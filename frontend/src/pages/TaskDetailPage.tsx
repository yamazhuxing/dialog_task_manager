import React, { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Submission,
  TaskDetail,
  claimTask,
  fetchSubmission,
  fetchSubmissions,
  fetchTask,
  releaseTask,
  uploadTaskFile,
} from "../api/client";
import { useAuth } from "../contexts/AuthContext";

const PIPELINE_STEPS: { step: string; label: string }[] = [
  { step: "queued", label: "文件已接收" },
  { step: "convert", label: "格式转换" },
  { step: "quality_check", label: "质量检测" },
  { step: "difficulty", label: "难度评级" },
  { step: "persist", label: "样本入库" },
  { step: "done", label: "处理完成" },
];

function stepStatusIcon(status: string) {
  if (status === "done") return "✓";
  if (status === "running") return "…";
  if (status === "failed") return "✕";
  return "○";
}

function stepStatusClass(status: string) {
  if (status === "done") return "text-emerald-400 border-emerald-500/40 bg-emerald-500/10";
  if (status === "running") return "text-cyan-300 border-cyan-400/50 bg-cyan-500/10 animate-pulse";
  if (status === "failed") return "text-red-300 border-red-500/40 bg-red-500/10";
  return "text-slate-500 border-white/10 bg-white/5";
}

