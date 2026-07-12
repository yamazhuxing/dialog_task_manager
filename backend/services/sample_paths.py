"""OpenClaw / Hermes 样本目录命名与路径解析。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SOURCE_TYPES = ("openclaw", "hermes")


def normalize_source_type(source_type: str) -> str:
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"无效来源类型: {source_type}")
    return source_type


def convert_basename(source_type: str) -> str:
    return f"{normalize_source_type(source_type)}-待质检数据"


def qc_basename(source_type: str) -> str:
    return f"{convert_basename(source_type)}-质检结果"


def pass_basename(source_type: str) -> str:
    return f"{convert_basename(source_type)}-pass"


def fail_basename(source_type: str) -> str:
    return f"{convert_basename(source_type)}-fail"


def report_basename(source_type: str) -> str:
    return f"{convert_basename(source_type)}-report"


@dataclass(frozen=True)
class SourceSamplePaths:
    source_type: str
    root: Path
    raw_dir: Path
    convert_dir: Path
    qc_dir: Path
    pass_dir: Path
    fail_dir: Path
    report_dir: Path

    @classmethod
    def from_root(cls, root: Path, source_type: str) -> SourceSamplePaths:
        source = normalize_source_type(source_type)
        convert_dir = root / convert_basename(source)
        qc_dir = root / qc_basename(source)
        return cls(
            source_type=source,
            root=root,
            raw_dir=root / source,
            convert_dir=convert_dir,
            qc_dir=qc_dir,
            pass_dir=qc_dir / pass_basename(source),
            fail_dir=qc_dir / fail_basename(source),
            report_dir=qc_dir / report_basename(source),
        )

    def has_passed_sessions(self) -> bool:
        return self.pass_dir.is_dir() and any(item.is_dir() for item in self.pass_dir.iterdir())


def delivery_report_path(qc_dir: Path) -> Path:
    convert_name = qc_dir.name.removesuffix("-质检结果")
    return qc_dir / f"{convert_name}-report" / "report.txt"


def iter_delivery_sources(samples_root: Path) -> list[SourceSamplePaths]:
    ready: list[SourceSamplePaths] = []
    for source_type in SOURCE_TYPES:
        paths = SourceSamplePaths.from_root(samples_root, source_type)
        if paths.has_passed_sessions():
            ready.append(paths)
    return ready
