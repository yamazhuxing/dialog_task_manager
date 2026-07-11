import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { DashboardStats, fetchDashboard } from "../api/client";

function StatCard({ title, value, hint }: { title: string; value: string | number; hint?: string }) {
  return (
    <div className="card">
      <div className="text-sm text-slate-400">{title}</div>
      <div className="mt-2 text-3xl font-semibold text-cyan-300">{value}</div>
      {hint && <div className="mt-2 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

function DistributionCard({
  title,
  data,
  ok,
  hint,
}: {
  title: string;
  data: Record<string, number>;
  ok?: boolean;
  hint?: string;
}) {
  const entries = Object.entries(data);
  const total = entries.reduce((sum, [, v]) => sum + v, 0);
  const showStatus = ok !== undefined && total > 0;
  return (
    <div className="card">
      <div className="flex items-center justify-between">
        <div className="font-medium">{title}</div>
        {showStatus && (
          <span className={`badge ${ok ? "badge-passed" : "bg-red-500/20 text-red-300"}`}>
            {ok ? "达标" : "待调整"}
          </span>
        )}
      </div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
      <div className="mt-4 space-y-2">
        {entries.length === 0 && <div className="text-sm text-slate-500">暂无数据</div>}
        {entries.map(([key, value]) => (
          <div key={key} className={value === 0 ? "opacity-50" : undefined}>
            <div className="mb-1 flex justify-between text-sm">
              <span>{key}</span>
              <span>
                {value} {total > 0 ? `(${((value / total) * 100).toFixed(1)}%)` : ""}
              </span>
            </div>
            <div className="h-2 rounded-full bg-white/10">
              <div
                className="h-2 rounded-full bg-cyan-500"
                style={{ width: total > 0 ? `${(value / total) * 100}%` : "0%" }}
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);

  useEffect(() => {
    fetchDashboard().then(setStats).catch(console.error);
  }, []);

  if (!stats) return <div>加载中...</div>;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">验收指标看板</h1>
        <p className="mt-1 text-sm text-slate-400">实时跟踪已通过样本与甲方验收比例</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="已通过样本"
          value={`${stats.passed_count} / ${stats.target_count}`}
          hint="1000 为参考目标，实际越多越好"
        />
        <StatCard title="可领取任务" value={stats.available_count} />
        <StatCard title="制作中任务" value={stats.claimed_count} />
        <StatCard
          title="场景覆盖 / 极差"
          value={`${stats.scene_covered_count}/${stats.scene_total_count} 类 · ${stats.scene_min_count}~${stats.scene_max_count}`}
          hint="13 类均需 ≥1 条，且最多/最少 < 5"
        />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <DistributionCard
          title="来源分布 (openclaw : hermes ≈ 6:4)"
          data={stats.source_distribution}
          ok={stats.source_ratio_ok}
          hint="达标：openclaw 占比 55%~65%（约 6:4）"
        />
        <DistributionCard
          title="模型分布 (opus 4.8 : 4.6 ≥ 7:3)"
          data={stats.model_distribution}
          ok={stats.model_ratio_ok}
          hint="达标：opus 4.8 占比 ≥ 70%"
        />
        <DistributionCard
          title="场景分布 (13 类)"
          data={stats.scene_distribution}
          ok={stats.scene_ratio_ok}
          hint={`已覆盖 ${stats.scene_covered_count}/${stats.scene_total_count} 类；达标：每类 ≥1 条且 max/min < 5`}
        />
        <DistributionCard title="难度分布" data={stats.difficulty_distribution} />
      </div>

      <div className="card">
        <div className="font-medium">快捷入口</div>
        <div className="mt-3 flex flex-wrap gap-3">
          <Link className="btn btn-primary" to="/tasks">
            去任务池领取
          </Link>
          <Link className="btn btn-secondary" to="/my-tasks">
            查看我的任务
          </Link>
        </div>
      </div>
    </div>
  );
}
