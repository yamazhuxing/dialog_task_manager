"""提交校验：session 去重、对话与任务匹配（不暴露具体规则）。"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy.orm import Session

from backend.models import Sample, Task

CONTENT_MISMATCH_MESSAGE = "上传失败：任务与对话文件不匹配，请更换对话文件后重试"
DETECTED_MODEL_MAP = {
    "claude-opus-4-6-thinking": "claude-opus-4-6",
    "claude-opus-4-6": "claude-opus-4-6",
    "claude-opus-4-8-thinking": "claude-opus-4-8",
    "claude-opus-4-8": "claude-opus-4-8",
}

MODEL_VERSION_MAP = {
    "claude-opus-4-6": "opus-4.6",
    "claude-opus-4-8": "opus-4.8",
}


def normalize_detected_model(raw: str | None) -> str | None:
    if not raw:
        return None
    text = raw.strip()
    return DETECTED_MODEL_MAP.get(text, text)


def model_version_from_detected(raw: str | None) -> str | None:
    normalized = normalize_detected_model(raw)
    if not normalized:
        return None
    return MODEL_VERSION_MAP.get(normalized)


def session_reused_message(existing_task_id: int) -> str:
    return f"上传失败：该对话文件已被任务 #{existing_task_id} 使用，请重新制作后上传"


class SubmissionValidationError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def normalize_text(text: str) -> str:
    return text.strip()


def sample_storage_dir_name(task_id: int, session_id: str) -> str:
    return f"{task_id}_{session_id}"


def peek_session_id(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    if suffix == ".json":
        try:
            data = json.loads(file_path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            data = None
        if isinstance(data, dict):
            session_id = data.get("id")
            if isinstance(session_id, str) and session_id.strip():
                return session_id.strip()
        stem = file_path.stem
        if stem.startswith("session-"):
            return stem[len("session-") :]
        return stem

    session_id = file_path.stem
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return session_id

    decoder = json.JSONDecoder()
    pos = 0
    while pos < len(text):
        while pos < len(text) and text[pos].isspace():
            pos += 1
        if pos >= len(text):
            break
        try:
            event, end = decoder.raw_decode(text, pos)
        except json.JSONDecodeError:
            break
        if isinstance(event, dict) and event.get("type") == "session":
            found = event.get("id")
            if isinstance(found, str) and found.strip():
                return found.strip()
        pos = end
    return session_id


def session_already_used(db: Session, session_id: str) -> Sample | None:
    return db.query(Sample).filter(Sample.session_id == session_id).first()


def ensure_session_available(db: Session, session_id: str) -> None:
    existing = session_already_used(db, session_id)
    if existing:
        raise SubmissionValidationError(session_reused_message(existing.task_id))


def task_turn_texts(task: Task) -> list[str]:
    turns = json.loads(task.turns_json or "[]")
    texts: list[str] = []
    for turn in turns:
        content = normalize_text(str(turn.get("content", "")))
        if content:
            texts.append(content)
    return texts


def extract_user_texts_from_session(session_dir: Path) -> list[str]:
    from quality_check import load_session_calls

    texts: list[str] = []
    for call in load_session_calls(session_dir):
        for msg in call.get("request", {}).get("messages", []):
            if msg.get("role") != "user":
                continue
            content = msg.get("content", [])
            if not isinstance(content, list):
                continue
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    part = normalize_text(str(block.get("text", "")))
                    if part:
                        parts.append(part)
            if parts:
                texts.append(normalize_text("\n".join(parts)))
    return texts


def dialogue_matches_task(session_dir: Path, task: Task) -> bool:
    user_texts = {normalize_text(t) for t in extract_user_texts_from_session(session_dir)}
    if not user_texts:
        return False
    for turn_text in task_turn_texts(task):
        if turn_text in user_texts:
            return True
    return False


def ensure_dialogue_matches_task(session_dir: Path, task: Task) -> None:
    if not dialogue_matches_task(session_dir, task):
        raise SubmissionValidationError(CONTENT_MISMATCH_MESSAGE)
