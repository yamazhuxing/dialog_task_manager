from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    claimed_tasks: Mapped[list["Task"]] = relationship(back_populates="claimer")
    submissions: Mapped[list["Submission"]] = relationship(back_populates="user")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scene: Mapped[str] = mapped_column(String(64), index=True)
    scene_label: Mapped[str] = mapped_column(String(128))
    topic: Mapped[str] = mapped_column(String(255))
    constraint_text: Mapped[str | None] = mapped_column("constraint", String(255), nullable=True)
    turns_json: Mapped[str] = mapped_column(Text)
    design_notes_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="available", index=True)
    claimed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    passed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    import_batch: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    claimer: Mapped[User | None] = relationship(back_populates="claimed_tasks")
    submissions: Mapped[list["Submission"]] = relationship(back_populates="task")
    sample: Mapped["Sample | None"] = relationship(back_populates="task", uselist=False)


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(16))
    model_version: Mapped[str] = mapped_column(String(16))
    original_filename: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(512))
    status: Mapped[str] = mapped_column(String(16), default="processing", index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detected_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    difficulty: Mapped[str | None] = mapped_column(String(16), nullable=True)
    justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    qc_stats_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_step: Mapped[str | None] = mapped_column(String(32), nullable=True)
    processing_log_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    qc_errors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    task: Mapped[Task] = relationship(back_populates="submissions")
    user: Mapped[User] = relationship(back_populates="submissions")


class Sample(Base):
    __tablename__ = "samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), unique=True, index=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), unique=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source_type: Mapped[str] = mapped_column(String(16), index=True)
    model_version: Mapped[str] = mapped_column(String(16), index=True)
    detected_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    scene: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    difficulty: Mapped[str | None] = mapped_column(String(16), nullable=True)
    assistant_turns: Mapped[int | None] = mapped_column(Integer, nullable=True)
    thinking_effort: Mapped[str | None] = mapped_column(String(16), nullable=True)
    raw_file_path: Mapped[str] = mapped_column(String(512))
    convert_dir: Mapped[str] = mapped_column(String(512))
    qc_dir: Mapped[str] = mapped_column(String(512))
    backup_dir: Mapped[str] = mapped_column(String(512))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    task: Mapped[Task] = relationship(back_populates="sample")


class QuestionImport(Base):
    __tablename__ = "question_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255))
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0)
    imported_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
