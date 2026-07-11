import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { TaskItem, claimTask, fetchTasks } from "../api/client";

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "available"
      ? "badge-available"
      : status === "claimed"
        ? "badge-claimed"
        : "badge-passed";
  const label =
    status === "available" ? "可领取" : status === "claimed" ? "制作中" : "已完成";
  return <span className={`badge ${cls}`}>{label}</span>;
}

export function TasksPage() {
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [statusFilter, setStatusFilter] = useState("available");
  const [sceneFilter, setSceneFilter] = useState("");
  const [message, setMessage] = useState("");

  const load = () => {
    fetchTasks({
      status_filter: statusFilter || undefined,
      scene: sceneFilter || undefined,
    } as Record<string, string>)
      .then(setTasks)
      .catch(console.error);
  };

  useEffect(() => {
    load();
  }, [statusFilter, sceneFilter]);

  const onClaim = async (id: number) => {
    try {
      await claimTask(id);
      setMessage("领取成功");
      load();
    } catch (err: unknown) {
      const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setMessage(msg || "领取失败");
    }
  };

  const scenes = Array.from(new Set(tasks.map((t) => t.scene)));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">任务池</h1>
        <p className="mt-1 text-sm text-slate-400">从 1200 个预设多轮对话任务中选择并领取</p>
      </div>

      <div className="card flex flex-wrap gap-3">
        <select className="select max-w-xs" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">全部状态</option>
          <option value="available">可领取</option>
          <option value="claimed">制作中</option>
          <option value="passed">已完成</option>
        </select>
        <select className="select max-w-xs" value={sceneFilter} onChange={(e) => setSceneFilter(e.target.value)}>
          <option value="">全部场景</option>
          {scenes.map((scene) => (
            <option key={scene} value={scene}>
              {scene}
            </option>
          ))}
        </select>
      </div>

      {message && <div className="rounded-xl bg-cyan-500/10 px-3 py-2 text-sm text-cyan-200">{message}</div>}

      <div className="space-y-3">
        {tasks.map((task) => (
          <div key={task.id} className="card flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">#{task.id}</span>
                <StatusBadge status={task.status} />
                <span className="text-sm text-slate-400">{task.scene_label}</span>
              </div>
              <div className="mt-2 text-lg">{task.topic}</div>
              <div className="mt-1 text-sm text-slate-500">
                {task.turn_count} 轮提问
                {task.claimed_by ? ` · 领取人：${task.claimed_by}` : ""}
              </div>
            </div>
            <div className="flex gap-2">
              <Link className="btn btn-secondary" to={`/tasks/${task.id}`}>
                查看详情
              </Link>
              {task.status === "available" && (
                <button className="btn btn-primary" onClick={() => onClaim(task.id)}>
                  领取
                </button>
              )}
            </div>
          </div>
        ))}
        {tasks.length === 0 && <div className="card text-slate-400">暂无任务，请管理员导入题目</div>}
      </div>
    </div>
  );
}
