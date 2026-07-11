import argparse
import csv
import json
import shutil
import sys
from pathlib import Path
from datetime import datetime
from collections import defaultdict

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


# 默认输入地址
DEFAULT_INPUT_DIR = r"C:\projects\trajectory\供应商试标\朱奚檑7.7\openclaw"

# 允许的模型列表
VALID_MODELS = {"claude-opus-4-6", "claude-opus-4-8"}

# 模型名标准化映射
MODEL_NAME_MAP = {
    "claude-opus-4-6-thinking": "claude-opus-4-6",
    "claude-opus-4-6": "claude-opus-4-6",
    "claude-opus-4-8-thinking": "claude-opus-4-8",
    "claude-opus-4-8": "claude-opus-4-8",
}

# Heartbeat / cron / no_reply 关键词（用于检测低质量对话）
SPECIAL_KEYWORDS = ["HEARTBEAT_OK", "NO_REPLY", "heartbeat poll", "[OpenClaw heartbeat poll]"]

# 合法的 thinking_effort
VALID_EFFORTS = ["high", "xhigh", "max"]


def load_session_calls(session_dir):
    """
    从 session 目录加载所有 call 记录
    
    参数:
        session_dir: session 目录路径
    返回:
        list: call 记录列表（按文件名排序）
    """
    calls = []
    json_files = sorted(session_dir.glob("*.json"))
    
    for json_file in json_files:
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                call = json.load(f)
                calls.append(call)
        except Exception as e:
            print(f"  [警告] 无法加载 {json_file.name}: {e}")
    
    return calls


