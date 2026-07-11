from pathlib import Path

from quality_check import collect_validation_results, write_quality_report

SAMPLE_METADATA_FILENAME = "sample_metadata.json"


def remove_convert_metadata(convert_dir: Path) -> int:
    """待质检数据目录不应含场景元数据，清理历史残留。"""
    if not convert_dir.exists():
        return 0
    removed = 0
    for path in convert_dir.rglob(SAMPLE_METADATA_FILENAME):
        path.unlink(missing_ok=True)
        removed += 1
    return removed


def refresh_delivery_report(convert_dir: Path, qc_dir: Path) -> Path:
    """按 quality_check.py 相同规则，基于当前交付目录重新生成 report.txt。"""
    remove_convert_metadata(convert_dir)
    report_path = qc_dir / "openclaw-待质检数据-report" / "report.txt"
    results = collect_validation_results(convert_dir)
    write_quality_report(report_path, convert_dir, results)
    return report_path
