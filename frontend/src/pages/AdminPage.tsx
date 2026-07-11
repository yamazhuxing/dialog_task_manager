import React, { useEffect, useRef, useState } from "react";
import {
  createTask,
  createUser,
  deleteTask,
  backfillSampleMetadata,
  fetchScenes,
  fetchUserStats,
  getToken,
  importQuestionsFile,
  SceneOption,
} from "../api/client";

interface UserStat {
  user_id: number;
  username: string;
  claimed_count: number;
  submitted_count: number;
  passed_count: number;
}

const MIN_TURNS = 5;
const MAX_TURNS = 10;
const EMPTY_TURNS = () => Array.from({ length: MIN_TURNS }, () => "");

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function AdminPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
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
  const [backfilling, setBackfilling] = useState(false);

  useEffect(() => {
    fetchUserStats().then(setUserStats).catch(console.error);
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

  const onBackfillMetadata = async () => {
    setBackfilling(true);
    setMessage("");
    try {
      const result = await backfillSampleMetadata();
      setMessage(`已补写 ${result.backfilled_count} 条样本的场景元数据`);
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setMessage(msg || "补写失败");
    } finally {
      setBackfilling(false);
    }
  };

  const onDownloadZip = async () => {
    const token = getToken();
    const res = await fetch("/api/delivery/zip", {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!res.ok) {
      setMessage("下载失败，请确认已有通过样本");
      return;
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `delivery_${Date.now()}.zip`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">管理后台</h1>
        <p className="mt-1 text-sm text-slate-400">用户管理、题目导入、交付物下载</p>
      </div>

      {message && <div className="rounded-xl bg-cyan-500/10 px-4 py-3 text-sm text-cyan-200">{message}</div>}

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
        <h2 className="font-medium">用户完成明细</h2>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-slate-400">
              <tr>
                <th className="py-2">用户</th>
                <th>领取数</th>
                <th>提交数</th>
                <th>通过数</th>
              </tr>
            </thead>
            <tbody>
              {userStats.map((item) => (
                <tr key={item.user_id} className="border-t border-white/10">
                  <td className="py-2">{item.username}</td>
                  <td>{item.claimed_count}</td>
                  <td>{item.submitted_count}</td>
                  <td>{item.passed_count}</td>
                </tr>
              ))}
              {userStats.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-4 text-slate-500">
                    暂无普通用户数据
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card space-y-4">
        <h2 className="font-medium">交付物下载</h2>
        <p className="text-sm text-slate-400">打包已通过样本的「待质检数据」和「质检结果」目录（含各 session 的 sample_metadata.json）</p>
        <div className="flex flex-wrap gap-2">
          <button className="btn btn-secondary" onClick={onBackfillMetadata} disabled={backfilling}>
            {backfilling ? "补写中..." : "补写场景元数据"}
          </button>
          <button className="btn btn-primary" onClick={onDownloadZip}>
            下载 ZIP
          </button>
        </div>
      </div>
    </div>
  );
}
