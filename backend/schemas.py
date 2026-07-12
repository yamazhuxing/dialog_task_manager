from datetime import datetime

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str
    role: str


class UserCreateRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    role: str = "user"


class UserResponse(BaseModel):
    id: int
    username: str
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


class TurnItem(BaseModel):
    round: int
    role: str
    content: str


class TaskListItem(BaseModel):
    id: int
    scene: str
    scene_label: str
    topic: str
    status: str
    claimed_by: str | None = None
    source_type: str | None = None
    model_version: str | None = None
    turn_count: int


class TaskDetail(BaseModel):
    id: int
    scene: str
    scene_label: str
    topic: str
    constraint_text: str | None
    status: str
    claimed_by: str | None = None
    source_type: str | None = None
    model_version: str | None = None
    turns: list[TurnItem]
    latest_submission_status: str | None = None
    latest_submission_error: str | None = None


class ProcessingLogItem(BaseModel):
    step: str
    label: str | None = None
    message: str | None = None
    status: str | None = None
    at: str | None = None


class QCHintItem(BaseModel):
    error: str
    essence: str
    remedy: str


class SubmissionResponse(BaseModel):
    id: int
    task_id: int
    status: str
    source_type: str
    model_version: str | None = None
    session_id: str | None = None
    detected_model: str | None = None
    difficulty: str | None = None
    error_message: str | None = None
    processing_step: str | None = None
    processing_log: list[ProcessingLogItem] = []
    qc_errors: list[str] = []
    qc_hints: list[QCHintItem] = []
    qc_stats: dict[str, str] = {}
    created_at: datetime

    class Config:
        from_attributes = True


class DashboardStats(BaseModel):
    passed_count: int
    target_count: int = 1000
    claimed_count: int
    available_count: int
    source_distribution: dict[str, int]
    model_distribution: dict[str, int]
    scene_distribution: dict[str, int]
    difficulty_distribution: dict[str, int]
    source_ratio_ok: bool
    model_ratio_ok: bool
    scene_ratio_ok: bool
    scene_min_count: int
    scene_max_count: int
    scene_covered_count: int
    scene_total_count: int = 13
    scene_range_ratio: float | None = None
    assistant_turns_distribution: dict[str, int] = {}
    assistant_turns_buckets: dict[str, int] = {}
    assistant_turns_min: int | None = None
    assistant_turns_max: int | None = None
    assistant_turns_avg: float | None = None
    assistant_turns_sample_count: int = 0
    assistant_turns_missing_count: int = 0


class UserStatsItem(BaseModel):
    user_id: int
    username: str
    role: str
    claimed_count: int
    in_progress_count: int
    submitted_count: int
    failed_count: int
    passed_count: int


class QuestionImportResponse(BaseModel):
    imported_count: int
    skipped_count: int
    total_tasks: int


class SceneOption(BaseModel):
    value: str
    label: str


class TaskTurnInput(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class TaskCreateRequest(BaseModel):
    scene: str
    topic: str = Field(min_length=1, max_length=255)
    constraint_text: str | None = Field(default=None, max_length=255)
    turns: list[TaskTurnInput] = Field(min_length=5, max_length=10)


class TaskCreateResponse(BaseModel):
    id: int
    scene: str
    scene_label: str
    topic: str
    turn_count: int


class TaskDeleteResponse(BaseModel):
    id: int
    message: str
