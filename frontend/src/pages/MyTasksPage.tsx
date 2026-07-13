import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { TaskItem, fetchTasks } from "../api/client";

function parseApiDateTime(value: string) {
  const normalized = /[zZ]|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`;
  return new Date(normalized);
}

function formatDateTime(value: string | null) {
  if (!value) return null;
  return parseApiDateTime(value).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Asia/Shanghai",
  });
}

function StatusBadge({ status }: { status: string }) {
  const cls = status === "claimed" ? "badge-claimed" : "badge-passed";
  const label = status === "claimed" ? "制作中" : "已通过";
  return <span className={`badge ${cls}`}>{label}</span>;
}

function StatCard({ title, value, hint }: { title: string; value: number; hint?: string }) {
  return (
    <div className="card">
      <div className="text-sm text-slate-400">{title}</div>
      <div className="mt-2 text-2xl font-semibold text-cyan-300">{value}</div>
      {hint && <div className="mt-2 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

export function MyTasksPage() {
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [statusFilter, setStatusFilter] = useState("");

  const load = () => {
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
  };

  useEffect(() => {
    load();
  }, []);

  const stats = useMemo(
    () => ({
      total: tasks.length,
      inProgress: tasks.filter((task) => task.status === "claimed").length,
      passed: tasks.filter((task) => task.status === "passed").length,
    }),
    [tasks],
  );

  const filteredTasks = useMemo(() => {
    if (!statusFilter) return tasks;
    return tasks.filter((task) => task.status === statusFilter);
  }, [tasks, statusFilter]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">我的任务</h1>
        <p className="mt-1 text-sm text-slate-400">查看已领取任务、统计进度并进入提交页面</p>
      </div>

      {error && <div className="rounded-xl bg-rose-500/10 px-3 py-2 text-sm text-rose-200">{error}</div>}

      {!loading && !error && (
        <div className="grid gap-3 sm:grid-cols-3">
          <StatCard title="全部任务" value={stats.total} hint="当前占用或已完成" />
          <StatCard title="制作中" value={stats.inProgress} hint="已领取，待通过质检" />
          <StatCard title="已通过" value={stats.passed} hint="样本已入库" />
        </div>
      )}

      <div className="card flex flex-wrap items-center gap-3">
        <label className="text-sm text-slate-400" htmlFor="my-task-status-filter">
          任务状态
        </label>
        <select
          id="my-task-status-filter"
          className="select max-w-xs"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          disabled={loading}
        >
          <option value="">全部</option>
          <option value="claimed">制作中</option>
          <option value="passed">已通过</option>
        </select>
        {!loading && statusFilter && (
          <span className="text-sm text-slate-500">共 {filteredTasks.length} 条</span>
        )}
      </div>

      <div className="space-y-3">
        {loading && <div className="card text-slate-400">加载中...</div>}
        {!loading &&
          filteredTasks.map((task) => (
            <div key={task.id} className="card flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">#{task.id}</span>
                  <StatusBadge status={task.status} />
                </div>
                <div className="mt-1 truncate font-medium">{task.topic}</div>
                <div className="mt-1 text-sm text-slate-400">
                  {task.scene_label}
                  {task.claimed_at && ` · 领取于 ${formatDateTime(task.claimed_at)}`}
                  {task.status === "passed" && task.passed_at && ` · 通过于 ${formatDateTime(task.passed_at)}`}
                </div>
              </div>
              <Link className="btn btn-primary shrink-0" to={`/tasks/${task.id}`}>
                进入
              </Link>
            </div>
          ))}
        {!loading && !error && tasks.length === 0 && (
          <div className="card text-slate-400">你还没有领取任务</div>
        )}
        {!loading && !error && tasks.length > 0 && filteredTasks.length === 0 && (
          <div className="card text-slate-400">当前筛选条件下暂无任务</div>
        )}
      </div>
    </div>
  );
}
