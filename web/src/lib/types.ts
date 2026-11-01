// The shapes the backend sends (see API.md).

export type Mashups = "components" | "original" | "both";
/** Where tracks come from, in the order they're tried. */
export type Source = "soulseek" | "youtube" | "mix";
export type Quality = "lossless" | "best" | "fast";
export type OutputFormat = "keep" | "flac" | "aiff" | "mp3" | "wav";
/** Where a track's file came from (a fix's source; a plain download is "soulseek"). */
export type FileSource = "soulseek" | "own" | "youtube" | "soundcloud" | "mix";

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

export interface Settings {
  music_dir: string;
  sockseek: string;
  mashups: Mashups;
  sources: Source[];
  quality: Quality;
  format: OutputFormat;
  tags: boolean;
}

export interface YtdlpStatus {
  version: string | null;
  source: "bundled" | "updated" | null;
  bundled: string | null;
  updated: string | null;
  updating: boolean;
  step: string;
  message: string;
  error: string;
  checked: string | null;
}

export interface AppState {
  app: { name: string; version: string };
  settings: Settings;
  music_dir: { path: string; exists: boolean };
  login: Login;
  sockseek: SockseekStatus;
  ytdlp: YtdlpStatus;
  jobs: { running: number; queued: number };
  limits: { page_bytes: number; text_bytes: number; upload_bytes: number; query_chars: number };
}

export type TrackKind = "track" | "with" | "mashup" | "component" | "album";

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

/** One of the tracklists resolve found (a video's description, chapters, each comment...). */
export interface Alternative {
  pick: number;
  source: string;
  label: string;
  count: number;
  cues: number;
  likes: number;
  author: string;
  pinned: boolean;
  by_uploader: boolean;
  score: number;
}

export interface Draft {
  id: string;
  source: "page" | "text" | "resolved";
  file: string;
  title: string;
  url: string;
  set: string;
  set_exists: boolean;
  mashups: Mashups;
  has_mashups: boolean;
  unidentified: number;
  counts: Record<Mashups, number>;
  /** Where the tracklist came from: "1001tracklists", "youtube", "exportify", "image", "text"... */
  kind: string;
  /** What was read: a link or a dropped file (empty for pasted text and saved pages). */
  origin: { kind?: string; name?: string; url?: string };
  picked: number;
  from: { source: string; label: string } | null;
  alternatives: Alternative[];
  warnings: string[];
  recording: string;
  cues: number;
  albums: number;
  tracks: DraftTrack[];
}

export interface SetSummary {
  id: string;
  name: string;
  title: string;
  url: string;
  source: "page" | "text" | "resolved";
  kind: string;
  recording: string;
  cues: number;
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
  source?: FileSource;
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

/** A file found under another name, scored against the track (see tl2mixxx's match.py). */
export interface LikelyFile extends SearchResult {
  score: number;
  confidence: "high" | "medium" | "low";
  reasons: string[];
  substitute: boolean;
  query: string;
}

/** A YouTube Music, YouTube or SoundCloud result for Find on YouTube, scored like a likely file. */
export interface VideoResult extends LikelyFile {
  source: "youtube" | "soundcloud";
  uploader: string;
  official: boolean;
  quality: string;
  thumbnail: string;
}

export interface FallbackJobResult {
  folder: string;
  set: string;
  tracks: {
    row: number;
    display: string;
    queries: { query: string; results: number; failed: boolean }[];
    candidates: VideoResult[];
    taken: { name: string; link: string; source: string; file: string } | null;
    error?: string;
  }[];
  errors: string[];
}

export interface ResolveJobResult {
  draft: string | null;
  kind: string;
  url: string;
  help: string;
  title?: string;
  count?: number;
}

export interface SuggestJobResult {
  tracks: {
    row: number;
    display: string;
    queries: { query: string; results: number; failed: boolean }[];
    candidates: LikelyFile[];
    taken: { name: string; link: string; file: string } | null;
  }[];
}

export type JobState = "queued" | "running" | "stopping" | "done" | "failed" | "stopped";

export type JobKind = "download" | "search" | "fix" | "suggest" | "resolve" | "fallback" | "cut" | "finish";

export interface Job {
  id: string;
  kind: JobKind;
  title: string;
  set: string | null;
  row: number | null;
  lane: "soulseek" | "youtube" | null;
  state: JobState;
  waiting: "soulseek" | "youtube" | "set" | null;
  ahead: number | null;
  created: string;
  started: string | null;
  finished: string | null;
  exit_code: number | null;
  message: string;
  error: string;
  /** From tl2mixxx's "PROGRESS" lines while it runs. */
  progress: { fraction: number; text: string } | null;
  result: SetResult | SearchJobResult | SuggestJobResult | FallbackJobResult | ResolveJobResult | null;
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

/** The jobs of a set's download: Soulseek, then YouTube, the recording and finishing the files. */
export const SET_JOB_KINDS: JobKind[] = ["download", "fallback", "cut", "finish"];

export function isSetJob(job: Pick<Job, "kind" | "row">): boolean {
  return job.row === null && SET_JOB_KINDS.includes(job.kind);
}

/** Jobs that change one track's file (a fix, a cut, converting it). */
export function changesTrack(job: Pick<Job, "kind" | "row">): boolean {
  return job.row !== null && (job.kind === "fix" || job.kind === "cut" || job.kind === "finish");
}
