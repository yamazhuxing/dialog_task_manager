import React, { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { TaskItem, fetchTasks } from "../api/client";

export function MyTasksPage() {
  const [tasks, setTasks] = useState<TaskItem[]>([]);

  useEffect(() => {
    fetchTasks({ mine: true } as Record<string, boolean>).then(setTasks).catch(console.error);
  }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">我的任务</h1>
        <p className="mt-1 text-sm text-slate-400">查看已领取任务并进入提交页面</p>
      </div>
      <div className="space-y-3">
        {tasks.map((task) => (
          <div key={task.id} className="card flex items-center justify-between">
            <div>
              <div className="font-medium">
                #{task.id} {task.topic}
              </div>
              <div className="mt-1 text-sm text-slate-400">
                {task.scene_label} · {task.status === "passed" ? "已通过" : "制作中"}
              </div>
            </div>
            <Link className="btn btn-primary" to={`/tasks/${task.id}`}>
              进入
            </Link>
          </div>
        ))}
        {tasks.length === 0 && <div className="card text-slate-400">你还没有领取任务</div>}
      </div>
    </div>
  );
}
