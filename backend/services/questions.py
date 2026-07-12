import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.config import Settings
from backend.constants import MAX_TASK_TURNS, MIN_TASK_TURNS, SCENE_LABELS
from backend.models import QuestionImport, Task, User
from backend.services.quality_report import remove_convert_metadata
from backend.services.sample_paths import iter_delivery_sources

DELIVERY_ZIP_NAME = "delivery_latest.zip"
DELIVERY_ZIP_META_NAME = "delivery_latest.meta.json"


def import_questions_from_data(
    db: Session,
    questions: list[dict],
    *,
    filename: str,
    imported_by: User,
    import_batch: str | None = None,
) -> tuple[int, int]:
    imported = 0
    skipped = 0
    batch = import_batch or datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")

    for item in questions:
        task_id = int(item["id"])
        exists = db.get(Task, task_id)
        if exists:
            skipped += 1
            continue
        task = Task(
            id=task_id,
            scene=item["scene"],
            scene_label=item.get("scene_label", item["scene"]),
            topic=item.get("topic", ""),
            constraint_text=item.get("constraint"),
            turns_json=json.dumps(item.get("turns", []), ensure_ascii=False),
            design_notes_json=json.dumps(item.get("design_notes"), ensure_ascii=False)
            if item.get("design_notes")
            else None,
            import_batch=batch,
        )
        db.add(task)
        imported += 1

    record = QuestionImport(
        filename=filename,
        imported_count=imported,
        skipped_count=skipped,
        imported_by_id=imported_by.id,
    )
    db.add(record)
    db.commit()
    return imported, skipped


def load_questions_file(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("题目文件必须是 JSON 数组")
    return data


def create_single_task(db: Session, *, scene: str, topic: str, constraint_text: str | None, turns: list[dict], created_by: User) -> Task:
    scene_label = SCENE_LABELS.get(scene)
    if not scene_label:
        raise ValueError("无效的场景类型")

    if not (MIN_TASK_TURNS <= len(turns) <= MAX_TASK_TURNS):
        raise ValueError(f"提问轮数需在 {MIN_TASK_TURNS}~{MAX_TASK_TURNS} 之间")

    normalized_turns = []
    for idx, turn in enumerate(turns, start=1):
        content = (turn.get("content") or "").strip()
        if not content:
            raise ValueError(f"第 {idx} 轮提问不能为空")
        normalized_turns.append({"round": idx, "role": "user", "content": content})

    max_id = db.query(func.max(Task.id)).scalar() or 0
    task = Task(
        id=max_id + 1,
        scene=scene,
        scene_label=scene_label,
        topic=topic.strip(),
        constraint_text=constraint_text.strip() if constraint_text else None,
        turns_json=json.dumps(normalized_turns, ensure_ascii=False),
        design_notes_json=json.dumps(
            {
                "rounds": len(normalized_turns),
                "generator": "manual",
                "created_by": created_by.username,
            },
            ensure_ascii=False,
        ),
        import_batch="manual",
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def _delivery_fingerprint(settings: Settings) -> tuple[int, float, list[tuple[str, Path]]]:
    """统计交付目录文件数、最新修改时间，并收集待打包目录。"""
    delivery_sources = iter_delivery_sources(settings.samples_dir)
    if not delivery_sources:
        raise FileNotFoundError("暂无已通过样本，请先完成至少一条通过样本")

    zip_entries: list[tuple[str, Path]] = []
    file_count = 0
    max_mtime = 0.0
    for paths in delivery_sources:
        if not paths.convert_dir.exists() or not paths.qc_dir.exists():
            continue
        remove_convert_metadata(paths.convert_dir)
        zip_entries.append((paths.convert_dir.name, paths.convert_dir))
        zip_entries.append((paths.qc_dir.name, paths.qc_dir))

    if not zip_entries:
        raise FileNotFoundError("暂无可交付的样本目录，请先完成至少一条通过样本")

    for _root_name, folder in zip_entries:
        for file_path in folder.rglob("*"):
            if file_path.is_file():
                file_count += 1
                max_mtime = max(max_mtime, file_path.stat().st_mtime)
    return file_count, max_mtime, zip_entries


def _read_delivery_cache_meta(meta_path: Path) -> dict | None:
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _write_delivery_zip(settings: Settings, zip_entries: list[tuple[str, Path]], zip_path: Path) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for root_name, folder in zip_entries:
            for file_path in folder.rglob("*"):
                if file_path.is_file():
                    arcname = f"{root_name}/{file_path.relative_to(folder).as_posix()}"
                    zf.write(file_path, arcname)


def create_delivery_zip(settings: Settings, *, force: bool = False) -> Path:
    file_count, max_mtime, zip_entries = _delivery_fingerprint(settings)
    cache_zip = settings.data_dir / DELIVERY_ZIP_NAME
    cache_meta = settings.data_dir / DELIVERY_ZIP_META_NAME

    cached = _read_delivery_cache_meta(cache_meta)
    if (
        not force
        and cache_zip.exists()
        and cached
        and cached.get("file_count") == file_count
        and cached.get("max_mtime") == max_mtime
    ):
        return cache_zip

    _write_delivery_zip(settings, zip_entries, cache_zip)
    cache_meta.write_text(
        json.dumps(
            {
                "file_count": file_count,
                "max_mtime": max_mtime,
                "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return cache_zip


def invalidate_delivery_zip_cache(settings: Settings) -> None:
    """有新样本入库后丢弃缓存，下次下载时重新打包。"""
    for name in (DELIVERY_ZIP_NAME, DELIVERY_ZIP_META_NAME):
        (settings.data_dir / name).unlink(missing_ok=True)
