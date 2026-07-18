"""第三方交付 ZIP 质检：结构与平台新版交付 ZIP 一致，复用 quality_check.validate_session。"""

from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from pathlib import Path

from backend.services.sample_paths import SOURCE_TYPES
from backend.services.questions import SESSION_SCENE_JSONL_NAME
from backend.services.difficulty import VALID_TASK_DIFFICULTIES, is_valid_difficulty

from quality_check import NON_CALL_FILENAMES, validate_session

DIFFICULTY_JUSTIFICATION_FILENAME = "task_difficulty_justification.json"


class ZipQcError(Exception):
    pass


def _validate_difficulty_justification(session_dir: Path, session_id: str) -> tuple[str | None, list[str]]:
    """
    校验 task_difficulty_justification.json：
    task_difficulty 只能是 low/medium/high/xhigh/expert，否则视为失败。
    """
    path = session_dir / DIFFICULTY_JUSTIFICATION_FILENAME
    if not path.is_file():
        return None, [f"缺少 {DIFFICULTY_JUSTIFICATION_FILENAME}"]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, [f"{DIFFICULTY_JUSTIFICATION_FILENAME} 无法解析: {exc}"]

    if not isinstance(data, dict):
        return None, [f"{DIFFICULTY_JUSTIFICATION_FILENAME} 格式无效（应为 JSON 对象）"]

    errors: list[str] = []
    file_session_id = data.get("session_id")
    if isinstance(file_session_id, str) and file_session_id.strip() and file_session_id.strip() != session_id:
        errors.append(
            f"{DIFFICULTY_JUSTIFICATION_FILENAME} 中 session_id='{file_session_id}' 与目录名不一致"
        )

    difficulty = data.get("task_difficulty")
    if not isinstance(difficulty, str) or not difficulty.strip():
        errors.append(
            f"{DIFFICULTY_JUSTIFICATION_FILENAME} 缺少 task_difficulty（允许: {sorted(VALID_TASK_DIFFICULTIES)}）"
        )
        return None, errors

    difficulty = difficulty.strip()
    if not is_valid_difficulty(difficulty):
        errors.append(
            f"task_difficulty='{difficulty}' 不合法（允许: {sorted(VALID_TASK_DIFFICULTIES)}），评级失败或无效"
        )
        return difficulty, errors

    return difficulty, errors


def _looks_like_session_dir(path: Path) -> bool:
    if not path.is_dir():
        return False
    for json_file in path.glob("*.json"):
        if json_file.name in NON_CALL_FILENAMES:
            continue
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(data, dict) and "request" in data:
            return True
    return False


def _resolve_delivery_root(extract_dir: Path) -> Path:
    """定位含 openclaw/hermes 的交付根目录（兼容外层多包一层文件夹）。"""
    if any((extract_dir / name).is_dir() for name in SOURCE_TYPES):
        return extract_dir
    if (extract_dir / SESSION_SCENE_JSONL_NAME).is_file():
        return extract_dir

    children = [p for p in extract_dir.iterdir() if not p.name.startswith(".") and p.name != "__MACOSX"]
    dirs = [p for p in children if p.is_dir()]
    if len(dirs) == 1 and any((dirs[0] / name).is_dir() for name in SOURCE_TYPES):
        return dirs[0]
    if len(dirs) == 1 and (dirs[0] / SESSION_SCENE_JSONL_NAME).is_file():
        return dirs[0]
    return extract_dir


def _read_session_scene_map(root: Path) -> tuple[dict[str, str], list[str]]:
    """读取 session-scene.jsonl，返回 {session_id: scene} 与结构告警。"""
    warnings: list[str] = []
    path = root / SESSION_SCENE_JSONL_NAME
    if not path.is_file():
        warnings.append(f"未找到 {SESSION_SCENE_JSONL_NAME}（可选，不影响逐条质检）")
        return {}, warnings

    mapping: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        warnings.append(f"无法读取 {SESSION_SCENE_JSONL_NAME}: {exc}")
        return {}, warnings

    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            warnings.append(f"{SESSION_SCENE_JSONL_NAME} 第 {line_no} 行不是合法 JSON")
            continue
        if not isinstance(item, dict):
            warnings.append(f"{SESSION_SCENE_JSONL_NAME} 第 {line_no} 行不是对象")
            continue
        session_id = item.get("session_id")
        scene = item.get("scene")
        if not isinstance(session_id, str) or not session_id.strip():
            warnings.append(f"{SESSION_SCENE_JSONL_NAME} 第 {line_no} 行缺少 session_id")
            continue
        if not isinstance(scene, str) or not scene.strip():
            warnings.append(f"{SESSION_SCENE_JSONL_NAME} 第 {line_no} 行缺少 scene")
            continue
        sid = session_id.strip()
        if sid in mapping:
            warnings.append(f"{SESSION_SCENE_JSONL_NAME} 中 session_id 重复: {sid}")
        mapping[sid] = scene.strip()
    return mapping, warnings


