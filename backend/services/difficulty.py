"""任务难度评级：流水线调用、结果校验、已通过样本补评。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from sqlalchemy.orm import Session

from backend.config import Settings
from backend.models import Sample, Submission, Task, User
from backend.services.sample_paths import SourceSamplePaths
from backend.services.submission_validation import sample_storage_dir_name
from backend.services.questions import invalidate_delivery_zip_cache

SAMPLE_METADATA_FILENAME = "sample_metadata.json"

VALID_TASK_DIFFICULTIES = frozenset({"low", "medium", "high", "xhigh", "expert"})


class DifficultyError(Exception):
    pass


def is_valid_difficulty(difficulty: str | None) -> bool:
    return difficulty in VALID_TASK_DIFFICULTIES


def read_difficulty_result(pass_session_dir: Path) -> tuple[str | None, str | None]:
    justification_file = pass_session_dir / "task_difficulty_justification.json"
    if not justification_file.exists():
        return None, None
    data = json.loads(justification_file.read_text(encoding="utf-8"))
    return data.get("task_difficulty"), data.get("justification")


def resolve_pass_session_dir(settings: Settings, sample: Sample) -> Path:
    """定位已通过样本在交付目录中的 pass session 路径。"""
    storage_name = sample_storage_dir_name(sample.task_id, sample.session_id)
    paths = SourceSamplePaths.from_root(settings.samples_dir, sample.source_type)
    candidates = [
        paths.pass_dir / storage_name,
    ]

    backup_root = Path(sample.backup_dir) if sample.backup_dir else None
    if backup_root and backup_root.is_dir():
        backup_paths = SourceSamplePaths.from_root(backup_root, sample.source_type)
        candidates.extend(
            [
                backup_paths.pass_dir / storage_name,
                backup_paths.pass_dir / sample.session_id,
            ]
        )

    for path in candidates:
        if path.is_dir() and any(path.glob("*.json")):
            return path

    raise DifficultyError(
        f"未找到可评级的 pass 目录（task_id={sample.task_id}, session_id={sample.session_id}）"
    )


def run_difficulty_rating(settings: Settings, pass_dir: Path) -> None:
    if not settings.deepseek_api_key:
        raise DifficultyError("未配置 DEEPSEEK_API_KEY，无法进行难度评级")

    if not pass_dir.is_dir():
        raise DifficultyError(f"难度评级输入目录不存在: {pass_dir}")

    cmd = [
        sys.executable,
        str(settings.project_root / "batch_deepseek_simple.py"),
        "--input_dir",
        str(pass_dir),
        "--api_key",
        settings.deepseek_api_key,
        "--api_base",
        settings.deepseek_api_base,
    ]
    result = subprocess.run(
        cmd,
        cwd=str(settings.project_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        raise DifficultyError(output or "batch_deepseek_simple.py 执行失败")


def validate_difficulty_result(
    difficulty: str | None,
    *,
    justification: str | None = None,
) -> tuple[str, str | None]:
    if is_valid_difficulty(difficulty):
        return difficulty, justification

    detail = difficulty or "未生成有效难度"
    if justification and justification not in {detail, "调用失败", "格式错误"}:
        detail = f"{detail}（{justification[:200]}）"
    raise DifficultyError(f"难度评级失败: {detail}，请检查 DeepSeek API 后重试")


def rerate_passed_sample(db: Session, settings: Settings, task_id: int) -> dict:
    task = db.get(Task, task_id)
    if not task:
        raise DifficultyError("任务不存在")
    if task.status != "passed":
        raise DifficultyError("仅支持对已通过任务补评难度")

    sample = db.query(Sample).filter(Sample.task_id == task_id).first()
    if not sample:
        raise DifficultyError("该任务尚无入库样本，无法补评")

    pass_session_dir = resolve_pass_session_dir(settings, sample)
    run_difficulty_rating(settings, pass_session_dir.parent)

    difficulty, justification = read_difficulty_result(pass_session_dir)
    difficulty, justification = validate_difficulty_result(difficulty, justification=justification)

    submission = db.get(Submission, sample.submission_id)
    if submission:
        submission.difficulty = difficulty
        submission.justification = justification

    sample.difficulty = difficulty

    metadata_path = pass_session_dir / SAMPLE_METADATA_FILENAME
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["difficulty"] = difficulty
        metadata_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    db.commit()
    invalidate_delivery_zip_cache(settings)

    return {
        "task_id": task_id,
        "session_id": sample.session_id,
        "difficulty": difficulty,
        "justification": justification,
        "message": f"难度已更新为 {difficulty}",
    }


def list_invalid_difficulty_samples(db: Session) -> list[dict]:
    rows = (
        db.query(Sample, Task, User)
        .join(Task, Sample.task_id == Task.id)
        .join(User, Sample.user_id == User.id)
        .order_by(Sample.id.desc())
        .all()
    )
    results: list[dict] = []
    for sample, task, user in rows:
        if is_valid_difficulty(sample.difficulty):
            continue
        results.append(
            {
                "task_id": sample.task_id,
                "session_id": sample.session_id,
                "username": user.username,
                "topic": task.topic,
                "difficulty": sample.difficulty,
                "passed_at": task.passed_at,
            }
        )
    return results
