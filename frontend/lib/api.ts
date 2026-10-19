/**
 * API Client for InterviewIQ Backend
 * Exact contract match with backend/schemas.py
 */

export type Mode = "A" | "B" | "C" | "D" | "E";
export type Difficulty = "easy" | "medium" | "hard";

export interface Persona {
  role: string;
  tone: string;
  difficulty: Difficulty;
  voice: string;
}

export interface SessionConfig {
  mode: Mode;
  topic: string;
  custom_questions: string[];
  file_namespace: string;
  persona: Persona;
  num_questions: number;
  /** Turn-based voice runs over the text socket; the backend needs the flag to
   *  honour "voice mode never probes" and to count every answer as a round. */
  voice_mode?: boolean;
}

export interface Report {
  session_id: string;
  per_question: number[];
  overall: number;
  strengths: string;
  gaps: string;
  study_next: string;
  verdict: string;
  verdict_why: string;
  adjustment: string;
}

export interface CreateSessionResponse {
  session_id: string;
  user_id: string;
}

export interface UploadResponse {
  file: string;
  chars: number;
  chunks: number;
  namespace: string;
}

export interface PastSession {
  session_id: string;
  mode: string;
  topic: string;
  rounds: number;
  overall: number;
  created_at: string;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Firebase ID token when logged in; {} when logged out (backend falls back
// to the shared dev identity — old behavior, unchanged).
async function authHeaders(): Promise<Record<string, string>> {
  try {
    const { getIdToken } = await import("./firebase");
    const token = await getIdToken();
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

/** Error carrying the HTTP status, so callers can tell "not yours" (404) and
 * "not signed in" (401) apart from a real outage. */
export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function getReport(sessionId: string): Promise<Report> {
  const res = await fetch(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/report`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
      ...(await authHeaders()),
    },
  });

  if (!res.ok) {
    const errorBody = await res.text();
    throw new ApiError(
      `Failed to load report (${res.status}): ${errorBody || res.statusText}`,
      res.status,
    );
  }

  return res.json();
}

export async function createSession(config: SessionConfig): Promise<CreateSessionResponse> {
  const res = await fetch(`${API_BASE}/sessions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(await authHeaders()),
    },
    body: JSON.stringify(config),
  });

  if (!res.ok) {
    const errorBody = await res.text();
    throw new Error(`Failed to create session (${res.status}): ${errorBody || res.statusText}`);
  }

  return res.json();
}

export async function uploadFile(file: File, namespace: string): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_BASE}/upload?namespace=${encodeURIComponent(namespace)}`, {
    method: "POST",
    headers: await authHeaders(),
    body: formData,
  });

  if (!res.ok) {
    const errorBody = await res.text();
    throw new Error(`Upload failed (${res.status}): ${errorBody || res.statusText}`);
  }

  return res.json();
}

export async function getSessions(): Promise<PastSession[]> {
  const res = await fetch(`${API_BASE}/sessions`, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
      ...(await authHeaders()),
    },
  });

  if (!res.ok) {
    const errorBody = await res.text();
    throw new Error(`Failed to load sessions (${res.status}): ${errorBody || res.statusText}`);
  }

  return res.json();
}

export async function deleteSession(sessionId: string): Promise<void> {
  const res = await fetch(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    headers: await authHeaders(),
  });

  if (!res.ok) {
    const errorBody = await res.text();
    throw new Error(`Failed to delete session (${res.status}): ${errorBody || res.statusText}`);
  }
}

export async function deleteAllSessions(): Promise<number> {
  const res = await fetch(`${API_BASE}/sessions`, {
    method: "DELETE",
    headers: await authHeaders(),
  });

  if (!res.ok) {
    const errorBody = await res.text();
    throw new Error(`Failed to delete sessions (${res.status}): ${errorBody || res.statusText}`);
  }

  const data = await res.json();
  return typeof data.deleted_count === "number" ? data.deleted_count : 0;
}
