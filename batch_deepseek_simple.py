#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DeepSeek-v4-pro 难度评估工具
功能：直接输入session文件夹，每个session目录下生成模型原始输出标注文件，无Excel汇总
用法：
python batch_deepseek_simple.py --input_dir <session文件夹路径> --api_key <API Key> [--api_base <API地址>]
"""

import json
from openai import OpenAI
import sys
import argparse
from pathlib import Path
from datetime import datetime

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


DEFAULT_INPUT_DIR = r"sample\openclaw-待质检数据-质检结果\openclaw-待质检数据-pass"
DEFAULT_API_KEY = "sk-69d327c6f2e7492d892cfb29d94757c1"
DEFAULT_API_BASE = "https://api.deepseek.com"

# 难度评估prompt模板（用户提供最新版）
PROMPT_TEMPLATE = """
You are an **Expert Software Engineering Analyst**. 
Your goal is to analyze a given software engineering task trajectory (a conversation between a user and an AI assistant, including code changes, reasoning, and tool usage) and accurately classify its **Task Difficulty Level**.

### Evaluation Criteria & Process
Do not judge difficulty purely by the length of the conversation or the volume of boilerplate code generated. 
Before making a decision, mentally analyze the following factors to form your justification:
1. **Reasoning Steps & Tool Usage**: Did the assistant solve it in one shot, or did it require multi-step deduction, multi-turn tool execution (e.g., debugging loops), and handling ambiguity?
2. **Context & Scope**: Is it a localized change, or does it involve cross-system integration and complex dependencies?
3. **Domain Knowledge**: Does it rely on basic programming knowledge, or does it require specialized, system-level, or cutting-edge domain expertise?

---

### Task Difficulty Scale
Choose exactly one of the following levels:

**1. `low` (Trivial / Basic)**
* **Criteria**: Simple tasks requiring minimal reasoning or coding.
* **Examples**: Daily Q&A, formatting adjustments, syntax corrections, basic calculations, text modifications, single-step simple tool usage.

**2. `medium` (Moderate / Standard Development)**
* **Criteria**: Tasks with a clear scope and moderate complexity. 
* **Examples**: Standard feature implementation (e.g., typical CRUD), writing unit tests for explicit functions, straightforward bug fixes within a single module, localized data processing.

**3. `high` (Complex / Multi-step Reasoning)*** **Criteria**: Requires multi-step reasoning, multi-turn tool usage, or deep thinking. 
* **Examples**: Complex debugging requiring tracing state across files, cross-system integration, refactoring medium-sized codebases, handling asynchronous logic or standard architectural design.

**4. `xhigh` (Advanced / System-Level / Long Toolchain)**
* **Criteria**: Requires extensive domain knowledge, long-range toolchains, or deep system-level troubleshooting.
* **Examples**: Complex algorithm implementation, performance optimization/profiling, resolving memory leaks, system-level networking issues, handling distributed system anomalies.

**5. `expert` (Specialized / Cutting-Edge)**
* **Criteria**: Requires a senior domain expert to resolve. Highly specialized professional judgment.
* **Examples**: Designing novel algorithms, resolving undocumented zero-day vulnerabilities, writing custom compilers, complex reverse engineering, cutting-edge machine learning architectures.

---

### Input TrajectoryBelow is the task trajectory you need to evaluate:

<trajectory>
{trajectory_content}
</trajectory>

---

