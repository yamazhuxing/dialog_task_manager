import json
from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.constants import SCENE_OPTIONS
from backend.models import Sample, Submission, Task, User
from backend.schemas import DashboardStats, TaskDetail, TaskListItem, UserStatsItem


def task_to_list_item(task: Task) -> TaskListItem:
    claimer = task.claimer.username if task.claimer else None
    turns = json.loads(task.turns_json or "[]")
    return TaskListItem(
        id=task.id,
        scene=task.scene,
        scene_label=task.scene_label,
        topic=task.topic,
        status=task.status,
        claimed_by=claimer,
        source_type=task.source_type,
        model_version=task.model_version,
        turn_count=len(turns),
    )


def task_to_detail(task: Task, latest_submission: Submission | None = None) -> TaskDetail:
    turns = json.loads(task.turns_json or "[]")
    return TaskDetail(
        id=task.id,
        scene=task.scene,
        scene_label=task.scene_label,
        topic=task.topic,
        constraint_text=task.constraint_text,
        status=task.status,
        claimed_by=task.claimer.username if task.claimer else None,
        source_type=task.source_type,
        model_version=task.model_version,
        turns=turns,
        latest_submission_status=latest_submission.status if latest_submission else None,
        latest_submission_error=latest_submission.error_message if latest_submission else None,
    )


def claim_task(db: Session, task: Task, user: User) -> Task:
    if task.status == "passed":
        raise ValueError("任务已完成，不可领取")
    if task.status == "claimed" and task.claimed_by_id != user.id:
        raise ValueError("任务已被其他用户领取")
    task.status = "claimed"
    task.claimed_by_id = user.id
    task.claimed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(task)
    return task


def release_task(db: Session, task: Task, user: User) -> Task:
    if task.status == "passed":
        raise ValueError("任务已完成，不可释放")
    if task.claimed_by_id != user.id and user.role != "admin":
        raise ValueError("只能释放自己领取的任务")
    task.status = "available"
    task.claimed_by_id = None
    task.claimed_at = None
    task.source_type = None
    task.model_version = None
    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, task: Task) -> None:
    if task.status == "passed":
        raise ValueError("已通过的任务不可删除，避免误删有效样本")

    sample = db.query(Sample).filter(Sample.task_id == task.id).first()
    if sample:
        raise ValueError("该任务已有入库样本，不可删除")

    db.query(Submission).filter(Submission.task_id == task.id).delete()
    db.delete(task)
    db.commit()


# 甲方验收比例：来源 openclaw:hermes ≈ 6:4，模型 opus 4.8 ≥ 70%，场景 13 类各 ≥1 且 max/min < 5
SOURCE_OPENCLAW_RATIO_MIN = 0.55
SOURCE_OPENCLAW_RATIO_MAX = 0.65
MODEL_OPUS48_RATIO_MIN = 0.70
SCENE_RATIO_MAX = 5
ASSISTANT_TURNS_MIN = 5


