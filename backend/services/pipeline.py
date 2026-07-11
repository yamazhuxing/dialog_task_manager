import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from collections.abc import Callable

from backend.config import Settings

from backend.services.quality_report import refresh_delivery_report, remove_convert_metadata
from backend.models import Task
from backend.services.submission_validation import (
    SubmissionValidationError,
    ensure_dialogue_matches_task,
    sample_storage_dir_name,
)

SAMPLE_METADATA_FILENAME = "sample_metadata.json"


class PipelineError(Exception):
    def __init__(
        self,
        message: str,
        *,
        errors: list[str] | None = None,
        session_id: str | None = None,
        qc_stats: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.errors = errors or []
        self.session_id = session_id
        self.qc_stats = qc_stats or {}


def _collect_qc_failure_details(convert_session_dir: Path, work_dir: Path, session_id: str) -> tuple[list[str], dict]:
    """质检未通过时收集具体报错（复用 validate_session，不修改验收标准）。"""
    from quality_check import validate_session

    errors: list[str] = []
    stats: dict = {}
    try:
        _ok, errors, stats = validate_session(convert_session_dir)
    except Exception as exc:
        errors = [str(exc)]

    if not errors:
        fail_csv = (
            work_dir
            / "openclaw-待质检数据-质检结果"
            / "openclaw-待质检数据-fail"
            / "failures.csv"
        )
        if fail_csv.exists():
            import csv

            with open(fail_csv, encoding="utf-8-sig") as f:
                for row in csv.DictReader(f):
                    if row.get("Session ID") == session_id and row.get("失败原因"):
                        errors = [e.strip() for e in row["失败原因"].split(";") if e.strip()]
                        break

    if not errors:
        errors = ["质检未通过，session 未进入 pass 目录"]

    return errors, stats


def _run_script(settings: Settings, script: str, args: list[str]) -> None:
    cmd = [sys.executable, str(settings.project_root / script), *args]
    result = subprocess.run(
        cmd,
        cwd=str(settings.project_root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        raise PipelineError(output.strip() or f"{script} 执行失败")


def _read_report_stats(pass_session_dir: Path) -> dict:
    qc_root = pass_session_dir.parent
    report_dir = qc_root / f"{pass_session_dir.parent.name.replace('-pass', '')}-report"
    report_file = report_dir / "report.txt"
    stats = {}
    if report_file.exists():
        text = report_file.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if "turns=" in line:
                for part in line.split(","):
                    part = part.strip()
                    if "=" in part:
                        k, v = part.split("=", 1)
                        stats[k.strip()] = v.strip()
    return stats


def _read_difficulty(pass_session_dir: Path) -> tuple[str | None, str | None]:
    justification_file = pass_session_dir / "task_difficulty_justification.json"
    if not justification_file.exists():
        return None, None
    data = json.loads(justification_file.read_text(encoding="utf-8"))
    return data.get("task_difficulty"), data.get("justification")


def _detect_model(convert_session_dir: Path) -> str | None:
    json_files = sorted(convert_session_dir.glob("*.json"))
    if not json_files:
        return None
    data = json.loads(json_files[0].read_text(encoding="utf-8"))
    return data.get("request", {}).get("model") or data.get("model")


def run_openclaw_pipeline(
    settings: Settings,
    uploaded_file: Path,
    work_dir: Path,
    on_progress: Callable[[str, str, str], None] | None = None,
    task: Task | None = None,
    validate_session_id: Callable[[str], None] | None = None,
) -> dict:
    def progress(step: str, message: str, status: str = "running") -> None:
        if on_progress:
            on_progress(step, message, status)

    work_dir.mkdir(parents=True, exist_ok=True)
    input_dir = work_dir / "input"
    if input_dir.exists():
        shutil.rmtree(input_dir)
    input_dir.mkdir(parents=True)

    target_file = input_dir / uploaded_file.name
    shutil.copy2(uploaded_file, target_file)

    convert_dir = work_dir / "openclaw-待质检数据"
    pass_dir = work_dir / "openclaw-待质检数据-质检结果" / "openclaw-待质检数据-pass"

    progress("convert", "正在执行格式转换...")
    _run_script(
        settings,
        "convert_openclaw.py",
        ["--input_dir", str(input_dir), "--output_dir", str(convert_dir)],
    )
    progress("convert", "格式转换完成", "done")

    session_dirs = [d for d in convert_dir.iterdir() if d.is_dir()]
    if not session_dirs:
        raise PipelineError("转换后未生成 session 目录")

    session_id = session_dirs[0].name
    session_dir = convert_dir / session_id

    if validate_session_id:
        validate_session_id(session_id)

    if task is not None:
        try:
            ensure_dialogue_matches_task(session_dir, task)
        except SubmissionValidationError as exc:
            progress("convert", "任务校验未通过", "failed")
            raise PipelineError(exc.message, session_id=session_id) from exc

    progress("quality_check", "正在执行质量检测...")
    _run_script(settings, "quality_check.py", ["--input_dir", str(convert_dir)])

    pass_session_dir = pass_dir / session_id
    if not pass_session_dir.exists():
        errors, qc_stats = _collect_qc_failure_details(session_dir, work_dir, session_id)
        progress("quality_check", "质量检测未通过", "failed")
        raise PipelineError(
            "质检未通过",
            errors=errors,
            session_id=session_id,
            qc_stats=qc_stats,
        )
    progress("quality_check", "质量检测通过", "done")

    progress("difficulty", "正在评级任务难度...")
    _run_script(
        settings,
        "batch_deepseek_simple.py",
        [
            "--input_dir",
            str(pass_dir),
            "--api_key",
            settings.deepseek_api_key,
            "--api_base",
            settings.deepseek_api_base,
        ],
    )
    progress("difficulty", "难度评级完成", "done")

    detected_model = _detect_model(session_dir)
    difficulty, justification = _read_difficulty(pass_session_dir)
    qc_stats = _read_report_stats(pass_session_dir)

    return {
        "session_id": session_id,
        "detected_model": detected_model,
        "difficulty": difficulty,
        "justification": justification,
        "qc_stats": qc_stats,
        "convert_dir": convert_dir,
        "qc_root": pass_dir.parent,
        "pass_session_dir": pass_session_dir,
    }


def write_sample_metadata(session_dir: Path, metadata: dict) -> Path:
    """Write sample_metadata.json into a session directory."""
    path = session_dir / SAMPLE_METADATA_FILENAME
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def build_sample_metadata(
    *,
    task_id: int,
    session_id: str,
    scene: str,
    scene_label: str,
    topic: str,
    constraint_text: str | None,
    source_type: str,
    model_version: str,
    detected_model: str | None,
    difficulty: str | None,
) -> dict:
    return {
        "task_id": task_id,
        "session_id": session_id,
        "scene": scene,
        "scene_label": scene_label,
        "topic": topic,
        "constraint_text": constraint_text,
        "source_type": source_type,
        "model_version": model_version,
        "detected_model": detected_model,
        "difficulty": difficulty,
        "metadata_version": 1,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
    }


def persist_passed_sample(
    settings: Settings,
    *,
    task_id: int,
    session_id: str,
    work_dir: Path,
    uploaded_file: Path,
    result: dict,
    metadata: dict,
) -> dict[str, Path]:
    samples_root = settings.samples_dir
    openclaw_raw = samples_root / "openclaw"
    convert_master = samples_root / "openclaw-待质检数据"
    qc_master = samples_root / "openclaw-待质检数据-质检结果"
    pass_master = qc_master / "openclaw-待质检数据-pass"
    backup_root = settings.backups_dir / f"task_{task_id}_{session_id}"

    for path in (openclaw_raw, convert_master, pass_master, backup_root):
        path.mkdir(parents=True, exist_ok=True)

    raw_dest = openclaw_raw / f"{task_id}_{session_id}.jsonl"
    shutil.copy2(uploaded_file, raw_dest)

    storage_name = sample_storage_dir_name(task_id, session_id)
    convert_session_master = convert_master / storage_name
    pass_session_master = pass_master / storage_name
    for dest in (convert_session_master, pass_session_master):
        if dest.exists():
            shutil.rmtree(dest)

    shutil.copytree(result["convert_dir"] / session_id, convert_session_master)
    shutil.copytree(result["pass_session_dir"], pass_session_master)

    # 场景元数据仅写入 pass 目录（待质检数据目录保持纯转换结果）
    write_sample_metadata(pass_session_master, metadata)
    remove_convert_metadata(convert_master)

    if backup_root.exists():
        shutil.rmtree(backup_root)
    shutil.copytree(work_dir, backup_root)

    refresh_delivery_report(convert_master, qc_master)

    return {
        "raw_file": raw_dest,
        "convert_dir": convert_master,
        "qc_dir": qc_master,
        "backup_dir": backup_root,
    }
