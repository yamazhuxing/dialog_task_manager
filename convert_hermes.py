"""
convert_hermes.py - Hermes JSON 格式转换脚本

功能：将 Hermes 私有格式 JSON 转换为 Anthropic 原生 Call-level 格式
- 每条输出记录 = 一次 LLM call 的 raw request / response
- 保留 thinking block 的 signature、tool_use / tool_result 原始结构
- 输出结构：一个 session 一个文件夹，文件夹下一个文件为一个 request

用法：
  python convert_hermes.py --input_dir <输入目录>
  
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
    "claude-opus-4-6": "claude-opus-4-6",
    "claude-opus-4-7": "claude-opus-4-7",
    "claude-opus-4-8": "claude-opus-4-8",
}

# 内置工具定义（Anthropic 格式）
BUILTIN_TOOLS = {
    "read": {"name": "read", "description": "Read the contents of a file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "offset": {"type": "number"}, "limit": {"type": "number"}}, "required": ["path"]}},
    "write": {"name": "write", "description": "Write content to a file.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    "edit": {"name": "edit", "description": "Edit a file using exact text replacement.", "input_schema": {"type": "object", "properties": {"path": {"type": "string"}, "edits": {"type": "array"}}, "required": ["path", "edits"]}},
    "exec": {"name": "exec", "description": "Execute shell commands.", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    "terminal": {"name": "terminal", "description": "Execute terminal commands.", "input_schema": {"type": "object", "properties": {"command": {"type": "string"}}, "required": ["command"]}},
    "web_search": {"name": "web_search", "description": "Search the web.", "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
    "web_fetch": {"name": "web_fetch", "description": "Fetch content from URL.", "input_schema": {"type": "object", "properties": {"url": {"type": "string"}}, "required": ["url"]}},
    "process": {"name": "process", "description": "Manage running processes.", "input_schema": {"type": "object", "properties": {"action": {"type": "string"}}, "required": ["action"]}},
}


def normalize_timestamp(raw_ts) -> str:
    """将 Hermes 时间戳统一为 ISO-8601 字符串（与 OpenClaw 转换结果一致）。"""
    if raw_ts is None:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if isinstance(raw_ts, (int, float)):
        seconds = raw_ts / 1000 if raw_ts > 1e12 else raw_ts
        return (
            datetime.fromtimestamp(seconds, tz=timezone.utc)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
    if isinstance(raw_ts, str):
        text = raw_ts.strip()
        if not text:
            return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return text if text.endswith("Z") else text + "Z"
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def extract_system_prompt(hermes_data):
    """从 Hermes 数据中提取 system prompt"""
    return hermes_data.get("system_prompt", "You are a helpful AI assistant.")


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


def parse_reasoning_details(reasoning_details_str):
    """解析 reasoning_details JSON 字符串，提取 thinking block"""
    if not reasoning_details_str:
        return None
    
    try:
        details = json.loads(reasoning_details_str)
        if isinstance(details, list) and len(details) > 0:
            first_item = details[0]
            if isinstance(first_item, dict) and first_item.get("type") == "thinking":
                return {
                    "thinking": first_item.get("thinking", ""),
                    "signature": first_item.get("signature", "")
                }
    except:
        pass
    
    return None


def convert_hermes_message_to_anthropic(msg):
    """将 Hermes 消息转换为 Anthropic 格式的 content blocks"""
    role = msg.get("role")
    
    if role == "user":
        # User 消息：简单的 text block
        content = msg.get("content", "")
        return [{"type": "text", "text": content if content else " "}]
    
    elif role == "assistant":
        blocks = []
        
        # 处理 thinking block（从 reasoning_details 提取）
        reasoning_details = msg.get("reasoning_details")
        if reasoning_details:
            thinking_data = parse_reasoning_details(reasoning_details)
            if thinking_data and thinking_data.get("thinking"):
                blocks.append({
                    "type": "thinking",
                    "thinking": thinking_data["thinking"],
                    "signature": thinking_data.get("signature", "Eo8E_placeholder_sig")
                })
        
        # 处理 text content
        content = msg.get("content", "")
        if content and content.strip():
            blocks.append({"type": "text", "text": content})
        
        # 处理 tool_calls
        tool_calls = msg.get("tool_calls") or []
        for tc in tool_calls:
            func = tc.get("function", {})
            args_str = func.get("arguments", "{}")
            try:
                args = json.loads(args_str) if isinstance(args_str, str) else args_str
            except:
                args = {"raw": args_str}
            
            blocks.append({
                "type": "tool_use",
                "id": tc.get("id") or tc.get("call_id") or f"toolu_{uuid.uuid4().hex[:12]}",
                "name": func.get("name", "unknown"),
                "input": args,
            })
        
        return blocks
    
    elif role == "tool":
        # Tool result 消息不在这里处理，由调用方处理
        return None
    
    return [{"type": "text", "text": str(msg.get("content", ""))}]


def convert_tool_result_to_block(msg):
    """将 Hermes tool result 消息转换为 tool_result block"""
    content = msg.get("content", "")
    
    # 检测是否是错误
    is_error = False
    if isinstance(content, str):
        # Hermes 的 tool result 可能包含 <untrusted_tool_result> 包装
        if '"success": false' in content or '"status": "error"' in content:
            is_error = True
    
    tool_call_id = msg.get("tool_call_id", "unknown")
    
    block = {
        "type": "tool_result",
        "tool_use_id": tool_call_id,
        "content": content if content else "",
    }
    
    if is_error:
        block["is_error"] = True
    
    return block


def process_hermes_json(json_path, system_prompt):
    """
    处理一个 Hermes JSON 文件，生成 Anthropic call-level 记录
    每个 assistant turn = 一次 LLM call
    """
    with open(json_path, "r", encoding="utf-8") as f:
        hermes_data = json.load(f)
    
    # 提取元数据
    session_id = hermes_data.get("id", Path(json_path).stem)
    raw_model = hermes_data.get("model", "claude-opus-4-6")
    model_name = MODEL_NAME_MAP.get(raw_model, raw_model)
    
    # 解析 model_config
    model_config_str = hermes_data.get("model_config", "{}")
    try:
        model_config = json.loads(model_config_str) if isinstance(model_config_str, str) else model_config_str
    except:
        model_config = {}
    
    reasoning_config = model_config.get("reasoning_config", {})
    if reasoning_config.get("enabled"):
        thinking_type = reasoning_config.get("effort", "high")
    else:
        thinking_type = "medium"
    if isinstance(thinking_type, dict):
        thinking_type = thinking_type.get("type", "high" if reasoning_config.get("enabled") else "medium")
    thinking_effort = thinking_type
    max_tokens = model_config.get("max_tokens") or 16384
    temperature = 1.0
    
    # 提取消息列表
    messages = hermes_data.get("messages", [])
    
    # 收集所有使用的工具
    all_tool_names = set()
    for msg in messages:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                func = tc.get("function", {})
                name = func.get("name")
                if name:
                    all_tool_names.add(name)
    
    tools_list = build_tools_list(all_tool_names)
    system_blocks = build_system_blocks(system_prompt)
    
    # 重建 call-level 记录
    calls = []
    anthropic_messages = []
    
    i = 0
    while i < len(messages):
        msg = messages[i]
        role = msg.get("role")
        
        if role == "user":
            # User 消息：添加到上下文
            user_blocks = convert_hermes_message_to_anthropic(msg)
            anthropic_messages.append({
                "role": "user",
                "content": user_blocks,
            })
            i += 1
        
        elif role == "assistant":
            # Assistant 消息：构建一个 call 记录
            response_blocks = convert_hermes_message_to_anthropic(msg)
            
            # 检查后续是否有 tool result 消息
            j = i + 1
            tool_results = []
            while j < len(messages) and messages[j].get("role") == "tool":
                tool_results.append(messages[j])
                j += 1
            
            # 判断 stop_reason
            finish_reason = msg.get("finish_reason")
            if finish_reason == "tool_calls":
                stop_reason = "tool_use"
            elif finish_reason == "stop":
                stop_reason = "end_turn"
            elif finish_reason == "max_tokens":
                stop_reason = "max_tokens"
            else:
                stop_reason = "end_turn"
            
            # 构建 usage
            token_count = msg.get("token_count")
            usage_block = {
                "input_tokens": 0,  # Hermes 不记录详细的 input tokens
                "output_tokens": token_count if token_count else 0,
            }
            
            # 生成 request_id 和 response_id
            request_id = f"msg_{uuid.uuid4().hex[:24]}"
            response_id = f"msg_{uuid.uuid4().hex[:24]}"
            
            # 构建 call 记录
            call_record = {
                "session_id": session_id,
                "request_id": request_id,
                "timestamp": normalize_timestamp(msg.get("timestamp")),
                "thinking_effort": thinking_effort,
                "request": {
                    "model": model_name,
                    "max_tokens": max_tokens,
                    "temperature": temperature,
                    "thinking": {
                        "type": thinking_type,
                        "budget_tokens": 10000,
                    },
                    "system": system_blocks,
                    "tools": tools_list,
                    "messages": [m for m in anthropic_messages],
                },
                "response": {
                    "response_data": {
                        "id": response_id,
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
            
            # 如果有 tool results，添加到上下文
            if tool_results:
                user_tool_blocks = []
                for tr in tool_results:
                    user_tool_blocks.append(convert_tool_result_to_block(tr))
                
                anthropic_messages.append({
                    "role": "user",
                    "content": user_tool_blocks,
                })
            
            # 跳过已处理的 tool result 消息
            i = j
        
        else:
            # 其他类型消息（如 system），跳过
            i += 1
    
    return calls, model_name, all_tool_names


def convert_file(json_path, target_dir, system_prompt_override=None):
    """转换一个 Hermes JSON 文件"""
    print(f"\n{'='*60}")
    print(f"[处理] {json_path}")
    
    try:
        # 读取文件获取 system prompt
        with open(json_path, "r", encoding="utf-8") as f:
            hermes_data = json.load(f)
        
        system_prompt = system_prompt_override or extract_system_prompt(hermes_data)
        
        calls, model_name, tool_names = process_hermes_json(json_path, system_prompt)
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
        "file": Path(json_path).name,
        "session_id": session_id,
        "model": model_name,
        "calls": len(calls),
    }


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="Hermes JSON -> Anthropic Call-level 格式转换",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python convert_hermes.py --input_dir D:/sessions/test/opus/2026.07.05_hermes
  python convert_hermes.py --input_dir D:/sessions/test/opus/2026.07.05_hermes --output_dir D:/output
        """
    )
    parser.add_argument("--input_dir", required=True, help="输入目录（包含 .json 文件）")
    parser.add_argument("--output_dir", help="输出目录（可选，默认自动生成）")
    parser.add_argument("--system_prompt", help="覆盖 system prompt（可选）")
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
    
    # 查找所有 JSON 文件（排除以 . 开头的文件）
    json_files = sorted(f for f in input_dir.glob("*.json") 
                       if f.parent == input_dir and not f.name.startswith('.'))
    
    if not json_files:
        print(f"[错误] 未找到 .json 文件: {input_dir}")
        sys.exit(1)
    
    print(f"[输入目录] {input_dir}")
    print(f"[输出目录] {target_dir}")
    print(f"[文件数量] {len(json_files)}")
    
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    results = []
    
    for json_file in json_files:
        result = convert_file(str(json_file), str(target_dir), args.system_prompt)
        if result:
            results.append(result)
    
    # 打印汇总
    print(f"\n{'='*60}")
    print(f"[汇总] 成功处理 {len(results)}/{len(json_files)} 个文件")
    print("="*60)
    
    for r in results:
        print(f"  ✓ {r['file']} -> {r['calls']} calls | model: {r['model']}")
    
    print(f"\n[完成] 输出目录: {target_dir}")


if __name__ == "__main__":
    main()
