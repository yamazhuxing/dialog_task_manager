"""解析通过样本的 assistant 轮次（验收标准 ≥ 5）。"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from backend.models import Sample, Submission

TURN_BUCKETS: list[tuple[str, str]] = [
    ("5", "5 轮（刚好达标）"),
    ("6-9", "6-9 轮"),
    ("10-14", "10-14 轮"),
    ("15-19", "15-19 轮"),
    ("20+", "20 轮及以上"),
]


def _parse_int_turn(raw: object) -> int | None:
    if raw is None:
        return None
    try:
        return int(float(str(raw).replace("%", "").strip()))
    except (TypeError, ValueError):
        return None


def turns_from_qc_stats(stats: dict | None) -> int | None:
    if not stats:
        return None
    return _parse_int_turn(stats.get("assistant_turns", stats.get("turns")))


def turns_from_qc_stats_json(qc_stats_json: str | None) -> int | None:
    if not qc_stats_json:
        return None
    try:
        stats = json.loads(qc_stats_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(stats, dict):
        return None
    return turns_from_qc_stats(stats)


def turns_from_report(qc_dir: str, session_id: str) -> int | None:
    report = Path(qc_dir) / "openclaw-待质检数据-report" / "report.txt"
    if not report.exists():
        return None
    lines = report.read_text(encoding="utf-8", errors="replace").splitlines()
    for i, line in enumerate(lines):
        if session_id not in line:
            continue
        for j in range(i, min(i + 3, len(lines))):
            match = re.search(r"turns=(\d+)", lines[j])
            if match:
                return int(match.group(1))
    return None


def turns_from_session_dir(convert_dir: str, session_id: str) -> int | None:
    session_dir = Path(convert_dir) / session_id
    if not session_dir.is_dir():
        return None
    try:
        from quality_check import validate_session

        _ok, _errors, stats = validate_session(session_dir)
        return _parse_int_turn(stats.get("assistant_turns"))
    except Exception:
        return None


def resolve_assistant_turns(sample: Sample, submission: Submission | None = None) -> int | None:
    if sample.assistant_turns is not None:
        return sample.assistant_turns

    if submission is not None:
        turns = turns_from_qc_stats_json(submission.qc_stats_json)
        if turns is not None:
            return turns

    turns = turns_from_report(sample.qc_dir, sample.session_id)
    if turns is not None:
        return turns

    return turns_from_session_dir(sample.convert_dir, sample.session_id)


def bucket_assistant_turns(turns: int) -> str:
    if turns == 5:
        return "5"
    if turns <= 9:
        return "6-9"
    if turns <= 14:
        return "10-14"
    if turns <= 19:
        return "15-19"
    return "20+"


def build_turn_bucket_distribution(turn_counts: list[int]) -> dict[str, int]:
    counter = Counter(bucket_assistant_turns(n) for n in turn_counts)
    return {key: counter.get(key, 0) for key, _label in TURN_BUCKETS}
