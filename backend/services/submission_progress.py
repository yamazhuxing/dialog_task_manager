import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.models import Submission

PIPELINE_STEPS: list[tuple[str, str]] = [
    ("queued", "文件已接收"),
    ("convert", "格式转换"),
    ("quality_check", "质量检测"),
    ("difficulty", "难度评级"),
    ("persist", "样本入库"),
    ("done", "处理完成"),
]


def _step_label(step: str) -> str:
    for key, label in PIPELINE_STEPS:
        if key == step:
            return label
    return step


def append_processing_log(
    db: Session,
    submission: Submission,
    *,
    step: str,
    message: str | None = None,
    status: str = "running",
) -> None:
    log = json.loads(submission.processing_log_json or "[]")
    for item in log:
        if item.get("step") == step:
            item["status"] = status
            if message:
                item["message"] = message
            item["at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            break
    else:
        log.append(
            {
                "step": step,
                "label": _step_label(step),
                "message": message,
                "status": status,
                "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    submission.processing_log_json = json.dumps(log, ensure_ascii=False)
    submission.processing_step = step
    db.commit()
    db.refresh(submission)


def mark_step_done(db: Session, submission: Submission, step: str, message: str | None = None) -> None:
    append_processing_log(db, submission, step=step, message=message, status="done")


def init_processing_log(db: Session, submission: Submission) -> None:
    submission.processing_step = "queued"
    submission.processing_log_json = json.dumps(
        [
            {
                "step": "queued",
                "label": "文件已接收",
                "message": "等待后台处理",
                "status": "done",
                "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            }
        ],
        ensure_ascii=False,
    )
    submission.qc_errors_json = None
    db.commit()
    db.refresh(submission)
