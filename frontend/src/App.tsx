import React from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { AuthProvider, useAuth } from "./contexts/AuthContext";
import { AdminPage } from "./pages/AdminPage";
import { DashboardPage } from "./pages/DashboardPage";
import { LoginPage } from "./pages/LoginPage";
import { MyTasksPage } from "./pages/MyTasksPage";
import { TaskDetailPage } from "./pages/TaskDetailPage";
import { TasksPage } from "./pages/TasksPage";

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="p-8">加载中...</div>;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  if (user?.role !== "admin") return <Navigate to="/" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route path="/" element={<DashboardPage />} />
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/tasks/:id" element={<TaskDetailPage />} />
          <Route path="/my-tasks" element={<MyTasksPage />} />
          <Route
            path="/admin"
            element={
              <AdminRoute>
                <AdminPage />
              </AdminRoute>
            }
          />
        </Route>
      </Routes>
    </AuthProvider>
  );
}
