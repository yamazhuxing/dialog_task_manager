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
    MetadataBackfillResponse,
    QuestionImportResponse,
    SceneOption,
    SubmissionResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskDeleteResponse,
    TaskDetail,
    TaskListItem,
    UserStatsItem,
)
from backend.services.pipeline import (
    PipelineError,
    SAMPLE_METADATA_FILENAME,
    build_sample_metadata,
    persist_passed_sample,
    run_openclaw_pipeline,
    write_sample_metadata,
)
from backend.services.questions import (
    create_delivery_zip,
    create_single_task,
    import_questions_from_data,
    load_questions_file,
)
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
            if submission.source_type == "hermes":
                raise PipelineError("Hermes 流水线第一期暂未开放，请使用 OpenClaw")

            result = run_openclaw_pipeline(settings, uploaded_file, work_dir)
            metadata = build_sample_metadata(
                task_id=task.id,
                session_id=result["session_id"],
                scene=task.scene,
                scene_label=task.scene_label,
                topic=task.topic,
                constraint_text=task.constraint_text,
                source_type=submission.source_type,
                model_version=submission.model_version,
                detected_model=result["detected_model"],
                difficulty=result["difficulty"],
            )
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
            submission.detected_model = result["detected_model"]
            submission.difficulty = result["difficulty"]
            submission.justification = result["justification"]
            submission.qc_stats_json = json.dumps(result["qc_stats"], ensure_ascii=False)
            submission.error_message = None

            existing_sample = db.query(Sample).filter(Sample.task_id == task.id).first()
            if existing_sample:
                db.delete(existing_sample)
                db.flush()

            sample = Sample(
                task_id=task.id,
                submission_id=submission.id,
                user_id=submission.user_id,
                source_type=submission.source_type,
                model_version=submission.model_version,
                detected_model=result["detected_model"],
                scene=task.scene,
                session_id=result["session_id"],
                difficulty=result["difficulty"],
                raw_file_path=str(paths["raw_file"]),
                convert_dir=str(paths["convert_dir"]),
                qc_dir=str(paths["qc_dir"]),
                backup_dir=str(paths["backup_dir"]),
            )
            db.add(sample)

            task.status = "passed"
            task.source_type = submission.source_type
            task.model_version = submission.model_version
            task.passed_at = datetime.now(timezone.utc)
            db.commit()
        except PipelineError as exc:
            submission.status = "failed"
            submission.error_message = str(exc)[:4000]
            db.commit()
    finally:
        db.close()


@router.post("/tasks/{task_id}/upload", response_model=SubmissionResponse)
async def upload_task_file(
    task_id: int,
    background_tasks: BackgroundTasks,
    source_type: str = Form(...),
    model_version: str = Form(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Submission:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.status != "claimed" or task.claimed_by_id != user.id:
        raise HTTPException(status_code=400, detail="只能为自己已领取的任务上传文件")
    if source_type not in {"openclaw", "hermes"}:
        raise HTTPException(status_code=400, detail="来源类型无效")
    if model_version not in {"opus-4.6", "opus-4.8"}:
        raise HTTPException(status_code=400, detail="模型版本无效")
    if source_type == "hermes":
        raise HTTPException(status_code=400, detail="Hermes 上传入口第一期暂未开放")

    filename = file.filename or "upload.jsonl"
    if not filename.endswith(".jsonl"):
        raise HTTPException(status_code=400, detail="OpenClaw 文件必须是 .jsonl 格式")

    upload_dir = settings.uploads_dir / str(user.id) / str(task_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = upload_dir / f"{timestamp}_{filename}"
    content = await file.read()
    dest.write_bytes(content)

    submission = Submission(
        task_id=task.id,
        user_id=user.id,
        source_type=source_type,
        model_version=model_version,
        original_filename=filename,
        file_path=str(dest),
        status="processing",
    )
    db.add(submission)
    task.source_type = source_type
    task.model_version = model_version
    db.commit()
    db.refresh(submission)

    background_tasks.add_task(_process_submission, submission.id)
    return submission


@router.get("/tasks/{task_id}/submissions", response_model=list[SubmissionResponse])
def list_task_submissions(
    task_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[Submission]:
    task = db.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="任务不存在")
    if task.claimed_by_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权查看该任务提交记录")
    return (
        db.query(Submission)
        .filter(Submission.task_id == task_id)
        .order_by(Submission.id.desc())
        .all()
    )


@router.get("/submissions/{submission_id}", response_model=SubmissionResponse)
def get_submission(
    submission_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Submission:
    submission = db.get(Submission, submission_id)
    if not submission:
        raise HTTPException(status_code=404, detail="提交记录不存在")
    if submission.user_id != user.id and user.role != "admin":
        raise HTTPException(status_code=403, detail="无权查看")
    return submission


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


@router.post("/samples/backfill-metadata", response_model=MetadataBackfillResponse)
def backfill_sample_metadata(
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
) -> MetadataBackfillResponse:
    samples = db.query(Sample).all()
    backfilled = 0
    for sample in samples:
        task = db.get(Task, sample.task_id)
        if not task:
            continue
        metadata = build_sample_metadata(
            task_id=task.id,
            session_id=sample.session_id,
            scene=sample.scene,
            scene_label=task.scene_label,
            topic=task.topic,
            constraint_text=task.constraint_text,
            source_type=sample.source_type,
            model_version=sample.model_version,
            detected_model=sample.detected_model,
            difficulty=sample.difficulty,
        )
        pass_session_dir = Path(sample.qc_dir) / "openclaw-待质检数据-pass" / sample.session_id
        convert_session_dir = Path(sample.convert_dir) / sample.session_id
        wrote = False
        if pass_session_dir.is_dir():
            write_sample_metadata(pass_session_dir, metadata)
            wrote = True
        if convert_session_dir.is_dir():
            convert_metadata = convert_session_dir / SAMPLE_METADATA_FILENAME
            if convert_metadata.exists():
                convert_metadata.unlink()
        if wrote:
            backfilled += 1
    return MetadataBackfillResponse(backfilled_count=backfilled)


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
    )
