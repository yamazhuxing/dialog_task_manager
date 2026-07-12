import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { TaskItem, fetchTasks } from "../api/client";

function formatDateTime(value: string | null) {
  if (!value) return null;
  return new Date(value).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function MyTasksPage() {
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    setError("");
    fetchTasks({ mine: true } as Record<string, boolean>)
      .then(setTasks)
      .catch((err: unknown) => {
        const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        setError(typeof msg === "string" ? msg : "加载任务失败，请刷新重试");
        setTasks([]);
      })
      .finally(() => setLoading(false));
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">我的任务</h1>
        <p className="mt-1 text-sm text-slate-400">查看已领取任务并进入提交页面</p>
      </div>
      {error && <div className="rounded-xl bg-rose-500/10 px-3 py-2 text-sm text-rose-200">{error}</div>}

      <div className="space-y-3">
        {loading && <div className="card text-slate-400">加载中...</div>}
        {!loading &&
          tasks.map((task) => (
          <div key={task.id} className="card flex items-center justify-between">
            <div>
              <div className="font-medium">
                #{task.id} {task.topic}
              </div>
              <div className="mt-1 text-sm text-slate-400">
                {task.scene_label} · {task.status === "passed" ? "已通过" : "制作中"}
                {task.claimed_at && ` · 领取于 ${formatDateTime(task.claimed_at)}`}
                {task.status === "passed" && task.passed_at && ` · 通过于 ${formatDateTime(task.passed_at)}`}
              </div>
            </div>
            <Link className="btn btn-primary" to={`/tasks/${task.id}`}>
              进入
            </Link>
          </div>
        ))}
        {!loading && !error && tasks.length === 0 && (
          <div className="card text-slate-400">你还没有领取任务</div>
        )}
      </div>
    </div>
  );
}
