import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  TaskDetail,
  claimTask,
  fetchSubmission,
  fetchSubmissions,
  fetchTask,
  releaseTask,
  uploadTaskFile,
} from "../api/client";
import { useAuth } from "../contexts/AuthContext";

export function TaskDetailPage() {
  const { id } = useParams();
  const taskId = Number(id);
  const { user } = useAuth();
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [message, setMessage] = useState("");
  const [sourceType, setSourceType] = useState("openclaw");
  const [modelVersion, setModelVersion] = useState("opus-4.8");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [pollingId, setPollingId] = useState<number | null>(null);
  const [copiedRound, setCopiedRound] = useState<number | null>(null);

  const load = () => fetchTask(taskId).then(setTask).catch(console.error);

  useEffect(() => {
    load();
  }, [taskId]);

  useEffect(() => {
    if (!pollingId) return;
    const timer = setInterval(async () => {
      try {
        const submission = await fetchSubmission(pollingId);
        if (submission.status === "processing") return;
        setPollingId(null);
        setMessage(
          submission.status === "passed"
            ? `提交成功，难度：${submission.difficulty || "未知"}`
            : `提交失败：${submission.error_message || "未知错误"}`,
        );
        load();
      } catch {
        setPollingId(null);
      }
    }, 3000);
    return () => clearInterval(timer);
  }, [pollingId]);

  if (!task) return <div>加载中...</div>;

  const isOwner = task.claimed_by === user?.username;
  const canUpload = task.status === "claimed" && isOwner;

  const onClaim = async () => {
    await claimTask(taskId);
    load();
  };

  const onRelease = async () => {
    await releaseTask(taskId);
    setMessage("已释放任务");
    load();
  };

  const onUpload = async () => {
    if (!file) {
      setMessage("请选择文件");
      return;
    }
    setUploading(true);
    setMessage("文件已上传，正在后台处理...");
    try {
      const submission = await uploadTaskFile(taskId, file, sourceType, modelVersion);
      setPollingId(submission.id);
      const history = await fetchSubmissions(taskId);
      console.log(history);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setMessage(msg || "上传失败");
    } finally {
      setUploading(false);
    }
  };

  const onCopyTurn = async (round: number, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed";
      textarea.style.opacity = "0";
      document.body.appendChild(textarea);
      textarea.select();
      document.execCommand("copy");
      document.body.removeChild(textarea);
    }
    setCopiedRound(round);
    window.setTimeout(() => {
      setCopiedRound((current) => (current === round ? null : current));
    }, 2000);
  };

  return (
    <div className="space-y-6">
      <Link to="/tasks" className="text-sm text-cyan-300">
        ← 返回任务池
      </Link>

      <div className="card">
        <div className="text-sm text-slate-400">
          #{task.id} · {task.scene_label}
        </div>
        <h1 className="mt-2 text-2xl font-semibold">{task.topic}</h1>
        {task.constraint_text && (
          <div className="mt-2 text-sm text-slate-400">约束：{task.constraint_text}</div>
        )}
        <div className="mt-3 text-sm text-slate-500">
          状态：{task.status} {task.claimed_by ? `· 领取人：${task.claimed_by}` : ""}
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {task.status === "available" && (
            <button className="btn btn-primary" onClick={onClaim}>
              领取任务
            </button>
          )}
          {task.status === "claimed" && isOwner && (
            <button className="btn btn-danger" onClick={onRelease}>
              释放任务
            </button>
          )}
        </div>
      </div>

      <div className="card">
        <h2 className="text-lg font-medium">多轮提问（请依次复制到 OpenClaw / Hermes）</h2>
        <div className="mt-4 space-y-4">
          {task.turns.map((turn) => (
            <div key={turn.round} className="rounded-xl border border-white/10 bg-black/20 p-4">
              <div className="mb-2 flex items-center justify-between gap-3">
                <div className="text-sm text-cyan-300">第 {turn.round} 轮</div>
                <button
                  type="button"
                  className="btn btn-secondary shrink-0 px-3 py-1 text-xs"
                  onClick={() => onCopyTurn(turn.round, turn.content)}
                >
                  {copiedRound === turn.round ? "已复制" : "复制"}
                </button>
              </div>
              <div className="whitespace-pre-wrap text-sm leading-6">{turn.content}</div>
            </div>
          ))}
        </div>
      </div>

      {canUpload && (
        <div className="card space-y-4">
          <h2 className="text-lg font-medium">提交原始对话文件</h2>
          <div className="grid gap-4 md:grid-cols-2">
            <div>
              <label className="mb-1 block text-sm text-slate-400">来源</label>
              <select className="select" value={sourceType} onChange={(e) => setSourceType(e.target.value)}>
                <option value="openclaw">OpenClaw</option>
                <option value="hermes" disabled>
                  Hermes（第一期暂未开放）
                </option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-sm text-slate-400">模型版本</label>
              <select className="select" value={modelVersion} onChange={(e) => setModelVersion(e.target.value)}>
                <option value="opus-4.8">Claude Opus 4.8</option>
                <option value="opus-4.6">Claude Opus 4.6</option>
              </select>
            </div>
          </div>
          <div>
            <label className="mb-1 block text-sm text-slate-400">原始文件 (.jsonl)</label>
            <input
              className="input"
              type="file"
              accept=".jsonl"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
            />
          </div>
          <button className="btn btn-primary" onClick={onUpload} disabled={uploading || !!pollingId}>
            {uploading || pollingId ? "处理中..." : "上传并自动质检评级"}
          </button>
          <p className="text-xs text-slate-500">
            质检失败可多次重新上传；任务仍由你占用，直至通过或主动释放。
          </p>
        </div>
      )}

      {message && <div className="rounded-xl bg-white/5 px-4 py-3 text-sm">{message}</div>}
      {task.latest_submission_error && (
        <div className="rounded-xl bg-red-500/10 px-4 py-3 text-sm text-red-300">
          最近失败：{task.latest_submission_error}
        </div>
      )}
    </div>
  );
}