### Output Format
Provide your response strictly in the following JSON format. Do not include markdown code blocks (e.g., ```json) in the output, just the raw JSON:

{{ 
    "justification": "Briefly analyze the tool usage, reasoning steps, and technical depth, then explain exactly why it fits the chosen level and not the adjacent levels.", 
    "task_difficulty": "<low|medium|high|xhigh|expert>" 
}}
"""

def find_last_call_file(session_dir: Path):
    DEFAULT_TS = float("-inf")

    last_file = None
    max_ts = DEFAULT_TS

    for f in session_dir.glob("*.json"):
        try:
            with f.open(encoding="utf-8") as fp:
                ts_str = json.load(fp).get("timestamp")
                if not isinstance(ts_str, str):
                    continue

                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                ts = dt.timestamp()

                if ts > max_ts:
                    max_ts = ts
                    last_file = f
        except (OSError, ValueError, KeyError, TypeError):
            continue

    return last_file

def main():
    parser = argparse.ArgumentParser(description="DeepSeek-v4-pro 难度评估工具")
    parser.add_argument("--input_dir", default=DEFAULT_INPUT_DIR, help="输入session文件夹路径")
    parser.add_argument("--api_key", default=DEFAULT_API_KEY, help="DeepSeek API Key")
    parser.add_argument("--api_base", default=DEFAULT_API_BASE, help="DeepSeek API 地址，默认：https://api.deepseek.com")
    args = parser.parse_args()
    
    input_dir = Path(args.input_dir)
    if not input_dir.exists():
        print(f"错误：目录不存在 {input_dir}")
        sys.exit(1)

    print("="*60)
    print("DeepSeek-V4-Pro 任务难度评估工具")
    print("="*60)
    print(f"输入目录：{input_dir}")
    print(f"每个session目录下生成：task_difficulty_justification.jsonl（含模型完整输出）")
    print(f"API地址：{args.api_base}")

    # 遍历session直接处理
    session_dirs = [d for d in input_dir.iterdir() if d.is_dir()]
    print(f"\n共找到 {len(session_dirs)} 个session")
    client = OpenAI(api_key=args.api_key, base_url=args.api_base)

    success_count = 0
    for idx, session_dir in enumerate(session_dirs):
        session_id = session_dir.name
        print(f"[{idx+1}/{len(session_dirs)}] 处理 {session_id}...")

        last_call = find_last_call_file(session_dir)
        if not last_call:
            diff = "无call文件"
            reply = "无可用call文件"
            status = "failed"
            print(f"⚠️  跳过：无call文件")
        else:
            # 读取内容拼接prompt（内存中处理，不保存本地）
            with open(last_call, "r", encoding="utf-8") as f:
                data = json.load(f)
                messages= data.get("request", {}).get("messages", [])
                resp_content = data.get("response", {}).get("response_data", {}).get("content", [])
                trajectory = '\n'.join(json.dumps(d, ensure_ascii=False) for d in messages + resp_content)
            prompt = PROMPT_TEMPLATE.format(trajectory_content=trajectory)
            
            try:
                resp = client.chat.completions.create(
                    model="deepseek-v4-pro",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7
                )
                reply = resp.choices[0].message.content.strip()
                try:
                    j = json.loads(reply)
                    justification = j.get("justification", "解析失败")
                    diff = j.get("task_difficulty", "解析失败")
                    status = "success" if diff in ["low", "medium", "high", "xhigh", "expert"] else "failed"
                except:
                    justification = "格式错误"
                    diff = "格式错误"
                    status = "failed"
                if status == "success":
                    success_count += 1
                print(f"✅ 完成，难度：{diff}")
            except Exception as e:
                reply = str(e)
                justification = "调用失败"
                diff = "调用失败"
                status = "failed"
                print(f"❌ 失败：{str(e)}")
        
        # 保存模型原始输出到session目录下（仅保存模型输出内容，无其他字段）
        label_entry = {
            "session_id": session_id,
            "evaluation_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "api_base": args.api_base,
            "justification": justification,
            "task_difficulty": diff
        }
        justification_file = session_dir / "task_difficulty_justification.json"
        with open(justification_file, "w", encoding="utf-8") as f:
            json.dump(label_entry, f, ensure_ascii=False, indent=4)

    print(f"\n✅ 全部完成！")
    print(f"成功：{success_count} / {len(session_dirs)}")
    print(f"标注文件已保存到对应session目录和")

if __name__ == "__main__":
    main()
