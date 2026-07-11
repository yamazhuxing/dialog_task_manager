#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用大模型生成自然口语化的五轮关联提问，格式/场景配额与 generate_questions.py 一致。

特性：
- 保留 13 场景配额与 topic 广度
- 每条独立调用 LLM，表达更自然、少模板感
- 断点续跑（checkpoint），可随时中断后继续
- 支持 --limit / --scene 试跑

用法：
  uv run python generate_questions_llm.py --limit 5
  uv run python generate_questions_llm.py
  uv run python generate_questions_llm.py --resume
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from pathlib import Path

from openai import OpenAI

from generate_questions import (
    ROUNDS,
    SCENE_BANK,
    SCENE_META,
    TOTAL,
    allocate_topics,
)

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
OUT_PATH = ROOT / "questions_1200.json"
CKPT_PATH = ROOT / "questions_1200.checkpoint.jsonl"
SEED = 20260710

DEFAULT_API_KEY = "sk-69d327c6f2e7492d892cfb29d94757c1"
DEFAULT_API_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-v4-flash"

SYSTEM_PROMPT = """你是蒸馏样本出题专家。为「用户 ↔ AI 编程/运维助手」设计多轮用户提问。
要求：
1. 只输出用户侧提问，共 5 轮，后轮必须承接前轮（可适度发散，但逻辑相关）。
2. 口语自然、像真人工程师/运营在对话，避免「请先…请再…请输出…」这种排比公文腔。
3. 每轮目标不同：定目标/澄清 → 动手落地 → 排障或验证 → 边界/优化 → 收束交付。
4. 问题要具体可执行，能激活推理、代码或分析；但不要故意刁难成超长开放题（控制 thinking 成本）。
5. 不要扮演助手回答；不要输出 markdown 代码块包裹整个 JSON。
6. 严格输出一个 JSON 对象，字段：
{"topic":"短标题","constraint":"关键约束","turns":[{"round":1,"role":"user","content":"..."}, ... 共5轮]}
"""

USER_PROMPT = """场景标签：{scene}（{scene_label}）
参考主题（可改写措辞，勿照抄模板句式）：{topic}
参考约束（可改写）：{constraint}
风格提示：{style}

请生成 1 条五轮用户提问。JSON only。"""

STYLES = [
    "偏务实，带一点时间压力（比如这周要上线）",
    "先抛现状和痛点，再提诉求，语气随意",
    "像在 pair programming，短句多、可追问",
    "先给背景上下文（环境/数据/团队），再提任务",
    "略带犹豫，希望助手帮做技术取舍",
    "已经试过一版失败了，带着失败现象来问",
    "偏清单思维，但句子不要千篇一律的「请给出」",
    "口语化，偶尔用括号补充细节",
]


def build_plan(rng: random.Random) -> list[dict]:
    """固定配额与主题分配，仅 content 交给 LLM。"""
    plan: list[dict] = []
    qid = 1
    for scene, label, count in SCENE_META:
        pairs = allocate_topics(rng, scene, count)
        for topic, constraint in pairs:
            plan.append(
                {
                    "id": qid,
                    "scene": scene,
                    "scene_label": label,
                    "seed_topic": topic,
                    "seed_constraint": constraint,
                }
            )
            qid += 1
    return plan


def load_checkpoint(path: Path) -> dict[int, dict]:
    done: dict[int, dict] = {}
    if not path.exists():
        return done
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                done[int(obj["id"])] = obj
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
    return done


def append_checkpoint(path: Path, record: dict) -> None:
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def extract_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("响应中未找到 JSON 对象")
    return json.loads(text[start : end + 1])


def normalize_turns(raw_turns: list) -> list[dict]:
    if not isinstance(raw_turns, list) or len(raw_turns) != ROUNDS:
        raise ValueError(f"turns 数量应为 {ROUNDS}，实际 {type(raw_turns)}/{getattr(raw_turns, '__len__', lambda: '?')()}")
    out = []
    for i, t in enumerate(raw_turns, start=1):
        if isinstance(t, str):
            content = t.strip()
        elif isinstance(t, dict):
            content = str(t.get("content", "")).strip()
        else:
            raise ValueError(f"非法 turn: {t!r}")
        if not content:
            raise ValueError(f"第 {i} 轮 content 为空")
        out.append({"round": i, "role": "user", "content": content})
    return out