def validate_session(session_dir):
    """
    验证一个 session 的所有 calls 是否符合质检标准
    
    质检项目：
    1. Session 级检查
       - session_id 一致性
       - request_id 唯一性
       - model 有效性&一致性
       - thinking_effort 有效性
    
    2. Call 级检查
       - system 非空
       - tools schema 结构正确
       - messages 格式正确（第一条必须是 user）
       - response content 是列表
       - thinking blocks 完整性
       - tool_use 结构正确
       - tool_use_id 匹配性
       - response stop_reason 有效性
    
    3. 质量检查
       - assistant turns 数量（≥5）
       - cron/heartbeat/no_reply 比例（<25%）
       - tool call error 比例（<25%）
       - thinking density（>50%）
       - 末轮完整性（必须是 end_turn 且包含 text）
       - tool_use 必须在 tools schema 中定义
    
    参数:
        session_dir: session 目录路径
    返回:
        tuple: (是否通过, 错误列表, 警告列表, 统计信息字典)
    """
    calls = load_session_calls(session_dir)
    
    if not calls:
        return False, ["目录中没有有效的 call 文件"], [], {}
    
    errors = []
    stats = {}

    # --- Session 级检查 ---
    
    # 检查 session_id 一致性
    session_ids = set(c.get("session_id") for c in calls)
    if len(session_ids) > 1:
        errors.append(f"一个 session 中包含多个 session_id: {session_ids}")
    
    # 检查 request_id 唯一性
    request_ids = [c.get("request_id") for c in calls]
    if len(request_ids) != len(set(request_ids)):
        errors.append("存在重复的 request_id")
    
    # 检查 model 有效性&一致性
    model_names = [c.get("request", {}).get("model", "unknown") for c in calls]
    normalized_models = [MODEL_NAME_MAP.get(model_name, model_name) for model_name in model_names]
    if len(set(normalized_models)) > 1:
        errors.append(f"同一session中，模型名称不唯一")
    for name in normalized_models:
        if name not in VALID_MODELS:
            errors.append(f"模型 '{name}' 不在允许列表中（允许: {VALID_MODELS}）")
    
    # 检查 thinking_effort 一致性
    thinking_efforts = [c.get("thinking_effort") for c in calls]      
    for effort in thinking_efforts:
        if effort not in VALID_EFFORTS:
            errors.append("thinking_effort 不属于 [high, xhigh, max]")

    
    # --- Call 级检查 ---
    
    for idx, c in enumerate(calls):
        req = c.get("request", {})
        resp = c.get("response", {}).get("response_data", {})
        
        # 检查 system 非空
        if not req.get("system"):
            errors.append(f"Call {idx}: request.system 为空")
        
        # 检查 tools 是列表且结构正确
        tools = req.get("tools", [])
        if not isinstance(tools, list):
            errors.append(f"Call {idx}: request.tools 不是列表")
        else:
            for t in tools:
                if not all(k in t for k in ("name", "description", "input_schema")):
                    errors.append(f"Call {idx}: tools 中缺少 name/description/input_schema")
                    break
        
        # 检查 messages[0].role == user
        msgs = req.get("messages", [])
        if msgs and msgs[0].get("role") != "user":
            errors.append(f"Call {idx}: messages[0].role 不是 'user' (实际: '{msgs[0].get('role')}')")

        # 检查 response.content 是列表
        resp_content = resp.get("content", [])
        if not isinstance(resp_content, list):
            errors.append(f"Call {idx}: response.content 不是列表")
        
        # 检查 stop_reason 有效性
        stop_reason = resp.get("stop_reason")
        if stop_reason not in ("end_turn", "tool_use", "max_tokens", "stop_sequence"):
            errors.append(f"Call {idx}: stop_reason 无效 ('{stop_reason}')")
        
        # 检查 thinking blocks: thinking 非空且有 signature
        for block in resp_content:
            if block.get("type") == "thinking":
                if not block.get("thinking", "").strip():
                    errors.append(f"Call {idx}: thinking block 为空")
                if not block.get("signature"):
                    errors.append(f"Call {idx}: thinking block 缺少 signature")
        
        # 检查 tool_use: id/name/input 都存在，input 是字典
        for block in resp_content:
            if block.get("type") == "tool_use":
                if not all(k in block for k in ("id", "name", "input")):
                    errors.append(f"Call {idx}: tool_use 缺少 id/name/input")
                if not isinstance(block.get("input"), dict):
                    errors.append(f"Call {idx}: tool_use.input 不是字典")
        
        # 检查 tool_result id 匹配性
        tool_use_ids = set()
        for msg in msgs:
            if msg.get("role") == "assistant":
                for b in msg.get("content", []):
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        tool_use_ids.add(b.get("id"))
        
        for msg in msgs:
            if msg.get("role") == "user":
                for b in msg.get("content", []):
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        if b.get("tool_use_id") not in tool_use_ids:
                            errors.append(f"Call {idx}: tool_result 的 tool_use_id '{b.get('tool_use_id')}' 没有匹配的 tool_use")
    
    # --- 质量检查（基于完整轨迹 = 最后一个 call 的视角）---
    
    # 1. 检查 assistant turns 数量
    assistant_count = len(calls)
    stats["assistant_turns"] = assistant_count
    if assistant_count < 5:
        errors.append(f"assistant turns 数量 = {assistant_count} (< 5，对话轮数过少)")
    
    # 2. 检查 cron/heartbeat/no_reply 比例
    last_call = calls[-1]
    all_user_msgs = []
    for msg in last_call["request"]["messages"]:
        if msg.get("role") == "user":
            all_user_msgs.append(msg)
    
    cron_count = 0
    for msg in all_user_msgs:
        text_parts = []
        for b in msg.get("content", []):
            if isinstance(b, dict) and b.get("type") == "text":
                text_parts.append(b.get("text", ""))
        full_text = "\n".join(text_parts)
        if any(kw in full_text for kw in SPECIAL_KEYWORDS):
            cron_count += 1
    
    cron_ratio = cron_count / len(all_user_msgs) if all_user_msgs else 0
    stats["cron_ratio"] = cron_ratio
    if cron_ratio >= 0.25:
        errors.append(f"cron/heartbeat/no_reply 比例 = {cron_ratio:.1%} (>= 25%，自动化消息过多)")
    
    # 3. 检查 tool call error 比例
    tool_result_count = 0
    tool_error_count = 0
    for msg in last_call["request"]["messages"]:
        for b in msg.get("content", []) if isinstance(msg.get("content"), list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                tool_result_count += 1
                c = b.get("content", "")
                if b.get("is_error") or (isinstance(c, str) and ('"status": "error"' in c or '"status":"error"' in c)):
                    tool_error_count += 1
    
    tool_err_ratio = tool_error_count / tool_result_count if tool_result_count > 0 else 0
    stats["tool_error_ratio"] = tool_err_ratio
    if tool_err_ratio >= 0.25:
        errors.append(f"tool_call_error 比例 = {tool_err_ratio:.1%} (>= 25%，工具调用错误较多)")
    
    # 4. 检查 tool_use 必须在 tools schema 中定义
    tool_names_in_schema = set(t["name"] for t in last_call["request"]["tools"])
    for idx, c in enumerate(calls):
        for b in c["response"]["response_data"].get("content", []):
            if b.get("type") == "tool_use" and b.get("name") not in tool_names_in_schema:
                errors.append(f"Call {idx}: tool_use '{b['name']}' 未在 tools schema 中定义")
                break
    
    # 5. 检查 thinking density（思考密度）
    think_count = 0
    for c in calls:
        has_think = any(
            b.get("type") == "thinking" and b.get("thinking", "").strip()
            for b in c["response"]["response_data"].get("content", [])
        )
        if has_think:
            think_count += 1
    
    think_density = think_count / assistant_count if assistant_count > 0 else 0
    stats["think_density"] = think_density
    if think_density <= 0.5:
        errors.append(f"thinking density = {think_density:.1%} (<= 50%，思考块密度过低)")
    
    # 6. 检查是否至少有一个非空的 thinking
    any_think = any(
        any(b.get("type") == "thinking" and b.get("thinking", "").strip()
            for b in c["response"]["response_data"].get("content", []))
        for c in calls
    )
    if not any_think:
        errors.append("整个轨迹中没有非空的 thinking block")
    
    # 7. 检查末轮完整性：最后一个 call 必须是 end_turn 且包含 text block
    # 禁止最后一轮是 tool_use（必须是完整的 summary）
    last_resp = calls[-1]["response"]["response_data"]
    last_stop_reason = last_resp.get("stop_reason")
    
    if last_stop_reason == "tool_use":
        errors.append(
            "最后一个 call 的 stop_reason 是 'tool_use' "
            "（禁止最后一轮以 tool_use 结尾，必须是完整的 summary）"
        )
    elif last_stop_reason != "end_turn":
        errors.append(f"最后一个 call 的 stop_reason 是 '{last_stop_reason}'（期望 end_turn）")
    
    has_text = any(b.get("type") == "text" and b.get("text", "").strip()
                   for b in last_resp.get("content", []))
    if not has_text:
        errors.append("最后一个 call 的 response 中没有非空的 text block")
    
    # 8. 检查 thinking 只出现在真实 user 消息后（scaffold bug 检测）
    think_after_user_only = True
    for idx2, c in enumerate(calls):
        has_think2 = any(b.get("type") == "thinking" and b.get("thinking", "").strip()
                        for b in c["response"]["response_data"].get("content", []))
        if has_think2:
            # 检查前一条消息是否是真实的 user 消息（非纯 tool_result）
            req_msgs = c["request"]["messages"]
            if req_msgs:
                last_msg = req_msgs[-1]
                if last_msg.get("role") == "user":
                    # 检查是否只包含 tool_results（没有真实的 user 文本）
                    has_real_text = any(
                        b.get("type") == "text" and b.get("text", "").strip()
                        for b in last_msg.get("content", [])
                        if isinstance(b, dict)
                    )
                    if not has_real_text:
                        think_after_user_only = False
                        break
                else:
                    think_after_user_only = False
                    break
    
    # 规范要求：thinking 不能仅出现在每个真 user 后第一轮
    if think_after_user_only and think_count > 1:
        errors.append("thinking 只出现在真实 user 消息后的第一轮（可能的 scaffold bug）")
    
    # 判断是否通过
    ok = len(errors) == 0
    return ok, errors, stats


def write_quality_report(report_path: Path, input_dir: Path, results: list[dict]) -> None:
    """写入与质检脚本一致的 report.txt。"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write("质检报告\n")
        f.write("=" * 60 + "\n\n")

        f.write(f"输入目录: {input_dir}\n")
        f.write(f"质检时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"总有效 Session 数: {len(results)}\n\n")

        pass_count = sum(1 for r in results if r["status"] == "pass")
        fail_count = sum(1 for r in results if r["status"] == "fail")
        error_count = sum(1 for r in results if r["status"] == "error")

        f.write("-" * 60 + "\n")
        f.write("汇总统计\n")
        f.write("-" * 60 + "\n")
        if results:
            f.write(f"✓ 通过: {pass_count} ({pass_count / len(results) * 100:.1f}%)\n")
            f.write(f"✗ 未通过: {fail_count} ({fail_count / len(results) * 100:.1f}%)\n")
        else:
            f.write("✓ 通过: 0 (0.0%)\n")
            f.write("✗ 未通过: 0 (0.0%)\n")
        if error_count > 0:
            f.write(f"⚠ 错误: {error_count} ({error_count / len(results) * 100:.1f}%)\n")
        f.write("\n")

        if pass_count > 0:
            f.write("-" * 60 + "\n")
            f.write("通过的 Sessions\n")
            f.write("-" * 60 + "\n")
            for r in results:
                if r["status"] == "pass":
                    f.write(f"✓ {r['session_id']}\n")
                    stats = r["stats"]
                    f.write(f"   turns={stats.get('assistant_turns', 0)}, ")
                    f.write(f"think_density={stats.get('think_density', 0):.1%}, ")
                    f.write(f"tool_err={stats.get('tool_error_ratio', 0):.1%}\n")
            f.write("\n")

        if fail_count > 0:
            f.write("-" * 60 + "\n")
            f.write("未通过的 Sessions\n")
            f.write("-" * 60 + "\n")
            for r in results:
                if r["status"] == "fail":
                    f.write(f"✗ {r['session_id']}\n")
                    f.write(f"   错误 ({len(r['errors'])}):\n")
                    for e in r["errors"][:5]:
                        f.write(f"     - {e}\n")
                    if len(r["errors"]) > 5:
                        f.write(f"     ... 还有 {len(r['errors']) - 5} 个错误\n")
                    f.write("\n")

        f.write("-" * 60 + "\n")
        f.write("详细统计\n")
        f.write("-" * 60 + "\n")

        valid_results = [r for r in results if r["status"] in ("pass", "fail")]
        if valid_results:
            avg_turns = sum(r["stats"].get("assistant_turns", 0) for r in valid_results) / len(valid_results)
            avg_think = sum(r["stats"].get("think_density", 0) for r in valid_results) / len(valid_results)
            avg_tool_err = sum(r["stats"].get("tool_error_ratio", 0) for r in valid_results) / len(valid_results)
            avg_cron = sum(r["stats"].get("cron_ratio", 0) for r in valid_results) / len(valid_results)

            f.write(f"平均 assistant turns: {avg_turns:.1f}\n")
            f.write(f"平均 thinking density: {avg_think:.1%}\n")
            f.write(f"平均 tool error ratio: {avg_tool_err:.1%}\n")
            f.write(f"平均 cron ratio: {avg_cron:.1%}\n")

        f.write("\n" + "=" * 60 + "\n")
        f.write("质检完成\n")
        f.write("=" * 60 + "\n")


def collect_validation_results(convert_dir: Path) -> list[dict]:
    """对 convert 目录下所有 session 重新执行 validate_session，返回结果列表。"""
    session_dirs = []
    for item in convert_dir.iterdir():
        if item.is_dir() and any(item.glob("*.json")):
            session_dirs.append(item)

    results: list[dict] = []
    for session_dir in sorted(session_dirs):
        session_id = session_dir.name
        try:
            ok, errors, stats = validate_session(session_dir)
            status = "pass" if ok else "fail"
        except Exception as exc:
            status = "error"
            errors = [str(exc)]
            stats = {}
        results.append(
            {
                "session_id": session_id,
                "status": status,
                "errors": errors,
                "stats": stats,
            }
        )
    return results


def process_session_dir(session_dir, pass_dir, fail_dir):
    """
    处理一个 session 目录，执行质检并移动到对应的输出目录
    
    参数:
        session_dir: session 目录路径
        pass_dir: 通过质检的输出目录
        fail_dir: 未通过质检的输出目录
    返回:
        dict: 质检结果摘要
    """
    session_id = session_dir.name
    print(f"\n[质检] {session_id}")
    
    try:
        ok, errors, stats = validate_session(session_dir)
    except Exception as e:
        print(f"  [错误] 质检失败: {e}")
        import traceback
        traceback.print_exc()
        return {
            "session_id": session_id,
            "status": "error",
            "errors": [str(e)],
            "stats": {},
        }
    
    # 打印统计信息
    print(f"  [统计] turns={stats.get('assistant_turns', 0)} | "
          f"think_density={stats.get('think_density', 0):.1%} | "
          f"tool_err={stats.get('tool_error_ratio', 0):.1%} | "
          f"cron={stats.get('cron_ratio', 0):.1%}")
    
    # 打印错误
    if errors:
        print(f"  [错误] {len(errors)} 项:")
        for e in errors[:3]:  # 只显示前3个
            print(f"    - {e}")
        if len(errors) > 3:
            print(f"    ... 还有 {len(errors) - 3} 项错误")
    
    # 根据结果复制到对应目录（已存在则覆盖）
    if ok:
        print(f"  [结果] ✓ 通过")
        dest = pass_dir / session_id
        status = "pass"
    else:
        print(f"  [结果] ✗ 未通过")
        dest = fail_dir / session_id
        status = "fail"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(session_dir, dest)
    
    return {
        "session_id": session_id,
        "status": status,
        "errors": errors,
        "stats": stats,
    }


def main():
    """主函数：处理命令行参数并执行质检"""
    parser = argparse.ArgumentParser(
        description="Anthropic Call-level 数据质检脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python quality_check.py --input_dir "C:\\Users\\admin\\.openclaw\\agents\\main\\sessions"
  python quality_check.py --input_dir "D:\\sessions\\test\\opus\\heyamei-待质检数据"
        """
    )
    parser.add_argument(
        "--input_dir",
        # required=True,
        default=DEFAULT_INPUT_DIR,
        help="输入目录（包含多个 session 子文件夹，每个文件夹包含 .json call 文件）"
    )
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    
    # 检查输入目录是否存在
    if not input_dir.exists():
        print(f"[错误] 输入目录不存在: {input_dir}")
        sys.exit(1)
    
    # 创建输出目录结构：输入文件夹名-质检结果/
    input_dirname = input_dir.name
    output_root = input_dir.parent / f"{input_dirname}-质检结果"
    pass_dir = output_root / f"{input_dirname}-pass"
    fail_dir = output_root / f"{input_dirname}-fail"
    report_dir = output_root / f"{input_dirname}-report"

    if output_root.exists():
        shutil.rmtree(output_root)
    pass_dir.mkdir(parents=True, exist_ok=True)
    fail_dir.mkdir(parents=True, exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"[输入目录] {input_dir}")
    print(f"[输出目录] {output_root}")
    
    # 查找所有 session 目录（包含 .json 文件的子目录）
    session_dirs = []
    for item in input_dir.iterdir():
        if item.is_dir():
            # 检查目录中是否包含 .json 文件（call 文件）
            if any(item.glob("*.json")):
                session_dirs.append(item)
    
    if not session_dirs:
        print(f"[错误] 未找到有效的 session 目录（包含 .json 文件的子目录）")
        sys.exit(1)
    
    print(f"[Session 数量] {len(session_dirs)}")
    
    # 处理每个 session
    results = []
    filtered_count = 0  # 被时间筛选过滤的session数量
    for session_dir in sorted(session_dirs):   
        result = process_session_dir(session_dir, pass_dir, fail_dir)
        results.append(result)
    
    # 生成失败原因 CSV
    fail_results = [r for r in results if r["status"] == "fail"]
    if fail_results:
        csv_path = fail_dir / "failures.csv"
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["Session ID", "失败原因"])
            
            for r in fail_results:
                session_id = r["session_id"]
                # 合并所有错误为一个字符串
                error_text = "; ".join(r["errors"])
                writer.writerow([session_id, error_text])
        
        print(f"\n[失败记录] 已生成 {csv_path}")
    
    # 生成质检报告
    report_path = report_dir / "report.txt"
    write_quality_report(report_path, input_dir, results)
    
    print(f"\n[质检报告] 已生成 {report_path}")
    
    # 打印控制台汇总
    print(f"\n{'=' * 60}")
    print(f"质检完成")
    print("=" * 60)
    print(f"总有效 Session: {len(results)}")
    print(f"✓ 通过: {pass_count}/{len(results)}")
    print(f"✗ 未通过: {fail_count}/{len(results)}")
    if error_count > 0:
        print(f"⚠ 错误: {error_count}/{len(results)}")
    print(f"\n输出目录: {output_root}")


if __name__ == "__main__":
    main()

