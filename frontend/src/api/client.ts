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
  claimed_at: string | null;
  passed_at: string | null;
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
  assistant_turns_distribution: Record<string, number>;
  assistant_turns_buckets: Record<string, number>;
  assistant_turns_min: number | null;
  assistant_turns_max: number | null;
  assistant_turns_avg: number | null;
  assistant_turns_sample_count: number;
  assistant_turns_missing_count: number;
  thinking_effort_distribution: Record<string, number>;
  thinking_ratio_ok: boolean;
  thinking_range_ratio: number | null;
  thinking_effort_sample_count: number;
  thinking_effort_missing_count: number;
  invalid_thinking_effort_count: number;
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

export interface ProcessingLogItem {
  step: string;
  label?: string | null;
  message?: string | null;
  status?: string | null;
  at?: string | null;
}

export interface QCHintItem {
  error: string;
  essence: string;
  remedy: string;
}

export interface Submission {
  id: number;
  task_id: number;
  status: string;
  source_type: string;
  model_version: string | null;
  session_id: string | null;
  detected_model: string | null;
  difficulty: string | null;
  error_message: string | null;
  processing_step: string | null;
  processing_log: ProcessingLogItem[];
  qc_errors: string[];
  qc_hints: QCHintItem[];
  qc_stats: Record<string, string>;
  created_at: string;
}

export async function uploadTaskFile(taskId: number, file: File, sourceType: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("source_type", sourceType);
  const { data } = await api.post<Submission>(`/tasks/${taskId}/upload`, form);
  return data;
}

export async function fetchSubmissions(taskId: number) {
  const { data } = await api.get<Submission[]>(`/tasks/${taskId}/submissions`);
  return data;
}

export async function fetchSubmission(id: number) {
  const { data } = await api.get<Submission>(`/submissions/${id}`);
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

export interface InvalidDifficultySample {
  task_id: number;
  session_id: string;
  username: string;
  topic: string;
  difficulty: string | null;
  passed_at: string | null;
}

export async function fetchDifficultyRepairs() {
  const { data } = await api.get<InvalidDifficultySample[]>("/admin/difficulty-repairs");
  return data;
}

export async function retryTaskDifficulty(taskId: number) {
  const { data } = await api.post(`/tasks/${taskId}/retry-difficulty`);
  return data;
}

export interface ZipQcSessionResult {
  source_type: string;
  session_id: string;
  status: string;
  errors: string[];
  thinking_effort: string | null;
  assistant_turns: number | null;
  difficulty: string | null;
  scene: string | null;
}

export interface ZipQcResponse {
  filename: string;
  total: number;
  pass_count: number;
  fail_count: number;
  error_count: number;
  structure_warnings: string[];
  sessions: ZipQcSessionResult[];
}

export type ZipQcProgressEvent =
  | { type: "upload"; percent: number }
  | { type: "phase"; phase: string; message: string; total?: number }
  | { type: "session"; current: number; total: number; session: ZipQcSessionResult }
  | { type: "result"; result: ZipQcResponse }
  | { type: "error"; detail: string };

export function qcExternalZip(
  file: File,
  onEvent: (event: ZipQcProgressEvent) => void,
): Promise<ZipQcResponse> {
  return new Promise((resolve, reject) => {
    const token = getToken();
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/admin/qc-zip");
    if (token) {
      xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    }
    xhr.timeout = 30 * 60 * 1000;

    xhr.upload.onprogress = (ev) => {
      if (!ev.lengthComputable) return;
      onEvent({
        type: "upload",
        percent: Math.min(100, Math.round((ev.loaded / ev.total) * 100)),
      });
    };

    xhr.upload.onload = () => {
      onEvent({ type: "upload", percent: 100 });
    };

    let settled = false;
    let finalResult: ZipQcResponse | null = null;
    let processedLen = 0;

    const handleLine = (line: string) => {
      const text = line.trim();
      if (!text) return;
      let event: Record<string, unknown>;
      try {
        event = JSON.parse(text) as Record<string, unknown>;
      } catch {
        return;
      }
      const eventType = event.type;
      if (eventType === "phase") {
        onEvent({
          type: "phase",
          phase: String(event.phase || ""),
          message: String(event.message || ""),
          total: typeof event.total === "number" ? event.total : undefined,
        });
      } else if (eventType === "session") {
        onEvent({
          type: "session",
          current: Number(event.current || 0),
          total: Number(event.total || 0),
          session: event.session as ZipQcSessionResult,
        });
      } else if (eventType === "result") {
        finalResult = event.result as ZipQcResponse;
        onEvent({ type: "result", result: finalResult });
      } else if (eventType === "error") {
        const detail = String(event.detail || "质检失败");
        onEvent({ type: "error", detail });
        if (!settled) {
          settled = true;
          reject(new Error(detail));
        }
      }
    };

    const consume = () => {
      const text = xhr.responseText;
      const pending = text.slice(processedLen);
      const parts = pending.split("\n");
      const completeCount = pending.endsWith("\n") ? parts.length : Math.max(0, parts.length - 1);
      for (let i = 0; i < completeCount; i += 1) {
        handleLine(parts[i]);
        processedLen += parts[i].length + 1;
      }
    };

    xhr.onreadystatechange = () => {
      if (xhr.readyState === XMLHttpRequest.LOADING || xhr.readyState === XMLHttpRequest.DONE) {
        consume();
      }
    };

    xhr.onload = () => {
      consume();
      if (settled) return;
      if (xhr.status >= 400) {
        settled = true;
        let detail = `上传/质检失败（HTTP ${xhr.status}）`;
        try {
          const data = JSON.parse(xhr.responseText) as { detail?: string };
          if (data.detail) detail = data.detail;
        } catch {
          // ignore
        }
        reject(new Error(detail));
        return;
      }
      if (!finalResult) {
        settled = true;
        reject(new Error("质检未返回完整结果"));
        return;
      }
      settled = true;
      resolve(finalResult);
    };

    xhr.onerror = () => {
      if (!settled) {
        settled = true;
        reject(new Error("网络错误，ZIP 质检中断"));
      }
    };

    xhr.ontimeout = () => {
      if (!settled) {
        settled = true;
        reject(new Error("质检超时，请缩小 ZIP 后重试"));
      }
    };

    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}
