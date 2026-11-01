// The shapes the backend sends (see API.md).

export type Mashups = "components" | "original" | "both";

export interface Login {
  source: "app" | "mixxx" | "none";
  username: string | null;
  path: string | null;
}

export interface SockseekStatus {
  path: string | null;
  source: "setting" | "automatic" | "bundled" | null;
  setting: string;
  found: boolean;
  error: string | null;
}

export interface AppState {
  app: { name: string; version: string };
  settings: { music_dir: string; sockseek: string; mashups: Mashups };
  music_dir: { path: string; exists: boolean };
  login: Login;
  sockseek: SockseekStatus;
  jobs: { running: number; queued: number };
  limits: { page_bytes: number; text_bytes: number; upload_bytes: number; query_chars: number };
}

export type TrackKind = "track" | "with" | "mashup" | "component";

export interface DraftTrack {
  row: number;
  number: string;
  kind: TrackKind;
  artist: string;
  title: string;
  display: string;
  label: string;
  duration: number | null;
  cue: number | null;
  unidentified: boolean;
  mashup_of: number | null;
  downloads: Record<Mashups, boolean>;
}

export interface Draft {
  id: string;
  source: "page" | "text";
  file: string;
  title: string;
  url: string;
  set: string;
  set_exists: boolean;
  mashups: Mashups;
  has_mashups: boolean;
  unidentified: number;
  counts: Record<Mashups, number>;
  tracks: DraftTrack[];
}

export interface SetSummary {
  id: string;
  name: string;
  title: string;
  url: string;
  source: "page" | "text";
  folder: string;
  m3u: string;
  mashups: Mashups;
  downloaded: boolean;
  found: number;
  missing: number;
  total: number;
  error: string | null;
  updated: string;
  updated_ts: number;
  busy: "running" | "queued" | null;
  pending: boolean;
}

export interface TrackFix {
  query?: string;
  file?: string;
  source?: "soulseek" | "own";
  link?: string;
  updated?: string;
}

export interface Track {
  row: number;
  number: string;
  kind: TrackKind;
  artist: string;
  title: string;
  display: string;
  label: string;
  duration: number | null;
  cue: number | null;
  unidentified: boolean;
  selectable: boolean;
  key: string;
  search: string;
  identity: string;
  status: "found" | "missing" | "skipped";
  retry_query: string;
  reason: string;
  file: string;
  fix: TrackFix | null;
  fix_in_use: boolean;
}

export interface TracksResponse {
  set: string;
  folder: string;
  title: string;
  mashups: Mashups;
  found: number;
  missing: number;
  tracks: Track[];
}

export interface SearchResult {
  user: string;
  path: string;
  name: string;
  format: string;
  size: number;
  length: number;
  bitrate: number;
  samplerate: number;
  bitdepth: number;
  free_slot: boolean;
  speed: number;
  link: string;
}

export interface SetResult {
  set: string;
  title: string;
  found: number;
  missing: number;
  total: number;
  cancelled: boolean;
  errors: string[];
  missing_tracks: { number: string; artist: string; title: string; reason: string }[];
}

export interface SearchJobResult {
  query: string;
  results: SearchResult[];
}

export type JobState = "queued" | "running" | "stopping" | "done" | "failed" | "stopped";

export interface Job {
  id: string;
  kind: "download" | "search" | "fix";
  title: string;
  set: string | null;
  row: number | null;
  state: JobState;
  waiting: "soulseek" | "set" | null;
  ahead: number | null;
  created: string;
  started: string | null;
  finished: string | null;
  exit_code: number | null;
  message: string;
  error: string;
  result: SetResult | SearchJobResult | null;
  log_lines: number;
  log?: string[];
}

export interface Upload {
  id: string;
  name: string;
  size: number;
}

export const ACTIVE_STATES: JobState[] = ["queued", "running", "stopping"];

export function isActive(job: Pick<Job, "state">): boolean {
  return ACTIVE_STATES.includes(job.state);
}
