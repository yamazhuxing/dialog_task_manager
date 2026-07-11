import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from backend.config import Settings

SAMPLE_METADATA_FILENAME = "sample_metadata.json"


class PipelineError(Exception):
    pass


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


def run_openclaw_pipeline(settings: Settings, uploaded_file: Path, work_dir: Path) -> dict:
    work_dir.mkdir(parents=True, exist_ok=True)
    input_dir = work_dir / "input"
    if input_dir.exists():
        shutil.rmtree(input_dir)
    input_dir.mkdir(parents=True)

    target_file = input_dir / uploaded_file.name
    shutil.copy2(uploaded_file, target_file)

    convert_dir = work_dir / "openclaw-待质检数据"
    pass_dir = work_dir / "openclaw-待质检数据-质检结果" / "openclaw-待质检数据-pass"

    _run_script(
        settings,
        "convert_openclaw.py",
        ["--input_dir", str(input_dir), "--output_dir", str(convert_dir)],
    )

    session_dirs = [d for d in convert_dir.iterdir() if d.is_dir()]
    if not session_dirs:
        raise PipelineError("转换后未生成 session 目录")

    session_id = session_dirs[0].name
    session_dir = convert_dir / session_id

    _run_script(settings, "quality_check.py", ["--input_dir", str(convert_dir)])

    pass_session_dir = pass_dir / session_id
    if not pass_session_dir.exists():
        fail_root = work_dir / "openclaw-待质检数据-质检结果" / "openclaw-待质检数据-fail"
        fail_session = fail_root / session_id
        errors = []
        if fail_session.exists():
            csv_path = fail_root / "failures.csv"
            if csv_path.exists():
                errors.append("质检未通过，详见 failures.csv")
        raise PipelineError("质检未通过。" + (" ".join(errors) if errors else ""))

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

    raw_dest = openclaw_raw / uploaded_file.name
    shutil.copy2(uploaded_file, raw_dest)

    convert_session_master = convert_master / session_id
    pass_session_master = pass_master / session_id
    for dest in (convert_session_master, pass_session_master):
        if dest.exists():
            shutil.rmtree(dest)

    shutil.copytree(result["convert_dir"] / session_id, convert_session_master)
    shutil.copytree(result["pass_session_dir"], pass_session_master)

    # 场景元数据仅写入 pass 目录（待质检数据目录保持纯转换结果）
    write_sample_metadata(pass_session_master, metadata)
    convert_metadata = convert_session_master / SAMPLE_METADATA_FILENAME
    if convert_metadata.exists():
        convert_metadata.unlink()

    if backup_root.exists():
        shutil.rmtree(backup_root)
    shutil.copytree(work_dir, backup_root)

    report_src = result["qc_root"] / "openclaw-待质检数据-report"
    report_dest = qc_master / "openclaw-待质检数据-report"
    report_dest.mkdir(parents=True, exist_ok=True)
    if report_src.exists():
        for item in report_src.iterdir():
            target = report_dest / item.name
            if item.is_file():
                shutil.copy2(item, target)

    return {
        "raw_file": raw_dest,
        "convert_dir": convert_master,
        "qc_dir": qc_master,
        "backup_dir": backup_root,
    }
