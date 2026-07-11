import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { DashboardStats, fetchDashboard } from "../api/client";

function StatCard({
  title,
  value,
  hint,
  compact = false,
}: {
  title: string;
  value: string | number;
  hint?: string;
  compact?: boolean;
}) {
  return (
    <div className="card">
      <div className="text-sm text-slate-400">{title}</div>
      <div
        className={
          compact
            ? "mt-2 text-lg font-medium leading-snug text-cyan-300"
            : "mt-2 text-2xl font-semibold text-cyan-300"
        }
      >
        {value}
      </div>
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

function AssistantTurnsPanel({ stats }: { stats: DashboardStats }) {
  const total = stats.assistant_turns_sample_count;
  const buckets = Object.entries(stats.assistant_turns_buckets);
  const exactEntries = Object.entries(stats.assistant_turns_distribution).sort(
    ([a], [b]) => Number(a) - Number(b),
  );

  const summary =
    total > 0 && stats.assistant_turns_avg != null
      ? `${total} 条通过样本 · 平均 ${stats.assistant_turns_avg} 轮 · 范围 ${stats.assistant_turns_min}–${stats.assistant_turns_max} 轮`
      : "暂无轮次数据";

  const detailText =
    exactEntries.length > 0
      ? `明细：${exactEntries.map(([turns, count]) => `${turns} 轮×${count}`).join("，")}`
      : "";

  return (
    <div className="card xl:col-span-2">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="font-medium">Assistant 轮次（通过样本）</div>
          <div className="mt-1 text-xs text-slate-500">
            统计每条样本中 assistant 回复轮数；甲方验收要求 ≥ 5 轮
          </div>
        </div>
        {total > 0 &&
          stats.assistant_turns_min != null &&
          stats.assistant_turns_min >= 5 &&
          stats.assistant_turns_missing_count === 0 && (
          <span className="badge badge-passed">全部 ≥ 5</span>
        )}
      </div>
      <div className="mt-3 text-sm text-cyan-200">{summary}</div>
      {stats.assistant_turns_missing_count > 0 && (
        <div className="mt-2 text-xs text-amber-300">
          另有 {stats.assistant_turns_missing_count} 条样本未能读取轮次（请检查样本目录是否完整）
        </div>
      )}
      <div className="mt-4 space-y-2">
        {total === 0 && <div className="text-sm text-slate-500">暂无数据</div>}
        {buckets.map(([label, value]) => (
          <div key={label} className={value === 0 ? "opacity-50" : undefined}>
            <div className="mb-1 flex justify-between text-sm">
              <span>{label}</span>
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
      {detailText && <div className="mt-3 text-xs text-slate-500">{detailText}</div>}
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

  const assistantTurnsValue =
    stats.assistant_turns_avg != null
      ? `平均 ${stats.assistant_turns_avg} 轮`
      : "—";
  const assistantTurnsHint =
    stats.assistant_turns_sample_count > 0
      ? `${stats.assistant_turns_sample_count} 条样本，范围 ${stats.assistant_turns_min}–${stats.assistant_turns_max} 轮（验收 ≥ 5）`
      : "通过样本入库后自动统计";

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">验收指标看板</h1>
        <p className="mt-1 text-sm text-slate-400">实时跟踪已通过样本与甲方验收比例</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-5">
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
          compact
        />
        <StatCard title="Assistant 轮次" value={assistantTurnsValue} hint={assistantTurnsHint} compact />
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
        <AssistantTurnsPanel stats={stats} />
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
