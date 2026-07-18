import React, { useEffect, useRef, useState } from "react";
import {
  createTask,
  createUser,
  deleteTask,
  fetchDifficultyRepairs,
  fetchScenes,
  fetchUserStats,
  getToken,
  importQuestionsFile,
  InvalidDifficultySample,
  qcExternalZip,
  retryTaskDifficulty,
  SceneOption,
  ZipQcResponse,
} from "../api/client";

interface UserStat {
  user_id: number;
  username: string;
  role: string;
  claimed_count: number;
  in_progress_count: number;
  submitted_count: number;
  failed_count: number;
  passed_count: number;
}

function loadUserStats(setUserStats: (stats: UserStat[]) => void) {
  fetchUserStats().then(setUserStats).catch(console.error);
}

const MIN_TURNS = 5;
const MAX_TURNS = 10;
const EMPTY_TURNS = () => Array.from({ length: MIN_TURNS }, () => "");

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatApiDateTime(value: string | null) {
  if (!value) return "-";
  const normalized = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`;
  return new Date(normalized).toLocaleString("zh-CN", { timeZone: "Asia/Shanghai" });
}

function loadDifficultyRepairs(setItems: (items: InvalidDifficultySample[]) => void) {
  fetchDifficultyRepairs().then(setItems).catch(console.error);
}

export function AdminPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [downloadingZip, setDownloadingZip] = useState(false);
  const [downloadProgress, setDownloadProgress] = useState<{
    phase: "packaging" | "downloading";
    percent: number | null;
  } | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [userStats, setUserStats] = useState<UserStat[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [scenes, setScenes] = useState<SceneOption[]>([]);
  const [taskScene, setTaskScene] = useState("");
  const [taskTopic, setTaskTopic] = useState("");
  const [taskConstraint, setTaskConstraint] = useState("");
  const [taskTurns, setTaskTurns] = useState<string[]>(EMPTY_TURNS);
  const [creatingTask, setCreatingTask] = useState(false);
  const [deleteTaskId, setDeleteTaskId] = useState("");
  const [deletingTask, setDeletingTask] = useState(false);
  const [difficultyRepairs, setDifficultyRepairs] = useState<InvalidDifficultySample[]>([]);
  const [retryingDifficultyTaskId, setRetryingDifficultyTaskId] = useState<number | null>(null);
  const [qcZipFile, setQcZipFile] = useState<File | null>(null);
  const [qcZipChecking, setQcZipChecking] = useState(false);
  const [qcZipResult, setQcZipResult] = useState<ZipQcResponse | null>(null);
  const qcZipInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    loadUserStats(setUserStats);
    loadDifficultyRepairs(setDifficultyRepairs);
    fetchScenes()
      .then((items) => {
        setScenes(items);
        if (items.length > 0) setTaskScene(items[0].value);
      })
      .catch(console.error);
  }, []);

  const pickFile = (file: File | null) => {
    if (!file) return;
    if (!file.name.endsWith(".json")) {
      setMessage("请选择 .json 格式的题目文件");
      return;
    }
    setImportFile(file);
    setMessage("");
  };

  const clearImportFile = () => {
    setImportFile(null);
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const resetTaskForm = () => {
    setTaskTopic("");
    setTaskConstraint("");
    setTaskTurns(EMPTY_TURNS());
    if (scenes.length > 0) setTaskScene(scenes[0].value);
  };

  const updateTurn = (index: number, value: string) => {
    setTaskTurns((prev) => prev.map((item, i) => (i === index ? value : item)));
  };

  const addTurn = () => {
    if (taskTurns.length >= MAX_TURNS) return;
    setTaskTurns((prev) => [...prev, ""]);
  };

  const removeTurn = () => {
    if (taskTurns.length <= MIN_TURNS) return;
    setTaskTurns((prev) => prev.slice(0, -1));
  };

  const onCreateUser = async () => {
    try {
      await createUser(username, password);
      setMessage(`用户 ${username} 创建成功`);
      setUsername("");
      setPassword("");
      loadUserStats(setUserStats);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setMessage(msg || "创建失败");
    }
  };

  const onCreateTask = async () => {
    if (creatingTask) return;
    const turns = taskTurns.map((content) => content.trim());
    if (!taskTopic.trim()) {
      setMessage("请填写任务主题");
      return;
    }
    if (turns.some((content) => !content)) {
      setMessage("每轮提问都不能为空");
      return;
    }
    setCreatingTask(true);
    setMessage("");
    try {
      const result = await createTask({
        scene: taskScene,
        topic: taskTopic.trim(),
        constraint_text: taskConstraint.trim() || undefined,
        turns: turns.map((content) => ({ content })),
      });
      setMessage(`任务 #${result.id} 创建成功：${result.topic}（${result.turn_count} 轮）`);
      resetTaskForm();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setMessage(msg || "创建任务失败");
    } finally {
      setCreatingTask(false);
    }
  };

  const onDeleteTaskById = async () => {
    const taskId = Number(deleteTaskId);
    if (!taskId || taskId < 1) {
      setMessage("请输入有效的任务 ID");
      return;
    }
    if (!window.confirm(`确定删除任务 #${taskId} 吗？此操作不可恢复。`)) return;
    setDeletingTask(true);
    setMessage("");
    try {
      const result = await deleteTask(taskId);
      setMessage(result.message || `任务 #${taskId} 已删除`);
      setDeleteTaskId("");
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setMessage(msg || "删除失败");
    } finally {
      setDeletingTask(false);
    }
  };

  const onImportFile = async () => {
    if (!importFile || importing) return;
    setImporting(true);
    setMessage("");
    try {
      const result = await importQuestionsFile(importFile);
      setMessage(
        `导入成功：新增 ${result.imported_count} 题，跳过 ${result.skipped_count} 题，当前共 ${result.total_tasks} 题`,
      );
      clearImportFile();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setMessage(msg || "导入失败");
    } finally {
      setImporting(false);
    }
  };

  const downloadDeliveryZip = async (apiPath: string, filenamePrefix: string, successLabel: string) => {
    if (downloadingZip) return;
    setDownloadingZip(true);
    setMessage("");
    setDownloadProgress({ phase: "packaging", percent: null });
    try {
      const token = getToken();
      const res = await fetch(apiPath, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!res.ok) {
        let detail = "下载失败，请确认已有通过样本";
        try {
          const data = (await res.json()) as { detail?: string };
          if (data.detail) detail = data.detail;
        } catch {
          // ignore non-json error body
        }
        setMessage(detail);
        return;
      }

      const totalBytes = Number(res.headers.get("Content-Length") || 0);
      setDownloadProgress({ phase: "downloading", percent: totalBytes > 0 ? 0 : null });

      let blob: Blob;
      if (!res.body) {
        blob = await res.blob();
      } else {
        const reader = res.body.getReader();
        const chunks: Uint8Array[] = [];
        let received = 0;
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          chunks.push(value);
          received += value.length;
          if (totalBytes > 0) {
            setDownloadProgress({
              phase: "downloading",
              percent: Math.min(99, Math.round((received / totalBytes) * 100)),
            });
          }
        }
        blob = new Blob(chunks as BlobPart[], { type: res.headers.get("Content-Type") || "application/zip" });
      }

      if (totalBytes > 0) {
        setDownloadProgress({ phase: "downloading", percent: 100 });
      }

      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${filenamePrefix}_${Date.now()}.zip`;
      a.click();
      URL.revokeObjectURL(url);
      setMessage(
        totalBytes > 0 ? `${successLabel}已开始下载（${formatFileSize(totalBytes)}）` : `${successLabel}已开始下载`,
      );
    } catch {
      setMessage("下载失败，请稍后重试");
    } finally {
      setDownloadingZip(false);
      setDownloadProgress(null);
    }
  };

  const onRetryDifficulty = async (taskId: number) => {
    if (retryingDifficultyTaskId != null) return;
    setRetryingDifficultyTaskId(taskId);
    setMessage("");
    try {
      const result = await retryTaskDifficulty(taskId);
      setMessage(`任务 #${taskId} 难度补评成功：${result.difficulty}`);
      loadDifficultyRepairs(setDifficultyRepairs);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setMessage(msg || `任务 #${taskId} 难度补评失败`);
    } finally {
      setRetryingDifficultyTaskId(null);
    }
  };

  const onDownloadRawZip = () =>
    downloadDeliveryZip("/api/delivery/raw-zip", "delivery_raw", "原始数据 ZIP ");

  const onDownloadV2Zip = () =>
    downloadDeliveryZip("/api/delivery/v2-zip", "delivery_v2", "新版交付 ZIP ");

  const onPickQcZip = (file: File | null) => {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".zip")) {
      setMessage("请选择 .zip 格式的样本包");
      return;
    }
    setQcZipFile(file);
    setQcZipResult(null);
    setMessage("");
  };

  const clearQcZip = () => {
    setQcZipFile(null);
    setQcZipResult(null);
    if (qcZipInputRef.current) qcZipInputRef.current.value = "";
  };

  const onQcZip = async () => {
    if (!qcZipFile || qcZipChecking) return;
    setQcZipChecking(true);
    setMessage("");
    setQcZipResult(null);
    try {
      const result = await qcExternalZip(qcZipFile);
      setQcZipResult(result);
      setMessage(
        `ZIP 质检完成：共 ${result.total} 条，通过 ${result.pass_count}，未通过 ${result.fail_count}` +
          (result.error_count > 0 ? `，错误 ${result.error_count}` : ""),
      );
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setMessage(msg || "ZIP 质检失败");
    } finally {
      setQcZipChecking(false);
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">管理后台</h1>
        <p className="mt-1 text-sm text-slate-400">用户管理、题目导入、交付物下载</p>
      </div>

      {message && <div className="rounded-xl bg-cyan-500/10 px-4 py-3 text-sm text-cyan-200">{message}</div>}

      <div className="card space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-medium">用户任务统计</h2>
            <p className="mt-1 text-sm text-slate-400">
              各账号领取、提交、通过情况（含管理员）
            </p>
          </div>
          <button className="btn btn-secondary px-3 py-1 text-xs" onClick={() => loadUserStats(setUserStats)}>
            刷新
          </button>
        </div>
        <div className="overflow-x-auto rounded-xl border border-white/10">
          <table className="w-full min-w-[640px] text-left text-sm">
            <thead className="bg-white/5 text-xs text-slate-400">
              <tr>
                <th className="px-3 py-2 font-medium">用户</th>
                <th className="px-3 py-2 font-medium">角色</th>
                <th className="px-3 py-2 font-medium">领取/占用</th>
                <th className="px-3 py-2 font-medium">制作中</th>
                <th className="px-3 py-2 font-medium">提交</th>
                <th className="px-3 py-2 font-medium">未通过</th>
                <th className="px-3 py-2 font-medium">已通过</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {userStats.map((item) => (
                <tr key={item.user_id}>
                  <td className="px-3 py-2 font-medium">{item.username}</td>
                  <td className="px-3 py-2">
                    <span
                      className={`badge ${item.role === "admin" ? "bg-violet-500/20 text-violet-300" : "badge-claimed"}`}
                    >
                      {item.role === "admin" ? "管理员" : "制作员"}
                    </span>
                  </td>
                  <td className="px-3 py-2">{item.claimed_count}</td>
                  <td className="px-3 py-2 text-amber-300">{item.in_progress_count}</td>
                  <td className="px-3 py-2">{item.submitted_count}</td>
                  <td className="px-3 py-2 text-red-300">{item.failed_count}</td>
                  <td className="px-3 py-2 text-cyan-300">{item.passed_count}</td>
                </tr>
              ))}
              {userStats.length > 0 && (
                <tr className="bg-white/[0.03] text-slate-300">
                  <td className="px-3 py-2 font-medium" colSpan={2}>
                    合计（{userStats.length} 人）
                  </td>
                  <td className="px-3 py-2">{userStats.reduce((s, u) => s + u.claimed_count, 0)}</td>
                  <td className="px-3 py-2">{userStats.reduce((s, u) => s + u.in_progress_count, 0)}</td>
                  <td className="px-3 py-2">{userStats.reduce((s, u) => s + u.submitted_count, 0)}</td>
                  <td className="px-3 py-2">{userStats.reduce((s, u) => s + u.failed_count, 0)}</td>
                  <td className="px-3 py-2">{userStats.reduce((s, u) => s + u.passed_count, 0)}</td>
                </tr>
              )}
              {userStats.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-6 text-center text-slate-500">
                    暂无用户数据
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-slate-500">
          领取/占用 = 当前占用或已完成的任务数；制作中 = 已领取但未通过；提交 = 上传次数（含失败重试）
        </p>
      </div>

      <div className="card space-y-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="font-medium">难度补评</h2>
            <p className="mt-1 text-sm text-slate-400">
              已通过但难度无效（如 API 欠费导致「调用失败」）的样本，可在此重新评级并同步数据库与交付物
            </p>
          </div>
          <button
            className="btn btn-secondary px-3 py-1 text-xs"
            onClick={() => loadDifficultyRepairs(setDifficultyRepairs)}
          >
            刷新
          </button>
        </div>
        <div className="overflow-x-auto rounded-xl border border-white/10">
          <table className="w-full min-w-[720px] text-left text-sm">
            <thead className="bg-white/5 text-xs text-slate-400">
              <tr>
                <th className="px-3 py-2 font-medium">任务</th>
                <th className="px-3 py-2 font-medium">用户</th>
                <th className="px-3 py-2 font-medium">当前难度</th>
                <th className="px-3 py-2 font-medium">通过时间</th>
                <th className="px-3 py-2 font-medium">操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {difficultyRepairs.map((item) => (
                <tr key={item.task_id}>
                  <td className="px-3 py-2">
                    <div className="font-medium">#{item.task_id}</div>
                    <div className="mt-1 max-w-xs truncate text-xs text-slate-500">{item.topic}</div>
                  </td>
                  <td className="px-3 py-2">{item.username}</td>
                  <td className="px-3 py-2 text-amber-300">{item.difficulty || "（空）"}</td>
                  <td className="px-3 py-2 text-slate-400">{formatApiDateTime(item.passed_at)}</td>
                  <td className="px-3 py-2">
                    <button
                      className="btn btn-primary px-3 py-1 text-xs"
                      disabled={retryingDifficultyTaskId != null}
                      onClick={() => onRetryDifficulty(item.task_id)}
                    >
                      {retryingDifficultyTaskId === item.task_id ? "评级中..." : "重新评级"}
                    </button>
                  </td>
                </tr>
              ))}
              {difficultyRepairs.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-3 py-6 text-center text-slate-500">
                    暂无需要补评的已通过样本
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card space-y-4">
        <h2 className="font-medium">创建用户</h2>
        <input className="input" placeholder="用户名" value={username} onChange={(e) => setUsername(e.target.value)} />
        <input
          className="input"
          placeholder="密码"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button className="btn btn-primary" onClick={onCreateUser}>
          创建账号
        </button>
      </div>

      <div className="card space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-medium">新增单条任务</h2>
            <p className="mt-1 text-sm text-slate-400">手动录入任务，支持 {MIN_TURNS}~{MAX_TURNS} 轮提问</p>
          </div>
          <span className="badge badge-passed shrink-0">{taskTurns.length} 轮</span>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label className="mb-1 block text-sm text-slate-400">场景</label>
            <select className="select" value={taskScene} onChange={(e) => setTaskScene(e.target.value)}>
              {scenes.map((scene) => (
                <option key={scene.value} value={scene.value}>
                  {scene.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-sm text-slate-400">约束（可选）</label>
            <input
              className="input"
              placeholder="如：文件批处理"
              value={taskConstraint}
              onChange={(e) => setTaskConstraint(e.target.value)}
            />
          </div>
        </div>

        <div>
          <label className="mb-1 block text-sm text-slate-400">任务主题</label>
          <input
            className="input"
            placeholder="如：Rust CLI 文件批处理工具"
            value={taskTopic}
            onChange={(e) => setTaskTopic(e.target.value)}
          />
        </div>

        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <label className="text-sm text-slate-400">多轮提问</label>
            <div className="flex gap-2">
              <button
                className="btn btn-secondary px-3 py-1 text-xs"
                onClick={removeTurn}
                disabled={taskTurns.length <= MIN_TURNS}
              >
                减少一轮
              </button>
              <button
                className="btn btn-secondary px-3 py-1 text-xs"
                onClick={addTurn}
                disabled={taskTurns.length >= MAX_TURNS}
              >
                增加一轮
              </button>
            </div>
          </div>
          {taskTurns.map((turn, index) => (
            <div key={index}>
              <div className="mb-1 text-xs text-cyan-300/80">第 {index + 1} 轮</div>
              <textarea
                className="textarea min-h-20 resize-y"
                placeholder={`输入第 ${index + 1} 轮用户提问`}
                value={turn}
                onChange={(e) => updateTurn(index, e.target.value)}
              />
            </div>
          ))}
        </div>

        <div className="flex flex-wrap gap-2">
          <button className="btn btn-primary" onClick={onCreateTask} disabled={creatingTask}>
            {creatingTask ? "创建中..." : "创建任务"}
          </button>
          <button className="btn btn-secondary" onClick={resetTaskForm} disabled={creatingTask}>
            重置
          </button>
        </div>
      </div>

      <div className="card space-y-4">
        <div>
          <h2 className="font-medium">删除任务</h2>
          <p className="mt-1 text-sm text-slate-400">仅可删除未通过的任务，已通过样本不可删除</p>
        </div>
        <div className="flex flex-col gap-3 sm:flex-row">
          <input
            className="input"
            placeholder="输入任务 ID，如 1201"
            value={deleteTaskId}
            onChange={(e) => setDeleteTaskId(e.target.value.replace(/\D/g, ""))}
          />
          <button className="btn btn-danger shrink-0" onClick={onDeleteTaskById} disabled={deletingTask}>
            {deletingTask ? "删除中..." : "删除任务"}
          </button>
        </div>
      </div>

      <div className="card space-y-4">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="font-medium">批量导入题目</h2>
            <p className="mt-1 text-sm text-slate-400">上传 JSON 文件批量补充题目</p>
          </div>
          <span className="badge badge-passed shrink-0">JSON 数组</span>
        </div>

        <input
          ref={fileInputRef}
          type="file"
          accept=".json,application/json"
          className="hidden"
          onChange={(e) => pickFile(e.target.files?.[0] || null)}
        />

        {!importFile ? (
          <div
            className={`file-drop ${dragOver ? "file-drop-active" : ""}`}
            onClick={() => fileInputRef.current?.click()}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragOver(false);
              pickFile(e.dataTransfer.files?.[0] || null);
            }}
          >
            <div className="text-sm text-slate-200">点击或拖拽 JSON 文件到此处</div>
            <div className="mt-1 text-xs text-slate-500">格式与 questions_1200.json 相同，重复 ID 自动跳过</div>
          </div>
        ) : (
          <div className="flex flex-col gap-3 rounded-xl border border-white/10 bg-white/[0.03] p-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <div className="truncate font-medium text-slate-200">{importFile.name}</div>
              <div className="mt-1 text-xs text-slate-500">{formatFileSize(importFile.size)}</div>
            </div>
            <div className="flex shrink-0 gap-2">
              <button className="btn btn-secondary" onClick={() => fileInputRef.current?.click()}>
                重选
              </button>
              <button className="btn btn-secondary" onClick={clearImportFile}>
                清除
              </button>
              <button className="btn btn-primary" onClick={onImportFile} disabled={importing}>
                {importing ? "导入中..." : "确认导入"}
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="card space-y-4">
        <h2 className="font-medium">第三方 ZIP 样本质检</h2>
        <p className="text-sm text-slate-400">
          上传与平台「新版交付 ZIP」同结构的包：可选 session-scene.jsonl，以及 openclaw/、hermes/ 下的 session
          目录。按平台同一套质检规则检测（模型仅 Opus 4.6/4.8，thinking 仅 xhigh/max；难度须为
          low/medium/high/xhigh/expert，否则判失败），用于非平台生产样本验收。
        </p>
        <input
          ref={qcZipInputRef}
          type="file"
          accept=".zip,application/zip"
          className="hidden"
          onChange={(e) => onPickQcZip(e.target.files?.[0] || null)}
        />
        <div className="flex flex-wrap items-center gap-2">
          <button
            className="btn btn-secondary"
            onClick={() => qcZipInputRef.current?.click()}
            disabled={qcZipChecking}
          >
            选择 ZIP
          </button>
          {qcZipFile && (
            <span className="text-sm text-slate-300">
              {qcZipFile.name}（{formatFileSize(qcZipFile.size)}）
            </span>
          )}
          {qcZipFile && (
            <button className="btn btn-secondary px-3 py-1 text-xs" onClick={clearQcZip} disabled={qcZipChecking}>
              清除
            </button>
          )}
          <button className="btn btn-primary" onClick={onQcZip} disabled={!qcZipFile || qcZipChecking}>
            {qcZipChecking ? "质检中..." : "开始质检"}
          </button>
        </div>
        {qcZipResult && (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-3 text-sm">
              <span className="text-slate-300">合计 {qcZipResult.total}</span>
              <span className="text-cyan-300">通过 {qcZipResult.pass_count}</span>
              <span className="text-red-300">未通过 {qcZipResult.fail_count}</span>
              {qcZipResult.error_count > 0 && (
                <span className="text-amber-300">错误 {qcZipResult.error_count}</span>
              )}
            </div>
            {qcZipResult.structure_warnings.length > 0 && (
              <div className="rounded-xl border border-amber-500/20 bg-amber-500/10 px-3 py-2 text-xs text-amber-200">
                {qcZipResult.structure_warnings.map((w) => (
                  <div key={w}>{w}</div>
                ))}
              </div>
            )}
            <div className="overflow-x-auto rounded-xl border border-white/10">
              <table className="w-full min-w-[720px] text-left text-sm">
                <thead className="bg-white/5 text-xs text-slate-400">
                  <tr>
                    <th className="px-3 py-2 font-medium">来源</th>
                    <th className="px-3 py-2 font-medium">session_id</th>
                    <th className="px-3 py-2 font-medium">场景</th>
                    <th className="px-3 py-2 font-medium">effort</th>
                    <th className="px-3 py-2 font-medium">难度</th>
                    <th className="px-3 py-2 font-medium">轮次</th>
                    <th className="px-3 py-2 font-medium">结果</th>
                    <th className="px-3 py-2 font-medium">原因</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {qcZipResult.sessions.map((item) => (
                    <tr key={`${item.source_type}-${item.session_id}`}>
                      <td className="px-3 py-2">{item.source_type}</td>
                      <td className="px-3 py-2 font-mono text-xs">{item.session_id}</td>
                      <td className="px-3 py-2 text-slate-400">{item.scene || "—"}</td>
                      <td className="px-3 py-2">{item.thinking_effort || "—"}</td>
                      <td className="px-3 py-2">{item.difficulty || "—"}</td>
                      <td className="px-3 py-2">{item.assistant_turns ?? "—"}</td>
                      <td className="px-3 py-2">
                        <span
                          className={`badge ${
                            item.status === "pass"
                              ? "badge-passed"
                              : item.status === "error"
                                ? "bg-amber-500/20 text-amber-300"
                                : "bg-red-500/20 text-red-300"
                          }`}
                        >
                          {item.status === "pass" ? "通过" : item.status === "error" ? "错误" : "未通过"}
                        </span>
                      </td>
                      <td className="max-w-md px-3 py-2 text-xs text-slate-400">
                        {item.errors.length === 0
                          ? "—"
                          : item.errors.slice(0, 3).join("；") +
                            (item.errors.length > 3 ? `…(+${item.errors.length - 3})` : "")}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      <div className="card space-y-4">
        <h2 className="font-medium">交付物下载</h2>
        <p className="text-sm text-slate-400">
          新版交付：session-scene.jsonl + hermes/ + openclaw/，来源目录仅包含 pass 通过样本；目录名、难度文件中的
          session_id 与 call 内真实 session_id 一致（不含平台任务前缀）；不包含 sample_metadata.json。
        </p>
        <p className="text-sm text-slate-400">
          原始上传：打包各已通过样本的用户上传文件（OpenClaw 为 .jsonl，Hermes 为 .json），按来源分子目录，并附带
          raw_manifest.json（任务、用户、session 对照表）。
        </p>
        {downloadProgress && (
          <div className="space-y-2 rounded-xl border border-white/10 bg-black/20 p-4">
            <div className="text-sm text-slate-300">
              {downloadProgress.phase === "packaging"
                ? "正在服务器打包，样本较多时请耐心等待..."
                : downloadProgress.percent != null
                  ? `正在下载 ${downloadProgress.percent}%`
                  : "正在下载..."}
            </div>
            {downloadProgress.percent != null && (
              <div className="h-2 overflow-hidden rounded-full bg-white/10">
                <div
                  className="h-full rounded-full bg-cyan-400 transition-all duration-200"
                  style={{ width: `${downloadProgress.percent}%` }}
                />
              </div>
            )}
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <button
            className="btn btn-primary"
            onClick={onDownloadV2Zip}
            disabled={downloadingZip}
          >
            {downloadingZip
              ? downloadProgress?.phase === "downloading" && downloadProgress.percent != null
                ? `下载中 ${downloadProgress.percent}%`
                : "打包中..."
              : "下载新版交付 ZIP"}
          </button>
          <button
            className="btn btn-secondary"
            onClick={onDownloadRawZip}
            disabled={downloadingZip}
          >
            {downloadingZip
              ? downloadProgress?.phase === "downloading" && downloadProgress.percent != null
                ? `下载中 ${downloadProgress.percent}%`
                : "打包中..."
              : "下载原始上传 ZIP"}
          </button>
        </div>
      </div>
    </div>
  );
}
