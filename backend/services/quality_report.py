from pathlib import Path

from quality_check import collect_validation_results, write_quality_report


def refresh_delivery_report(convert_dir: Path, qc_dir: Path) -> Path:
    """按 quality_check.py 相同规则，基于当前交付目录重新生成 report.txt。"""
    report_path = qc_dir / "openclaw-待质检数据-report" / "report.txt"
    results = collect_validation_results(convert_dir)
    write_quality_report(report_path, convert_dir, results)
    return report_path
