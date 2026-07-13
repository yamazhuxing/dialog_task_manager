"""解析通过样本的 thinking_effort（验收要求 xhigh / max，比例 1:1）。"""

from __future__ import annotations

import json
from pathlib import Path

from backend.models import Sample, Submission

from backend.services.assistant_turns import resolve_session_dir

VALID_THINKING_EFFORTS = frozenset({"xhigh", "max"})


def effort_from_qc_stats(stats: dict | None) -> str | None:
    if not stats:
        return None
    effort = stats.get("thinking_effort")
    if isinstance(effort, str) and effort.strip():
        return effort.strip()
    return None


def effort_from_qc_stats_json(qc_stats_json: str | None) -> str | None:
    if not qc_stats_json:
        return None
    try:
        stats = json.loads(qc_stats_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(stats, dict):
        return None
    return effort_from_qc_stats(stats)


def effort_from_session_dir(convert_dir: str, sample: Sample) -> str | None:
    session_dir = resolve_session_dir(convert_dir, sample)
    if session_dir is None:
        return None
    json_files = sorted(session_dir.glob("*.json"))
    for json_file in json_files:
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        effort = data.get("thinking_effort")
        if isinstance(effort, str) and effort.strip():
            return effort.strip()
    return None


def resolve_thinking_effort(sample: Sample, submission: Submission | None = None) -> str | None:
    if sample.thinking_effort:
        return sample.thinking_effort

    if submission is not None:
        effort = effort_from_qc_stats_json(submission.qc_stats_json)
        if effort:
            return effort

    return effort_from_session_dir(sample.convert_dir, sample)


def read_thinking_effort_from_session(session_dir: Path) -> str | None:
    json_files = sorted(session_dir.glob("*.json"))
    for json_file in json_files:
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        effort = data.get("thinking_effort")
        if isinstance(effort, str) and effort.strip():
            return effort.strip()
    return None
