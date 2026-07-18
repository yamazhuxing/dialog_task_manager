import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from backend.config import get_settings
from backend.database import SessionLocal, get_db
from backend.deps import get_current_user, require_admin
from backend.models import Sample, Submission, Task, User
from backend.constants import SCENE_OPTIONS
from backend.schemas import (
    DashboardStats,
    QuestionImportResponse,
    SceneOption,
    SubmissionResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskDeleteResponse,
    TaskDetail,
    TaskListItem,
    DifficultyRetryResponse,
    InvalidDifficultySampleItem,
    UserStatsItem,
    ZipQcResponse,
)
from backend.services.pipeline import (
    PipelineError,
    build_sample_metadata,
    persist_passed_sample,
    run_hermes_pipeline,
    run_openclaw_pipeline,
)
from backend.services.assistant_turns import turns_from_qc_stats
from backend.services.thinking_effort import effort_from_qc_stats
from backend.services.submission_validation import (
    SubmissionValidationError,
    ensure_session_available,
    peek_session_id,
    source_extension_mismatch_message,
)
from backend.services.qc_hints import build_qc_hints
from backend.services.submission_progress import (
    append_processing_log,
    init_processing_log,
    mark_step_done,
)
from backend.services.questions import (
    create_delivery_zip,
    create_raw_delivery_zip,
    create_single_task,
    create_v2_delivery_zip,
    import_questions_from_data,
    load_questions_file,
)
from backend.services.difficulty import DifficultyError, list_invalid_difficulty_samples, rerate_passed_sample
from backend.services.external_zip_qc import ZipQcError, run_zip_quality_check
from backend.services.tasks import (
    claim_task,
    delete_task,
    get_dashboard_stats,
    get_user_stats,
    release_task,
    task_to_detail,
    task_to_list_item,
)

router = APIRouter(prefix="/api", tags=["api"])
settings = get_settings()


def _latest_submission(db: Session, task_id: int) -> Submission | None:
    return (
        db.query(Submission)
        .filter(Submission.task_id == task_id)
        .order_by(Submission.id.desc())
        .first()
    )


@router.get("/scenes", response_model=list[SceneOption])
def list_scenes(_: User = Depends(get_current_user)) -> list[SceneOption]:
    return [SceneOption(value=value, label=label) for value, label in SCENE_OPTIONS]