function ProcessingTimeline({ submission }: { submission: Submission }) {
  const logMap = new Map(submission.processing_log.map((item) => [item.step, item]));
  const currentIdx = PIPELINE_STEPS.findIndex((s) => s.step === submission.processing_step);

  return (
    <div className="space-y-2">
      {PIPELINE_STEPS.map((def, idx) => {
        const item = logMap.get(def.step);
        let status = item?.status || "pending";
        if (!item && submission.status === "processing") {
          status = idx <= currentIdx ? (idx === currentIdx ? "running" : "pending") : "pending";
        }
        if (!item && submission.status === "passed" && idx <= PIPELINE_STEPS.length - 1) {
          status = "done";
        }
        if (!item && submission.status === "failed" && idx < currentIdx) {
          status = "done";
        }
        const label = item?.label || def.label;
        const message = item?.message;

        return (
          <div
            key={def.step}
            className={`flex items-start gap-3 rounded-xl border px-3 py-2 ${stepStatusClass(status)}`}
          >
            <span className="mt-0.5 w-4 shrink-0 text-center text-sm font-semibold">
              {stepStatusIcon(status)}
            </span>
            <div className="min-w-0 flex-1">
              <div className="text-sm font-medium">{label}</div>
              {message && <div className="mt-0.5 text-xs opacity-80">{message}</div>}
              {item?.at && <div className="mt-0.5 text-xs text-slate-500">{item.at}</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function QCFailurePanel({ submission }: { submission: Submission }) {
  const hints =
    submission.qc_hints.length > 0
      ? submission.qc_hints
      : submission.error_message
        ? [
            {
              error: submission.error_message,
              essence: "请对照甲方质检项检查轨迹结构",
              remedy: "根据报错调整对话后重新导出上传",
            },
          ]
        : [];

  const statEntries = Object.entries(submission.qc_stats || {});

  return (
    <div className="space-y-4">
      {statEntries.length > 0 && (
        <div className="flex flex-wrap gap-2 text-xs">
          {statEntries.map(([key, value]) => (
            <span key={key} className="rounded-full bg-white/5 px-2.5 py-1 text-slate-300">
              {key}={value}
            </span>
          ))}
        </div>
      )}
      <div className="overflow-x-auto rounded-xl border border-red-500/20">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="bg-red-500/10 text-xs text-red-200">
            <tr>
              <th className="px-3 py-2 font-medium">Session</th>
              <th className="px-3 py-2 font-medium">报错</th>
              <th className="px-3 py-2 font-medium">本质</th>
              <th className="px-3 py-2 font-medium">补救</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-white/5">
            {hints.map((hint, idx) => (
              <tr key={idx} className="align-top">
                <td className="px-3 py-3 font-mono text-xs text-slate-300">
                  {submission.session_id?.slice(0, 8) || "—"}
                </td>
                <td className="px-3 py-3 text-red-200">{hint.error}</td>
                <td className="px-3 py-3 text-slate-300">{hint.essence}</td>
                <td className="px-3 py-3 text-cyan-200">{hint.remedy}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {submission.session_id && (
        <div className="text-xs text-slate-500">完整 Session ID：{submission.session_id}</div>
      )}
    </div>
  );
}

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
  const [activeSubmission, setActiveSubmission] = useState<Submission | null>(null);
  const [copiedRound, setCopiedRound] = useState<number | null>(null);

  const load = useCallback(() => fetchTask(taskId).then(setTask).catch(console.error), [taskId]);

  const loadSubmissions = useCallback(async () => {
    try {
      const subs = await fetchSubmissions(taskId);
      const latest = subs[0] ?? null;
      setActiveSubmission(latest);
      if (latest?.status === "processing") {
        setPollingId(latest.id);
      }
      return latest;
    } catch (err) {
      console.error(err);
      return null;
    }
  }, [taskId]);

  useEffect(() => {
    load();
    loadSubmissions();
  }, [load, loadSubmissions]);

  useEffect(() => {
    if (!pollingId) return;
    const timer = setInterval(async () => {
      try {
        const submission = await fetchSubmission(pollingId);
        setActiveSubmission(submission);
        if (submission.status === "processing") return;
        setPollingId(null);
        setMessage(
          submission.status === "passed"
            ? `提交成功，难度：${submission.difficulty || "未知"}`
            : "提交未通过，请查看下方失败分析",
        );
        load();
      } catch {
        setPollingId(null);
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [pollingId, load]);

  if (!task) return <div>加载中...</div>;

  const isOwner = task.claimed_by === user?.username;
  const canUpload = task.status === "claimed" && isOwner;
  const isProcessing = activeSubmission?.status === "processing" || !!pollingId;

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
      setActiveSubmission(submission);
      setPollingId(submission.id);
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
          <button className="btn btn-primary" onClick={onUpload} disabled={uploading || isProcessing}>
            {uploading || isProcessing ? "处理中..." : "上传并自动质检评级"}
          </button>
          <p className="text-xs text-slate-500">
            质检失败可多次重新上传；任务仍由你占用，直至通过或主动释放。
          </p>
        </div>
      )}

      {activeSubmission && (isProcessing || activeSubmission.status !== "processing") && (
        <div className="card space-y-4">
          <div className="flex items-center justify-between gap-3">
            <h2 className="text-lg font-medium">处理进度</h2>
            <span
              className={`badge ${
                activeSubmission.status === "passed"
                  ? "badge-passed"
                  : activeSubmission.status === "failed"
                    ? "bg-red-500/20 text-red-300"
                    : "badge-claimed"
              }`}
            >
              {activeSubmission.status === "processing"
                ? "处理中"
                : activeSubmission.status === "passed"
                  ? "已通过"
                  : "未通过"}
            </span>
          </div>
          <ProcessingTimeline submission={activeSubmission} />
          {activeSubmission.status === "passed" && activeSubmission.difficulty && (
            <div className="rounded-xl bg-cyan-500/10 px-4 py-3 text-sm text-cyan-200">
              难度评级：{activeSubmission.difficulty}
              {activeSubmission.detected_model ? ` · 检测模型：${activeSubmission.detected_model}` : ""}
            </div>
          )}
          {activeSubmission.status === "failed" && (
            <div className="space-y-3">
              <h3 className="text-base font-medium text-red-200">质检失败分析</h3>
              <QCFailurePanel submission={activeSubmission} />
            </div>
          )}
        </div>
      )}

      {message && <div className="rounded-xl bg-white/5 px-4 py-3 text-sm">{message}</div>}
    </div>
  );
}
