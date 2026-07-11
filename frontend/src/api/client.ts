import axios from "axios";

const TOKEN_KEY = "mss_token";

export const api = axios.create({
  baseURL: "/api",
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export interface UserInfo {
  id: number;
  username: string;
  role: string;
}

export interface TaskItem {
  id: number;
  scene: string;
  scene_label: string;
  topic: string;
  status: string;
  claimed_by: string | null;
  source_type: string | null;
  model_version: string | null;
  turn_count: number;
}

export interface TaskDetail extends TaskItem {
  constraint_text: string | null;
  turns: { round: number; role: string; content: string }[];
  latest_submission_status: string | null;
  latest_submission_error: string | null;
}

export interface DashboardStats {
  passed_count: number;
  target_count: number;
  claimed_count: number;
  available_count: number;
  source_distribution: Record<string, number>;
  model_distribution: Record<string, number>;
  scene_distribution: Record<string, number>;
  difficulty_distribution: Record<string, number>;
  source_ratio_ok: boolean;
  model_ratio_ok: boolean;
  scene_ratio_ok: boolean;
  scene_min_count: number;
  scene_max_count: number;
  scene_covered_count: number;
  scene_total_count: number;
  scene_range_ratio: number | null;
}

export async function login(username: string, password: string) {
  const { data } = await api.post("/auth/login", { username, password });
  setToken(data.access_token);
  return data;
}

export async function fetchMe() {
  const { data } = await api.get<UserInfo>("/auth/me");
  return data;
}

export async function fetchTasks(params?: Record<string, string | boolean>) {
  const { data } = await api.get<TaskItem[]>("/tasks", { params });
  return data;
}

export async function fetchTask(id: number) {
  const { data } = await api.get<TaskDetail>(`/tasks/${id}`);
  return data;
}

export async function claimTask(id: number) {
  const { data } = await api.post<TaskDetail>(`/tasks/${id}/claim`);
  return data;
}

export async function releaseTask(id: number) {
  const { data } = await api.post<TaskDetail>(`/tasks/${id}/release`);
  return data;
}

export async function fetchDashboard() {
  const { data } = await api.get<DashboardStats>("/stats/dashboard");
  return data;
}

export async function uploadTaskFile(
  taskId: number,
  file: File,
  sourceType: string,
  modelVersion: string,
) {
  const form = new FormData();
  form.append("file", file);
  form.append("source_type", sourceType);
  form.append("model_version", modelVersion);
  const { data } = await api.post(`/tasks/${taskId}/upload`, form);
  return data;
}

export async function fetchSubmissions(taskId: number) {
  const { data } = await api.get(`/tasks/${taskId}/submissions`);
  return data;
}

export async function fetchSubmission(id: number) {
  const { data } = await api.get(`/submissions/${id}`);
  return data;
}

export async function createUser(username: string, password: string, role = "user") {
  const { data } = await api.post("/auth/users", { username, password, role });
  return data;
}

export async function importDefaultQuestions() {
  const { data } = await api.post("/questions/import-default");
  return data;
}

export async function importQuestionsFile(file: File) {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post("/questions/import", form);
  return data;
}

export async function fetchUserStats() {
  const { data } = await api.get("/stats/users");
  return data;
}

export interface SceneOption {
  value: string;
  label: string;
}

export async function fetchScenes() {
  const { data } = await api.get<SceneOption[]>("/scenes");
  return data;
}

export async function createTask(payload: {
  scene: string;
  topic: string;
  constraint_text?: string;
  turns: { content: string }[];
}) {
  const { data } = await api.post("/tasks", payload);
  return data;
}

export async function deleteTask(taskId: number) {
  const { data } = await api.delete(`/tasks/${taskId}`);
  return data;
}

export async function backfillSampleMetadata() {
  const { data } = await api.post("/samples/backfill-metadata");
  return data as { backfilled_count: number };
}
