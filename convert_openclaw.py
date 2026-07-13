"""
convert.py - OpenClaw JSONL 格式转换脚本

功能：将 OpenClaw 私有格式 JSONL 转换为 Anthropic 原生 Call-level 格式
- 每条输出记录 = 一次 LLM call 的 raw request / response
- 保留 thinking block 的 signature、tool_use / tool_result 原始结构
- 输出结构：一个 session 一个文件夹，文件夹下一个文件为一个 request

用法：
  python convert.py --input_dir <输入目录>
  
  如果不指定 --output_dir，将自动生成：输入目录名-待质检数据
"""

import argparse
import json
import shutil
import sys
import uuid
from pathlib import Path
from datetime import datetime, timezone

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 模型名标准化映射
MODEL_NAME_MAP = {
    "claude-opus-4-6-thinking": "claude-opus-4-6",
    "claude-opus-4-6": "claude-opus-4-6",
    "claude-opus-4-7-thinking": "claude-opus-4-7",
    "claude-opus-4-7": "claude-opus-4-7",
    "claude-opus-4-8-thinking": "claude-opus-4-8",
    "claude-opus-4-8": "claude-opus-4-8",
}

# 内置工具定义（Anthropic 格式）
BUILTIN_TOOLS = {
    "read": {"name": "read", "description": "Read the contents of a file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "offset": {"type": "number"}, "limit": {"type": "number"}}, "required": ["path"]}},
    "write": {"name": "write", "description": "Write content to a file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    "edit": {"name": "edit", "description": "Edit a file using exact text replacement.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "edits": {"type": "array"}}, "required": ["path", "edits"]}},
    "exec": {"name": "exec", "description": "Execute shell commands.", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    "web_search": {"name": "web_search", "description": "Search the web.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    "web_fetch": {"name": "web_fetch", "description": "Fetch content from URL.", "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    "process": {"name": "process", "description": "Manage running processes.", "input_schema": {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]}},
    "sessions_spawn": {"name": "sessions_spawn", "description": "Spawn sub-agent session.", "input_schema": {"type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"]}},
    "sessions_list": {"name": "sessions_list", "description": "List sessions.", "input_schema": {"type": "object", "properties": {}}},
    "sessions_history": {"name": "sessions_history", "description": "Get session history.", "input_schema": {"type": "object", "properties": {"sessionKey": {"type": "string"}}, "required": ["sessionKey"]}},
    "sessions_send": {"name": "sessions_send", "description": "Send message to session.", "input_schema": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}},
    "sessions_yield": {"name": "sessions_yield", "description": "Yield current turn.", "input_schema": {"type": "object", "properties": {}}},
    "subagents": {"name": "subagents", "description": "Manage sub-agents.", "input_schema": {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]}},
    "session_status": {"name": "session_status", "description": "Show session status.", "input_schema": {"type": "object", "properties": {}}},
    "update_plan": {"name": "update_plan", "description": "Update work plan.", "input_schema": {"type": "object", "properties": {"plan": {"type": "array"}}, "required": ["plan"]}},
    "cron": {"name": "cron", "description": "Manage cron jobs.", "input_schema": {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]}},
    "memory_search": {"name": "memory_search", "description": "Search memory.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    "memory_get": {"name": "memory_get", "description": "Get memory content.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
}


def get_system_prompt():
    """返回固定的 system prompt"""
    return "You are a personal assistant running inside OpenClaw."


def build_system_blocks(system_text):
    """将 system prompt 转换为 Anthropic content blocks"""
    return [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}]


def build_tools_list(used_tool_names):
    """根据使用的工具名称构建 tools 列表"""
    tools = []
    for name in sorted(used_tool_names):
        if name in BUILTIN_TOOLS:
            tools.append(BUILTIN_TOOLS[name])
        else:
            tools.append({"name": name, "description": f"Tool: {name}", "input_schema": {"type": "object", "properties": {}, "required": []}})
    return tools