@router.post("/tasks", response_model=TaskCreateResponse)
def create_task(
    payload: TaskCreateRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> TaskCreateResponse:
    try:
        task = create_single_task(
            db,
            scene=payload.scene,
            topic=payload.topic,
            constraint_text=payload.constraint_text,
            turns=[turn.model_dump() for turn in payload.turns],
            created_by=admin,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    turns = json.loads(task.turns_json or "[]")
    return TaskCreateResponse(
        id=task.id,
        scene=task.scene,
        scene_label=task.scene_label,
        topic=task.topic,
        turn_count=len(turns),
    )


@router.get("/stats/dashboard", response_model=DashboardStats)
def dashboard_stats(db: Session = Depends(get_db), _: User = Depends(get_current_user)) -> DashboardStats:
    return get_dashboard_stats(db)


@router.get("/stats/users", response_model=list[UserStatsItem])
def user_stats(db: Session = Depends(get_db), _: User = Depends(require_admin)) -> list[UserStatsItem]:
    return get_user_stats(db)


@router.get("/tasks", response_model=list[TaskListItem])
def list_tasks(
    status_filter: str | None = None,
    scene: str | None = None,
    mine: bool = False,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TaskListItem]:
    query = db.query(Task)
    if status_filter:
        query = query.filter(Task.status == status_filter)
    if scene:
        query = query.filter(Task.scene == scene)
    if mine:
        query = query.filter(Task.claimed_by_id == user.id)
        # MySQL 不支持 NULLS LAST，用 is_(None) 把无领取时间的记录排到末尾
        tasks = query.order_by(Task.claimed_at.is_(None), Task.claimed_at.desc(), Task.id.desc()).all()
    else:
        tasks = query.order_by(Task.id.asc()).all()
    return [task_to_list_item(task) for task in tasks]


@router.get("/tasks/{task_id}", response_model=TaskDetail)
def get_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> TaskDetail:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    return task_to_detail(task, _latest_submission(db, task_id))


@router.delete("/tasks/{task_id}", response_model=TaskDeleteResponse)
def remove_task(
    task_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> TaskDeleteResponse:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        delete_task(db, task)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return TaskDeleteResponse(id=task_id, message="任务已删除")


@router.post("/tasks/{task_id}/claim", response_model=TaskDetail)
def claim(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> TaskDetail:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        claim_task(db, task, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.refresh(task)
    return task_to_detail(task)


@router.post("/tasks/{task_id}/release", response_model=TaskDetail)
def release(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> TaskDetail:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    try:
        release_task(db, task, user)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    db.refresh(task)
    return task_to_detail(task)


def _submission_to_response(submission: Submission) -> SubmissionResponse:
    processing_log = json.loads(submission.processing_log_json or "[]")
    qc_errors = json.loads(submission.qc_errors_json or "[]")
    qc_stats_raw = json.loads(submission.qc_stats_json or "{}")
    qc_stats = (
        {str(k): str(v) for k, v in qc_stats_raw.items()}
        if isinstance(qc_stats_raw, dict)
        else {}
    )
    return SubmissionResponse(
        id=submission.id,
        task_id=submission.task_id,
        status=submission.status,
        source_type=submission.source_type,
        model_version=submission.model_version or None,
        session_id=submission.session_id,
        detected_model=submission.detected_model,
        difficulty=submission.difficulty,
        error_message=submission.error_message,
        processing_step=submission.processing_step,
        processing_log=processing_log,
        qc_errors=qc_errors,
        qc_hints=build_qc_hints(qc_errors),
        qc_stats=qc_stats,
        created_at=submission.created_at,
    )


def _process_submission(submission_id: int) -> None:
    db = SessionLocal()
    try:
        submission = db.get(Submission, submission_id)
        if not submission:
            return
        task = db.get(Task, submission.task_id)
        if not task:
            return

        work_dir = settings.data_dir / "processing" / f"task_{task.id}" / f"sub_{submission.id}"
        uploaded_file = Path(submission.file_path)
        try:

            def on_progress(step: str, message: str, status: str = "running") -> None:
                submission_ref = db.get(Submission, submission_id)
                if not submission_ref:
                    return
                append_processing_log(db, submission_ref, step=step, message=message, status=status)

            def validate_session_id(session_id: str) -> None:
                ensure_session_available(db, session_id)

            pipeline_runner = (
                run_hermes_pipeline if submission.source_type == "hermes" else run_openclaw_pipeline
            )

            result = pipeline_runner(
                settings,
                uploaded_file,
                work_dir,
                on_progress=on_progress,
                task=task,
                validate_session_id=validate_session_id,
            )
            ensure_session_available(db, result["session_id"])
            submission.model_version = result["model_version"]
            submission.detected_model = result["detected_model"]
            metadata = build_sample_metadata(
                task_id=task.id,
                session_id=result["session_id"],
                scene=task.scene,
                scene_label=task.scene_label,
                topic=task.topic,
                constraint_text=task.constraint_text,
                source_type=submission.source_type,
                model_version=result["model_version"],
                detected_model=result["detected_model"],
                difficulty=result["difficulty"],
                thinking_effort=result.get("thinking_effort"),
            )
            append_processing_log(db, submission, step="persist", message="正在写入样本与备份...")
            paths = persist_passed_sample(
                settings,
                task_id=task.id,
                session_id=result["session_id"],
                work_dir=work_dir,
                uploaded_file=uploaded_file,
                result=result,
                metadata=metadata,
            )

            submission.status = "passed"
            submission.session_id = result["session_id"]
            submission.difficulty = result["difficulty"]
            submission.justification = result["justification"]
            submission.qc_stats_json = json.dumps(result["qc_stats"], ensure_ascii=False)
            submission.error_message = None
            submission.qc_errors_json = None
            mark_step_done(db, submission, "persist", "样本已入库")
            mark_step_done(db, submission, "done", "处理完成")

            existing_sample = db.query(Sample).filter(Sample.task_id == task.id).first()
            if existing_sample:
                db.delete(existing_sample)
                db.flush()

            sample = Sample(
                task_id=task.id,
                submission_id=submission.id,
                user_id=submission.user_id,
                source_type=submission.source_type,
                model_version=result["model_version"],
                detected_model=result["detected_model"],
                scene=task.scene,
                session_id=result["session_id"],
                difficulty=result["difficulty"],
                assistant_turns=turns_from_qc_stats(result.get("qc_stats")),
                thinking_effort=effort_from_qc_stats(result.get("qc_stats")) or result.get("thinking_effort"),
                raw_file_path=str(paths["raw_file"]),
                convert_dir=str(paths["convert_dir"]),
                qc_dir=str(paths["qc_dir"]),
                backup_dir=str(paths["backup_dir"]),
            )
            db.add(sample)

            task.status = "passed"
            task.source_type = submission.source_type
            task.model_version = result["model_version"]
            task.passed_at = datetime.now(timezone.utc)
            db.commit()
        except PipelineError as exc:
            submission.status = "failed"
            errors = exc.errors or [str(exc)]
            submission.session_id = exc.session_id or submission.session_id
            submission.qc_errors_json = json.dumps(errors, ensure_ascii=False)
            if exc.qc_stats:
                submission.qc_stats_json = json.dumps(exc.qc_stats, ensure_ascii=False)
            summary = errors[0] if errors else str(exc)
            submission.error_message = summary[:4000]
            append_processing_log(
                db,
                submission,
                step=submission.processing_step or "quality_check",
                message="处理失败",
                status="failed",
            )
            db.commit()
    finally:
        db.close()


@router.post("/tasks/{task_id}/upload", response_model=SubmissionResponse)
async def upload_task_file(
    task_id: int,
    background_tasks: BackgroundTasks,
    source_type: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SubmissionResponse:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "claimed" or task.claimed_by_id != user.id:
        raise HTTPException(status_code=400, detail="只能为自己已领取的任务上传文件")
    if source_type not in {"openclaw", "hermes"}:
        raise HTTPException(status_code=400, detail="来源类型无效")
    if source_type == "openclaw":
        filename = file.filename or "upload.jsonl"
    else:
        filename = file.filename or "upload.json"

    mismatch = source_extension_mismatch_message(source_type, filename)
    if mismatch:
        raise HTTPException(status_code=400, detail=mismatch)

    upload_dir = settings.uploads_dir / str(user.id) / str(task_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = upload_dir / f"{timestamp}_{filename}"
    content = await file.read()
    dest.write_bytes(content)

    try:
        peeked_session_id = peek_session_id(dest)
        ensure_session_available(db, peeked_session_id)
    except SubmissionValidationError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=exc.message) from None

    submission = Submission(
        task_id=task.id,
        user_id=user.id,
        source_type=source_type,
        model_version="",
        original_filename=filename,
        file_path=str(dest),
        status="processing",
    )
    db.add(submission)
    task.source_type = source_type
    db.commit()
    db.refresh(submission)
    init_processing_log(db, submission)

    background_tasks.add_task(_process_submission, submission.id)
    return _submission_to_response(submission)


@router.get("/tasks/{task_id}/submissions", response_model=list[SubmissionResponse])
def list_task_submissions(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[SubmissionResponse]:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.claimed_by_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权查看该任务提交记录")
    submissions = (
        db.query(Submission)
        .filter(Submission.task_id == task_id)
        .order_by(Submission.id.desc())
        .all()
    )
    return [_submission_to_response(item) for item in submissions]


@router.get("/submissions/{submission_id}", response_model=SubmissionResponse)
def get_submission(
    submission_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SubmissionResponse:
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="提交记录不存在")
    if submission.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权查看")
    return _submission_to_response(submission)


@router.post("/questions/import-default", response_model=QuestionImportResponse)
def import_default_questions(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> QuestionImportResponse:
    if not settings.questions_path.exists():
        raise HTTPException(status_code=404, detail="questions_1200.json 不存在")
    questions = load_questions_file(settings.questions_path)
    imported, skipped = import_questions_from_data(
        db,
        questions,
        filename=settings.questions_path.name,
        imported_by=admin,
        import_batch="default",
    )
    total = db.query(Task).count()
    return QuestionImportResponse(imported_count=imported, skipped_count=skipped, total_tasks=total)


@router.post("/questions/import", response_model=QuestionImportResponse)
async def import_questions_file(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
) -> QuestionImportResponse:
    content = await file.read()
    try:
        questions = json.loads(content.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="JSON 格式无效") from exc
    if not isinstance(questions, list):
        raise HTTPException(status_code=400, detail="题目文件必须是 JSON 数组")
    imported, skipped = import_questions_from_data(
        db,
        questions,
        filename=file.filename or "import.json",
        imported_by=admin,
    )
    total = db.query(Task).count()
    return QuestionImportResponse(imported_count=imported, skipped_count=skipped, total_tasks=total)


@router.get("/delivery/zip")
def download_delivery_zip(_: User = Depends(require_admin)):
    from fastapi.responses import FileResponse

    try:
        zip_path = create_delivery_zip(settings)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path=zip_path,
        filename=zip_path.name,
        media_type="application/zip",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/delivery/raw-zip")
def download_raw_delivery_zip(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    from fastapi.responses import FileResponse

    try:
        zip_path = create_raw_delivery_zip(db, settings)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path=zip_path,
        filename=zip_path.name,
        media_type="application/zip",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/delivery/v2-zip")
def download_v2_delivery_zip(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """新版交付 ZIP：session-scene.jsonl + hermes/openclaw 仅 pass；目录与难度 session_id 去任务前缀，不含 sample_metadata。"""
    from fastapi.responses import FileResponse

    try:
        zip_path = create_v2_delivery_zip(db, settings)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(
        path=zip_path,
        filename=zip_path.name,
        media_type="application/zip",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/admin/qc-zip", response_model=ZipQcResponse)
async def qc_external_delivery_zip(
    file: UploadFile = File(...),
    _: User = Depends(require_admin),
) -> ZipQcResponse:
    """上传与平台新版交付结构一致的 ZIP，对其中 hermes/openclaw session 执行质检。"""
    filename = file.filename or "upload.zip"
    if not filename.lower().endswith(".zip"):
        raise HTTPException(status_code=400, detail="请上传 .zip 文件")

    qc_dir = settings.data_dir / "qc_uploads"
    qc_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = qc_dir / f"{timestamp}_{Path(filename).name}"
    try:
        with dest.open("wb") as out:
            shutil.copyfileobj(file.file, out)
        result = run_zip_quality_check(dest)
    except ZipQcError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"质检失败: {exc}") from exc
    finally:
        dest.unlink(missing_ok=True)

    return ZipQcResponse(**result)


@router.get("/admin/difficulty-repairs", response_model=list[InvalidDifficultySampleItem])
def difficulty_repairs(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[InvalidDifficultySampleItem]:
    return list_invalid_difficulty_samples(db)


@router.post("/tasks/{task_id}/retry-difficulty", response_model=DifficultyRetryResponse)
def retry_task_difficulty(
    task_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> DifficultyRetryResponse:
    try:
        result = rerate_passed_sample(db, settings, task_id)
    except DifficultyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DifficultyRetryResponse(**result)