def _parse_assistant_turns(qc_stats_json: str | None) -> int | None:
    if not qc_stats_json:
        return None
    try:
        stats = json.loads(qc_stats_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(stats, dict):
        return None
    raw = stats.get("assistant_turns", stats.get("turns"))
    if raw is None:
        return None
    try:
        return int(float(str(raw).replace("%", "").strip()))
    except (TypeError, ValueError):
        return None


def get_dashboard_stats(db: Session) -> DashboardStats:
    passed_count = db.query(func.count(Sample.id)).scalar() or 0
    claimed_count = db.query(func.count(Task.id)).filter(Task.status == "claimed").scalar() or 0
    available_count = db.query(func.count(Task.id)).filter(Task.status == "available").scalar() or 0

    samples = db.query(Sample).all()
    source_distribution = Counter(s.source_type for s in samples)
    model_distribution = Counter(s.model_version for s in samples)
    scene_counts_raw = Counter(s.scene for s in samples)
    difficulty_distribution = Counter(s.difficulty or "unknown" for s in samples)

    # 13 类场景全部纳入统计（无样本记为 0）
    scene_distribution = {
        label: scene_counts_raw.get(code, 0) for code, label in SCENE_OPTIONS
    }
    scene_count_values = list(scene_distribution.values())
    scene_min = min(scene_count_values)
    scene_max = max(scene_count_values)
    scene_covered_count = sum(1 for count in scene_count_values if count > 0)
    scene_total_count = len(SCENE_OPTIONS)
    scene_ratio_ok = (
        scene_min >= 1
        and scene_max / scene_min < SCENE_RATIO_MAX
    )
    scene_range_ratio = round(scene_max / scene_min, 2) if scene_min >= 1 else None

    openclaw = source_distribution.get("openclaw", 0)
    hermes = source_distribution.get("hermes", 0)
    total_source = openclaw + hermes
    openclaw_ratio = openclaw / total_source if total_source else 0.0
    source_ratio_ok = (
        total_source > 0
        and SOURCE_OPENCLAW_RATIO_MIN <= openclaw_ratio <= SOURCE_OPENCLAW_RATIO_MAX
    )

    opus48 = model_distribution.get("opus-4.8", 0)
    opus46 = model_distribution.get("opus-4.6", 0)
    total_model = opus48 + opus46
    model_ratio_ok = total_model > 0 and (opus48 / total_model >= MODEL_OPUS48_RATIO_MIN)

    turn_rows = (
        db.query(Submission.qc_stats_json)
        .join(Sample, Sample.submission_id == Submission.id)
        .all()
    )
    turn_counts: list[int] = []
    for (qc_stats_json,) in turn_rows:
        turns = _parse_assistant_turns(qc_stats_json)
        if turns is not None:
            turn_counts.append(turns)

    assistant_turns_distribution = dict(Counter(str(n) for n in turn_counts))
    assistant_turns_min = min(turn_counts) if turn_counts else None
    assistant_turns_max = max(turn_counts) if turn_counts else None
    assistant_turns_avg = round(sum(turn_counts) / len(turn_counts), 1) if turn_counts else None
    assistant_turns_known_count = len(turn_counts)

    return DashboardStats(
        passed_count=passed_count,
        claimed_count=claimed_count,
        available_count=available_count,
        source_distribution=dict(source_distribution),
        model_distribution=dict(model_distribution),
        scene_distribution=scene_distribution,
        difficulty_distribution=dict(difficulty_distribution),
        source_ratio_ok=source_ratio_ok,
        model_ratio_ok=model_ratio_ok,
        scene_ratio_ok=scene_ratio_ok,
        scene_min_count=scene_min,
        scene_max_count=scene_max,
        scene_covered_count=scene_covered_count,
        scene_total_count=scene_total_count,
        scene_range_ratio=scene_range_ratio,
        assistant_turns_distribution=assistant_turns_distribution,
        assistant_turns_min=assistant_turns_min,
        assistant_turns_max=assistant_turns_max,
        assistant_turns_avg=assistant_turns_avg,
        assistant_turns_known_count=assistant_turns_known_count,
    )


def get_user_stats(db: Session) -> list[UserStatsItem]:
    users = db.query(User).filter(User.role == "user").all()
    results: list[UserStatsItem] = []
    for user in users:
        claimed_count = db.query(func.count(Task.id)).filter(
            Task.claimed_by_id == user.id, Task.status.in_(["claimed", "passed"])
        ).scalar() or 0
        submitted_count = db.query(func.count(Submission.id)).filter(Submission.user_id == user.id).scalar() or 0
        passed_count = db.query(func.count(Sample.id)).filter(Sample.user_id == user.id).scalar() or 0
        results.append(
            UserStatsItem(
                user_id=user.id,
                username=user.username,
                claimed_count=claimed_count,
                submitted_count=submitted_count,
                passed_count=passed_count,
            )
        )
    return results