def convert_assistant_content_to_blocks(msg):
    """将 assistant 消息内容转换为 Anthropic blocks"""
    blocks = []
    content = msg.get("content", [])
    
    if isinstance(content, str):
        if content.strip():
            blocks.append({"type": "text", "text": content})
        return blocks
    
    for block in content:
        if not isinstance(block, dict):
            if isinstance(block, str) and block.strip():
                blocks.append({"type": "text", "text": block})
            continue
        
        btype = block.get("type", "")
        
        # 处理 thinking block
        if btype == "thinking":
            thinking_text = block.get("thinking", "")
            if thinking_text and thinking_text.strip():
                blocks.append({
                    "type": "thinking",
                    "thinking": thinking_text,
                    "signature": block.get("thinkingSignature") or block.get("signature") or "Eo8E_placeholder_sig",
                })
        
        # 处理 text block
        elif btype == "text":
            text = block.get("text", "")
            if text.strip():
                blocks.append({"type": "text", "text": text})
        
        # 处理 toolCall
        elif btype == "toolCall":
            args = block.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except:
                    args = {"raw": args}
            blocks.append({
                "type": "tool_use",
                "id": block.get("id", f"toolu_{uuid.uuid4().hex[:12]}"),
                "name": block.get("name", "unknown"),
                "input": args,
            })
        
        # 处理已有的 tool_use
        elif btype == "tool_use":
            blocks.append(block)
    
    # 处理 legacy tool_calls 数组
    tool_calls = msg.get("tool_calls") or []
    for tc in tool_calls:
        func = tc.get("function", {})
        args = func.get("arguments", "{}")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except:
                args = {"raw": args}
        blocks.append({
            "type": "tool_use",
            "id": tc.get("id", f"toolu_{uuid.uuid4().hex[:12]}"),
            "name": func.get("name", "unknown"),
            "input": args,
        })
    
    return blocks


def convert_tool_message_to_result(msg):
    """将工具响应消息转换为 tool_result block"""
    content = msg.get("content", "")
    
    # 从 content blocks 中提取文本
    if isinstance(content, list):
        parts = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                parts.append(b.get("text", ""))
            elif isinstance(b, str):
                parts.append(b)
        content = "\n".join(parts)
    
    # 检测是否是错误
    is_error = False
    if isinstance(content, str):
        if '"status": "error"' in content or '"status":"error"' in content:
            is_error = True
    
    tool_use_id = msg.get("tool_call_id") or msg.get("toolCallId") or "unknown"
    
    block = {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content if content else "",
    }
    
    if is_error:
        block["is_error"] = True
    
    return block


def convert_user_content_to_blocks(msg):
    """将 user 消息内容转换为 Anthropic blocks"""
    content = msg.get("content", "")
    
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content.strip() else [{"type": "text", "text": " "}]
    
    if isinstance(content, list):
        blocks = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") in ("text", "tool_result", "image"):
                    blocks.append(item)
                else:
                    blocks.append(item)
            elif isinstance(item, str):
                blocks.append({"type": "text", "text": item})
        return blocks if blocks else [{"type": "text", "text": " "}]
    
    return [{"type": "text", "text": str(content)}]


