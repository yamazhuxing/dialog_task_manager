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
  sortNumeric = false,
}: {
  title: string;
  data: Record<string, number>;
  ok?: boolean;
  hint?: string;
  sortNumeric?: boolean;
}) {
  const entries = Object.entries(data);
  const sortedEntries = sortNumeric
    ? [...entries].sort(([a], [b]) => Number(a) - Number(b))
    : entries;
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
        {sortedEntries.map(([key, value]) => (
          <div key={key} className={value === 0 ? "opacity-50" : undefined}>
            <div className="mb-1 flex justify-between text-sm">
              <span>{sortNumeric ? `${key} 轮` : key}</span>
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

  const sceneRangeLabel =
    stats.scene_range_ratio != null ? `${stats.scene_range_ratio}` : "—";
  const sceneRangeHint =
    stats.scene_range_ratio != null
      ? `单类最少 ${stats.scene_min_count} 条、最多 ${stats.scene_max_count} 条；极差比 max÷min = ${stats.scene_range_ratio}（要求 < 5）`
      : `单类最少 ${stats.scene_min_count} 条、最多 ${stats.scene_max_count} 条；极差比待计算（13 类均需至少 1 条后才算 max÷min）`;

  const assistantTurnsHint =
    stats.assistant_turns_known_count > 0
      ? `已统计 ${stats.assistant_turns_known_count}/${stats.passed_count} 条通过样本；平均 ${stats.assistant_turns_avg} 轮，最少 ${stats.assistant_turns_min} 轮，最多 ${stats.assistant_turns_max} 轮（验收标准 ≥ 5）`
      : "暂无通过样本的轮次数据（新入库样本会自动统计）";

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
          title="场景覆盖 / 极差比"
          value={`已覆盖 ${stats.scene_covered_count}/${stats.scene_total_count} 类 · 极差 ${sceneRangeLabel}`}
          hint={sceneRangeHint}
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
          hint={`已覆盖 ${stats.scene_covered_count}/${stats.scene_total_count} 类；极差比 max÷min ${stats.scene_range_ratio != null ? `= ${stats.scene_range_ratio}（< 5 达标）` : "待计算（每类需 ≥1 条）"}`}
        />
        <DistributionCard title="难度分布" data={stats.difficulty_distribution} />
        <DistributionCard
          title="Assistant 轮次分布（通过样本）"
          data={stats.assistant_turns_distribution}
          sortNumeric
          hint={assistantTurnsHint}
        />
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
