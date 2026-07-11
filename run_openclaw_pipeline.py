#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenClaw 一键流水线：格式转换 → 质检 → 难度评级

用法：
  uv run python run_openclaw_pipeline.py --input_dir sample/openclaw
  uv run python run_openclaw_pipeline.py --input_dir sample/openclaw --skip_rate
  uv run python run_openclaw_pipeline.py --input_dir sample/openclaw --api_key sk-xxx
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
DEFAULT_API_KEY = "sk-69d327c6f2e7492d892cfb29d94757c1"
DEFAULT_API_BASE = "https://api.deepseek.com"


def run_step(title: str, script: str, args: list[str]) -> None:
    print(f"\n{'=' * 60}")
    print(f"[步骤] {title}")
    print("=" * 60)
    cmd = [sys.executable, str(ROOT / script), *args]
    print(f"[命令] {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print(f"\n[失败] {title} 退出码={result.returncode}")
        sys.exit(result.returncode)
    print(f"[完成] {title}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OpenClaw 一键流水线：转换 → 质检 → 难度评级",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  uv run python run_openclaw_pipeline.py --input_dir sample/openclaw
  uv run python run_openclaw_pipeline.py --input_dir sample/openclaw --skip_rate
        """,
    )
    parser.add_argument("--input_dir", required=True, help="OpenClaw 原始 .jsonl 所在目录")
    parser.add_argument("--output_dir", help="转换输出目录（可选，默认自动生成）")
    parser.add_argument("--api_key", default=DEFAULT_API_KEY, help="DeepSeek API Key")
    parser.add_argument("--api_base", default=DEFAULT_API_BASE, help="DeepSeek API 地址")
    parser.add_argument(
        "--skip_rate",
        action="store_true",
        help="跳过难度评级（只做转换+质检）",
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir).resolve()
    if not input_dir.exists():
        print(f"[错误] 输入目录不存在: {input_dir}")
        sys.exit(1)

    if args.output_dir:
        convert_dir = Path(args.output_dir).resolve()
    else:
        convert_dir = input_dir.parent / f"{input_dir.name}-待质检数据"

    qc_root = convert_dir.parent / f"{convert_dir.name}-质检结果"
    pass_dir = qc_root / f"{convert_dir.name}-pass"

    print("=" * 60)
    print("OpenClaw 一键流水线")
    print("=" * 60)
    print(f"[原始输入] {input_dir}")
    print(f"[转换输出] {convert_dir}")
    print(f"[质检输出] {qc_root}")
    print(f"[合格目录] {pass_dir}")
    if args.skip_rate:
        print("[难度评级] 跳过")
    else:
        print(f"[API地址] {args.api_base}")

    # 1) 格式转换
    convert_args = ["--input_dir", str(input_dir), "--output_dir", str(convert_dir)]
    run_step("1/3 格式转换 (convert_openclaw.py)", "convert_openclaw.py", convert_args)

    # 2) 质检
    run_step("2/3 质检 (quality_check.py)", "quality_check.py", ["--input_dir", str(convert_dir)])

    if not pass_dir.exists():
        print(f"[错误] 未找到合格目录: {pass_dir}")
        sys.exit(1)

    pass_sessions = [d for d in pass_dir.iterdir() if d.is_dir()]
    print(f"\n[质检通过] {len(pass_sessions)} 个 session")
    if not pass_sessions:
        print("[结束] 无合格 session，跳过难度评级")
        sys.exit(0)

    # 3) 难度评级
    if args.skip_rate:
        print("\n[跳过] 难度评级")
    else:
        rate_args = [
            "--input_dir",
            str(pass_dir),
            "--api_key",
            args.api_key,
            "--api_base",
            args.api_base,
        ]
        run_step("3/3 难度评级 (batch_deepseek_simple.py)", "batch_deepseek_simple.py", rate_args)

    print(f"\n{'=' * 60}")
    print("流水线全部完成")
    print("=" * 60)
    print(f"转换目录: {convert_dir}")
    print(f"质检目录: {qc_root}")
    print(f"合格目录: {pass_dir}")
    if not args.skip_rate:
        print("难度标注: 各 session 下的 task_difficulty_justification.json")


if __name__ == "__main__":
    main()