def process_openclaw_jsonl(jsonl_path, system_prompt):
    """
    处理一个 OpenClaw JSONL 文件，生成 Anthropic call-level 记录
    每个 assistant turn = 一次 LLM call
    """
    # 解析 JSONL: 支持单行和多行格式
    events = []
    with open(jsonl_path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.split("\n")
    first_line = next((l.strip() for l in lines if l.strip()), "")
    
    if first_line.startswith("{") and first_line.endswith("}"):
        # 标准 JSONL
        for line in lines:
            line = line.strip()
            if not line:
                continue
            events.append(json.loads(line))
    else:
        # 多行格式化 JSON
        decoder = json.JSONDecoder()
        pos = 0
        content = content.strip()
        while pos < len(content):
            while pos < len(content) and content[pos] in " \t\n\r":
                pos += 1
            if pos >= len(content):
                break
            obj, end_pos = decoder.raw_decode(content, pos)
            events.append(obj)
            pos = end_pos

    # 提取元数据
    session_id = Path(jsonl_path).stem
    raw_model = "claude-opus-4-6"
    thinking_effort = "high"
    temperature = 1.0
    max_tokens = 16384

    messages = []
    message_timestamps = []
    
    for ev in events:
        ev_type = ev.get("type", "")
        
        if ev_type == "session":
            session_id = ev.get("id", session_id)
        elif ev_type == "model_change":
            raw_model = ev.get("modelId", raw_model)
        elif ev_type == "thinking_level_change":
            thinking_effort = ev.get("thinkingLevel", thinking_effort)
        elif ev_type == "message":
            msg = ev.get("message", {})
            if msg.get("role") in ("user", "assistant", "toolResult"):
                messages.append(msg)
                message_timestamps.append(msg.get("timestamp") or ev.get("timestamp"))

    # 标准化模型名称
    model_name = MODEL_NAME_MAP.get(raw_model, raw_model)
    
    # 处理 thinking_effort（保留原始值，不兜底为 high）
    if isinstance(thinking_effort, dict):
        thinking_effort = thinking_effort.get("type")

    # 收集所有使用的工具
    all_tool_names = set()
    for msg in messages:
        if msg.get("role") == "assistant":
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "toolCall":
                    name = block.get("name")
                    if name:
                        all_tool_names.add(name)

    tools_list = build_tools_list(all_tool_names)
    system_blocks = build_system_blocks(system_prompt)

    # 跳过第一条 system 消息
    start_idx = 0
    if messages and messages[0].get("role") == "system":
        start_idx = 1

    # 重建 call-level 记录
    calls = []
    anthropic_messages = []
    
    for i in range(start_idx, len(messages)):
        msg = messages[i]
        role = msg.get("role", "")

        if role == "user":
            anthropic_messages.append({
                "role": "user",
                "content": convert_user_content_to_blocks(msg),
            })
        
        elif role in ("tool", "toolResult"):
            tool_block = convert_tool_message_to_result(msg)
            if anthropic_messages and anthropic_messages[-1]["role"] == "user":
                anthropic_messages[-1]["content"].append(tool_block)
            else:
                anthropic_messages.append({
                    "role": "user",
                    "content": [tool_block],
                })
        
        elif role == "assistant":
            # 创建一条 call 记录
            response_blocks = convert_assistant_content_to_blocks(msg)

            # 确保以 user 开头
            if not anthropic_messages or anthropic_messages[0].get("role") != "user":
                anthropic_messages.insert(0, {
                    "role": "user",
                    "content": [{"type": "text", "text": "[session start]"}],
                })

            # 使用源数据的元数据
            raw_stop = msg.get("stopReason", "")
            stop_reason_map = {
                "stop": "end_turn",
                "end_turn": "end_turn",
                "tool_use": "tool_use",
                "max_tokens": "max_tokens",
                "stop_sequence": "stop_sequence",
            }
            if raw_stop in stop_reason_map:
                stop_reason = stop_reason_map[raw_stop]
            else:
                has_tool_use = any(b.get("type") == "tool_use" for b in response_blocks)
                stop_reason = "tool_use" if has_tool_use else "end_turn"

            # timestamp
            src_ts = message_timestamps[i] if i < len(message_timestamps) else None
            if isinstance(src_ts, (int, float)):
                real_timestamp = datetime.fromtimestamp(src_ts / 1000, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            elif isinstance(src_ts, str):
                real_timestamp = src_ts if src_ts.endswith("Z") else src_ts + "Z"
            else:
                real_timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

            # response id
            real_resp_id = msg.get("responseId") or f"msg_{uuid.uuid4().hex[:16]}"
            
            # request_id
            request_id = msg.get("requestId") or msg.get("x-request-id") or msg.get("x_request_id") or str(uuid.uuid4())

            # usage
            src_usage = msg.get("usage", {})
            if src_usage:
                usage_block = {
                    "input_tokens": src_usage.get("input", 0),
                    "output_tokens": src_usage.get("output", 0),
                    "cache_read_input_tokens": src_usage.get("cacheRead", 0),
                    "cache_creation_input_tokens": src_usage.get("cacheWrite", 0),
                }
            else:
                usage_block = {
                    "input_tokens": len(json.dumps(anthropic_messages, ensure_ascii=False)) // 4,
                    "output_tokens": len(json.dumps(response_blocks, ensure_ascii=False)) // 4,
                    "cache_read_input_tokens": 0,
                }

            # 构建 call 记录
            call_record = {
                "session_id": session_id,
                "request_id": request_id,
                "timestamp": real_timestamp,
                "thinking_effort": thinking_effort,
                "request": {
                    "model": model_name,
                    "max_tokens": max_tokens,
                    "thinking": {"type": "adaptive"},
                    "temperature": temperature,
                    "system": system_blocks,
                    "tools": tools_list,
                    "messages": [m for m in anthropic_messages],
                },
                "response": {
                    "response_data": {
                        "id": real_resp_id,
                        "type": "message",
                        "role": "assistant",
                        "model": model_name,
                        "content": response_blocks,
                        "stop_reason": stop_reason,
                        "stop_sequence": None,
                        "usage": usage_block,
                    }
                },
            }
            calls.append(call_record)

            # 将 assistant 消息添加到上下文
            anthropic_messages.append({
                "role": "assistant",
                "content": response_blocks,
            })

    return calls, model_name, all_tool_names


def convert_file(jsonl_path, target_dir, system_prompt):
    """转换一个 JSONL 文件"""
    print(f"\n{'='*60}")
    print(f"[处理] {jsonl_path}")

    try:
        calls, model_name, tool_names = process_openclaw_jsonl(jsonl_path, system_prompt)
    except Exception as e:
        print(f"  [错误] 解析失败: {e}")
        import traceback
        traceback.print_exc()
        return None

    if not calls:
        print("  [跳过] 无有效 call")
        return None

    session_id = calls[0]["session_id"]
    print(f"  [Session] {session_id}")
    print(f"  [Model] {model_name}")
    print(f"  [Calls] {len(calls)}")
    print(f"  [Tools] {', '.join(sorted(tool_names)) if tool_names else 'None'}")

    # 输出: 每个 session 一个文件夹，每个 call 一个文件
    session_dir = Path(target_dir) / session_id
    if session_dir.exists():
        shutil.rmtree(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True)

    for idx, call in enumerate(calls):
        out_file = session_dir / f"{idx:04d}_{call['request_id']}.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(call, f, ensure_ascii=False, indent=2)

    print(f"  [输出] {session_dir}/ ({len(calls)} files)")

    return {
        "file": Path(jsonl_path).name,
        "session_id": session_id,
        "model": model_name,
        "calls": len(calls),
    }


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="OpenClaw JSONL -> Anthropic Call-level 格式转换",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python convert.py --input_dir D:/sessions/test/opus/heyamei
  python convert.py --input_dir D:/sessions/test/opus/heyamei --output_dir D:/output
        """
    )
    parser.add_argument("--input_dir", required=True, help="输入目录（包含 .jsonl 文件）")
    parser.add_argument("--output_dir", help="输出目录（可选，默认自动生成）")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    
    # 自动生成输出目录名
    if args.output_dir:
        target_dir = Path(args.output_dir)
    else:
        input_dirname = input_dir.name
        target_dir = input_dir.parent / f"{input_dirname}-待质检数据"

    if not input_dir.exists():
        print(f"[错误] 输入目录不存在: {input_dir}")
        sys.exit(1)

    system_prompt = get_system_prompt()

    jsonl_files = sorted(f for f in input_dir.glob("*.jsonl") if f.parent == input_dir)
    if not jsonl_files:
        print(f"[错误] 未找到 .jsonl 文件: {input_dir}")
        sys.exit(1)

    print(f"[输入目录] {input_dir}")
    print(f"[输出目录] {target_dir}")
    print(f"[文件数量] {len(jsonl_files)}")

    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for jsonl_file in jsonl_files:
        result = convert_file(str(jsonl_file), str(target_dir), system_prompt)
        if result:
            results.append(result)

    # 打印汇总
    print(f"\n{'='*60}")
    print(f"[汇总] 成功处理 {len(results)}/{len(jsonl_files)} 个文件")
    print("="*60)

    for r in results:
        print(f"  ✓ {r['file']} -> {r['calls']} calls | model: {r['model']}")

    print(f"\n[完成] 输出目录: {target_dir}")


if __name__ == "__main__":
    main()
