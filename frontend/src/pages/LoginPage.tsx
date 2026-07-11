import React, { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login } from "../api/client";
import { useAuth } from "../contexts/AuthContext";

export function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const { refresh } = useAuth();
  const navigate = useNavigate();

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      await login(username, password);
      await refresh();
      navigate("/");
    } catch {
      setError("登录失败，请检查用户名和密码");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <form onSubmit={onSubmit} className="card w-full max-w-md space-y-4">
        <div>
          <h1 className="text-2xl font-semibold">样本制作任务管理系统</h1>
          <p className="mt-2 text-sm text-slate-400">登录后开始领取任务并提交样本</p>
        </div>
        {error && <div className="rounded-xl bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</div>}
        <div>
          <label className="mb-1 block text-sm text-slate-400">用户名</label>
          <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} />
        </div>
        <div>
          <label className="mb-1 block text-sm text-slate-400">密码</label>
          <input
            className="input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <button className="btn btn-primary w-full" disabled={loading}>
          {loading ? "登录中..." : "登录"}
        </button>
      </form>
    </div>
  );
}
