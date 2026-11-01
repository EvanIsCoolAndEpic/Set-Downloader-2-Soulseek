// The JSON API client. Every /api call carries this launch's token (see API.md, "The token").

import type {
  AppState,
  Draft,
  Job,
  Login,
  Mashups,
  SetSummary,
  TracksResponse,
  Upload,
} from "./types";

const TOKEN_KEY = "setdl-token";

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

let token: string | null = null;

/** Reads the token from the address (#token=...), keeps it for reloads and removes it from the
 * address bar. */
export function initToken(): string | null {
  const fromHash = new URLSearchParams(location.hash.slice(1)).get("token");
  if (fromHash) {
    token = fromHash;
    try {
      sessionStorage.setItem(TOKEN_KEY, fromHash);
    } catch {
      // storage can be off: the token still works for this page
    }
    history.replaceState(null, "", location.pathname + location.search);
  } else {
    try {
      token = sessionStorage.getItem(TOKEN_KEY);
    } catch {
      token = null;
    }
  }
  return token;
}

export function getToken(): string | null {
  return token;
}

/** For tests. */
export function setToken(value: string | null): void {
  token = value;
}

export function authHeaders(): Record<string, string> {
  return token ? { "X-SetDL-Token": token } : {};
}

const OFFLINE = "Can't reach Set Downloader. Check that it's still running.";

export async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  init: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = { ...authHeaders() };
  let payload: BodyInit | undefined;
  if (body instanceof Blob) {
    payload = body;
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  let res: Response;
  try {
    res = await fetch(path, { method, headers, body: payload, ...init });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(0, "network", OFFLINE);
  }
  let data: unknown = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    const err = (data as { error?: { code?: string; message?: string } } | null)?.error;
    throw new ApiError(
      res.status,
      err?.code ?? "http_" + res.status,
      err?.message ?? `Set Downloader answered with an error (${res.status}).`,
    );
  }
  return data as T;
}

const enc = encodeURIComponent;

export const api = {
  state: () => request<AppState>("GET", "/api/state"),
  saveSettings: (changes: Partial<AppState["settings"]>) =>
    request<AppState>("PUT", "/api/settings", changes),
  saveLogin: (username: string, password: string) =>
    request<{ login: Login }>("PUT", "/api/login", { username, password }),
  forgetLogin: () => request<{ login: Login }>("DELETE", "/api/login"),

  draftFromFile: (file: File) =>
    request<Draft>("POST", `/api/drafts/page?name=${enc(file.name)}`, file),
  draftFromText: (text: string) => request<Draft>("POST", "/api/drafts/text", { text }),
  draft: (id: string) => request<Draft>("GET", `/api/drafts/${enc(id)}`),
  deleteDraft: (id: string) => request<{ ok: true }>("DELETE", `/api/drafts/${enc(id)}`),

  downloadDraft: (draft: string, mashups: Mashups) =>
    request<{ job: Job; already_queued: boolean }>("POST", "/api/downloads", { draft, mashups }),
  retrySet: (set: string) =>
    request<{ job: Job; already_queued: boolean }>("POST", "/api/downloads", { set }),

  sets: () => request<{ music_dir: string; sets: SetSummary[] }>("GET", "/api/sets"),
  tracks: (set: string, signal?: AbortSignal) =>
    request<TracksResponse>("GET", `/api/sets/${enc(set)}/tracks`, undefined, { signal }),
  fix: (
    set: string,
    row: number,
    body:
      | { identity: string; link: string; query: string }
      | { identity: string; query: string }
      | { identity: string; upload: string }
      | { identity: string; clear: true },
  ) => request<{ job: Job }>("POST", `/api/sets/${enc(set)}/tracks/${row}/fix`, body),

  search: (query: string) => request<{ job: Job }>("POST", "/api/searches", { query }),
  upload: (file: File) =>
    request<{ upload: Upload }>("POST", `/api/uploads?name=${enc(file.name)}`, file),
  deleteUpload: (id: string) => request<{ ok: true }>("DELETE", `/api/uploads/${enc(id)}`),

  jobs: () => request<{ jobs: Job[] }>("GET", "/api/jobs"),
  job: (id: string) => request<Job>("GET", `/api/jobs/${enc(id)}`),
  stopJob: (id: string) => request<{ job: Job }>("POST", `/api/jobs/${enc(id)}/stop`),

  reveal: (target: { set: string } | { path: string } | Record<string, never>) =>
    request<{ ok: true; path: string }>("POST", "/api/reveal", target),
  openUrl: (url: string) => request<{ ok: true }>("POST", "/api/open-url", { url }),
};

/** A message for any error, in plain words. */
export function errorText(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "Something went wrong.";
}