def generate_one(
    client: OpenAI,
    model: str,
    item: dict,
    rng: random.Random,
    temperature: float,
    max_retries: int = 3,
) -> dict:
    style = rng.choice(STYLES)
    prompt = USER_PROMPT.format(
        scene=item["scene"],
        scene_label=item["scene_label"],
        topic=item["seed_topic"],
        constraint=item["seed_constraint"],
        style=style,
    )
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or ""
            data = extract_json(raw)
            turns = normalize_turns(data.get("turns", []))
            topic = str(data.get("topic") or item["seed_topic"]).strip()
            constraint = str(data.get("constraint") or item["seed_constraint"]).strip()
            return {
                "id": item["id"],
                "scene": item["scene"],
                "scene_label": item["scene_label"],
                "topic": topic,
                "constraint": constraint,
                "turns": turns,
                "design_notes": {
                    "rounds": ROUNDS,
                    "thinking_policy": "prefer_concrete_deliverables",
                    "depth_pattern": "scope->implement->debug->edge->deliver",
                    "generator": "llm",
                    "model": model,
                    "style": style,
                },
            }
        except Exception as e:
            last_err = e
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"id={item['id']} 生成失败: {last_err}")


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM 生成自然五轮提问")
    parser.add_argument("--api_key", default=DEFAULT_API_KEY)
    parser.add_argument("--api_base", default=DEFAULT_API_BASE)
    parser.add_argument("--model", default=DEFAULT_MODEL, help="建议 flash 控成本，可用 deepseek-v4-pro")
    parser.add_argument("--temperature", type=float, default=0.9)
    parser.add_argument("--limit", type=int, default=0, help="只生成前 N 条（试跑）")
    parser.add_argument("--scene", default="", help="只生成指定 scene")
    parser.add_argument("--resume", action="store_true", help="从 checkpoint 续跑")
    parser.add_argument("--fresh", action="store_true", help="忽略 checkpoint 重新开始")
    parser.add_argument("--sleep", type=float, default=0.2, help="每次调用间隔秒")
    parser.add_argument("--out", default=str(OUT_PATH))
    parser.add_argument("--checkpoint", default=str(CKPT_PATH))
    args = parser.parse_args()

    rng = random.Random(SEED)
    plan = build_plan(rng)
    if args.scene:
        plan = [p for p in plan if p["scene"] == args.scene]
    if args.limit and args.limit > 0:
        plan = plan[: args.limit]

    ckpt_path = Path(args.checkpoint)
    out_path = Path(args.out)

    if args.fresh and ckpt_path.exists():
        ckpt_path.unlink()
        print(f"[清理] 已删除 checkpoint: {ckpt_path}")

    done = load_checkpoint(ckpt_path) if (args.resume or ckpt_path.exists()) else {}
    if done and not args.resume and not args.fresh:
        print(f"[提示] 发现 checkpoint {len(done)} 条，默认续跑。若要重来请加 --fresh")

    client = OpenAI(api_key=args.api_key, base_url=args.api_base)
    pending = [p for p in plan if p["id"] not in done]
    print("=" * 60)
    print("LLM 提问生成")
    print("=" * 60)
    print(f"计划: {len(plan)} | 已完成: {len(done)} | 待生成: {len(pending)}")
    print(f"模型: {args.model} | 输出: {out_path}")

    ok = 0
    fail = 0
    for i, item in enumerate(pending, start=1):
        try:
            rec = generate_one(client, args.model, item, rng, args.temperature)
            append_checkpoint(ckpt_path, rec)
            done[rec["id"]] = rec
            ok += 1
            preview = rec["turns"][0]["content"][:60].replace("\n", " ")
            print(f"[{i}/{len(pending)}] id={rec['id']} {rec['scene']} ✓ {preview}...")
        except Exception as e:
            fail += 1
            print(f"[{i}/{len(pending)}] id={item['id']} ✗ {e}")
        if args.sleep > 0:
            time.sleep(args.sleep)

    # 按 id 排序写出完整 JSON（仅包含本次 plan 范围内）
    records = [done[p["id"]] for p in plan if p["id"] in done]
    missing = [p["id"] for p in plan if p["id"] not in done]
    if missing:
        print(f"\n[未完成] {len(missing)} 条，例如 id={missing[:10]}... 可用 --resume 继续")
        # 仍写出已完成部分，便于预览
        out_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[部分写入] {out_path} ({len(records)} 条)")
        sys.exit(1)

    if len(records) == TOTAL and not args.limit and not args.scene:
        counts = Counter(r["scene"] for r in records)
        mn, mx = min(counts.values()), max(counts.values())
        assert len(records) == TOTAL
        assert mn >= 1 and mx / mn < 4, (mn, mx, dict(counts))
        for r in records:
            assert len(r["turns"]) == ROUNDS
            assert [t["round"] for t in r["turns"]] == list(range(1, ROUNDS + 1))
        print(f"[校验通过] 总数={len(records)} 分布={dict(counts)} 极差比={mx/mn:.3f}")
    else:
        counts = Counter(r["scene"] for r in records)
        print(f"[试跑完成] 总数={len(records)} 分布={dict(counts)}")

    out_path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[完成] 成功本轮 {ok}，失败 {fail}")
    print(f"[已写入] {out_path}")


if __name__ == "__main__":
    main()
