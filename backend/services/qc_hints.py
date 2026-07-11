"""将质检报错映射为可读的成因与补救建议（仅展示层，不修改验收标准）。"""

from __future__ import annotations

import re
from typing import TypedDict


class QCHint(TypedDict):
    error: str
    essence: str
    remedy: str


_RULES: list[tuple[re.Pattern[str], str, str]] = [
    (
        re.compile(r"thinking density", re.I),
        "思考块密度不足：多轮工具排障但 thinking 占比偏低",
        "再加 ≥2 轮「会带 thinking、少空转工具」的追问，避免空转 exec/read",
    ),
    (
        re.compile(r"scaffold bug|真实 user 消息后的第一轮", re.I),
        "scaffold 结构问题：全程纯问答、thinking 都跟在真实 user 后",
        "追问逼出 write/exec，让至少一次 thinking 出现在 tool_result 之后",
    ),
    (
        re.compile(r"上传失败，请确认当前任务"),
        "提交未通过校验",
        "请确认任务与文件后重新上传",
    ),
    (
        re.compile(r"上传失败，请更换对话文件"),
        "提交未通过校验",
        "请重新制作对话后上传",
    ),
    (
        re.compile(r"assistant turns", re.I),
        "对话轮数不足",
        "继续多轮追问，确保至少 5 轮有效 assistant 回复",
    ),
    (
        re.compile(r"tool_call_error|tool error ratio|tool_err", re.I),
        "工具调用失败比例过高",
        "减少无效工具调用，修正命令/路径后再追问，避免连续 error tool_result",
    ),
    (
        re.compile(r"cron/heartbeat|no_reply", re.I),
        "自动化/心跳类 user 消息占比过高",
        "减少 heartbeat/cron 触发，使用真实业务追问推进对话",
    ),
    (
        re.compile(r"最后一个 call.*tool_use", re.I),
        "末轮以 tool_use 结束，缺少完整 text 总结",
        "最后一轮应让模型输出 end_turn 的完整 text 答复，不要停在工具调用",
    ),
    (
        re.compile(r"最后一个 call.*end_turn|非空的 text block", re.I),
        "末轮回复不完整",
        "确保最后一轮 assistant 有非空 text 总结",
    ),
    (
        re.compile(r"thinking block 为空|没有非空的 thinking", re.I),
        "缺少有效 thinking 块",
        "使用 high/xhigh/max thinking，并确保模型输出带 signature 的 thinking",
    ),
    (
        re.compile(r"模型.*不在允许列表|模型名称不唯一", re.I),
        "模型不符合要求",
        "请使用 Claude Opus 4.6 或 4.8，且全程保持一致",
    ),
]


def build_qc_hints(errors: list[str]) -> list[QCHint]:
    hints: list[QCHint] = []
    for error in errors:
        essence = "请对照甲方质检项检查轨迹结构"
        remedy = "根据报错调整对话后重新导出上传"
        for pattern, mapped_essence, mapped_remedy in _RULES:
            if pattern.search(error):
                essence = mapped_essence
                remedy = mapped_remedy
                break
        hints.append({"error": error, "essence": essence, "remedy": remedy})
    return hints
