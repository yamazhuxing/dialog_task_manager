import React from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";

const navItems = [
  { to: "/", label: "看板" },
  { to: "/tasks", label: "任务池" },
  { to: "/my-tasks", label: "我的任务" },
];

export function Layout() {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  return (
    <div className="min-h-screen lg:flex">
      <aside className="border-b border-white/10 bg-black/20 lg:min-h-screen lg:w-64 lg:border-b-0 lg:border-r">
        <div className="p-6">
          <div className="text-lg font-semibold text-cyan-300">样本制作平台</div>
          <div className="mt-1 text-sm text-slate-400">多轮对话样本协作管理</div>
        </div>
        <nav className="flex gap-2 overflow-x-auto px-4 pb-4 lg:flex-col lg:px-3">
          {navItems.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className={`rounded-xl px-4 py-2 text-sm ${
                location.pathname === item.to
                  ? "bg-cyan-500/20 text-cyan-200"
                  : "text-slate-300 hover:bg-white/5"
              }`}
            >
              {item.label}
            </Link>
          ))}
          {user?.role === "admin" && (
            <Link
              to="/admin"
              className={`rounded-xl px-4 py-2 text-sm ${
                location.pathname === "/admin"
                  ? "bg-cyan-500/20 text-cyan-200"
                  : "text-slate-300 hover:bg-white/5"
              }`}
            >
              管理
            </Link>
          )}
        </nav>
        <div className="mt-auto hidden border-t border-white/10 p-4 lg:block">
          <div className="text-sm text-slate-300">{user?.username}</div>
          <div className="text-xs text-slate-500">{user?.role === "admin" ? "管理员" : "制作员"}</div>
          <button
            className="btn btn-secondary mt-3 w-full"
            onClick={() => {
              logout();
              navigate("/login");
            }}
          >
            退出登录
          </button>
        </div>
      </aside>
      <main className="flex-1 p-4 lg:p-8">
        <Outlet />
      </main>
    </div>
  );
}