def _discover_sessions(root: Path) -> list[tuple[str, Path]]:
    found: list[tuple[str, Path]] = []
    for source_type in SOURCE_TYPES:
        source_dir = root / source_type
        if not source_dir.is_dir():
            continue
        for child in sorted(source_dir.iterdir()):
            if _looks_like_session_dir(child):
                found.append((source_type, child))
    return found


def _safe_extract_zip(zip_path: Path, dest: Path) -> None:
    """解压 ZIP，并拒绝路径穿越。"""
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in Path(name).parts:
                raise ZipQcError(f"ZIP 含非法路径: {info.filename}")
        zf.extractall(dest)


def run_zip_quality_check(zip_path: Path) -> dict:
    """
    对与平台新版交付结构一致的 ZIP 执行质检。

    期望结构：
      session-scene.jsonl（可选）
      openclaw/{session_id}/*.json
      hermes/{session_id}/*.json
    """
    if not zip_path.is_file():
        raise ZipQcError("上传文件不存在")
    if not zipfile.is_zipfile(zip_path):
        raise ZipQcError("上传文件不是合法 ZIP")

    work_dir = Path(tempfile.mkdtemp(prefix="zip_qc_"))
    try:
        extract_dir = work_dir / "extract"
        extract_dir.mkdir(parents=True, exist_ok=True)
        try:
            _safe_extract_zip(zip_path, extract_dir)
        except zipfile.BadZipFile as exc:
            raise ZipQcError("ZIP 文件损坏或无法解压") from exc

        root = _resolve_delivery_root(extract_dir)
        scene_map, structure_warnings = _read_session_scene_map(root)
        sessions = _discover_sessions(root)
        if not sessions:
            raise ZipQcError(
                "未找到可质检的 session 目录，请确认 ZIP 含 openclaw/ 或 hermes/ 下的 call 样本"
            )

        results: list[dict] = []
        for source_type, session_dir in sessions:
            session_id = session_dir.name
            extra_errors: list[str] = []
            try:
                ok, errors, stats = validate_session(session_dir)
            except Exception as exc:
                results.append(
                    {
                        "source_type": source_type,
                        "session_id": session_id,
                        "status": "error",
                        "errors": [str(exc)],
                        "thinking_effort": None,
                        "assistant_turns": None,
                        "difficulty": None,
                        "scene": scene_map.get(session_id),
                    }
                )
                continue

            # 目录名应与 call 内 session_id 一致
            try:
                from quality_check import load_session_calls

                calls = load_session_calls(session_dir)
                call_ids = {c.get("session_id") for c in calls if c.get("session_id")}
                if call_ids and session_id not in call_ids:
                    extra_errors.append(
                        f"目录名 '{session_id}' 与 call 内 session_id {call_ids} 不一致"
                    )
                if len(call_ids) > 1:
                    extra_errors.append(f"call 内存在多个 session_id: {call_ids}")
            except Exception:
                pass

            if scene_map and session_id not in scene_map:
                extra_errors.append(f"{SESSION_SCENE_JSONL_NAME} 中缺少该 session_id")

            difficulty, difficulty_errors = _validate_difficulty_justification(session_dir, session_id)
            extra_errors.extend(difficulty_errors)

            all_errors = list(errors) + extra_errors
            status = "pass" if ok and not extra_errors else "fail"
            results.append(
                {
                    "source_type": source_type,
                    "session_id": session_id,
                    "status": status,
                    "errors": all_errors,
                    "thinking_effort": stats.get("thinking_effort"),
                    "assistant_turns": stats.get("assistant_turns"),
                    "difficulty": difficulty,
                    "scene": scene_map.get(session_id),
                }
            )

        found_ids = {item["session_id"] for item in results}
        for sid in sorted(set(scene_map) - found_ids):
            structure_warnings.append(
                f"{SESSION_SCENE_JSONL_NAME} 中有 session_id={sid}，但 ZIP 中未找到对应目录"
            )

        pass_count = sum(1 for r in results if r["status"] == "pass")
        fail_count = sum(1 for r in results if r["status"] == "fail")
        error_count = sum(1 for r in results if r["status"] == "error")
        return {
            "filename": zip_path.name,
            "total": len(results),
            "pass_count": pass_count,
            "fail_count": fail_count,
            "error_count": error_count,
            "structure_warnings": structure_warnings,
            "sessions": results,
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
