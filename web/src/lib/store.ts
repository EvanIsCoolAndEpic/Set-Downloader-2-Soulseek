// App data shared by every view: state, sets, jobs, logs and each open set's tracks. Kept in one
// small store (useSyncExternalStore) and fed by the API and the live event stream.

import { useSyncExternalStore } from "react";
import { api, ApiError, errorText } from "./api";
import { listen, type ConnState } from "./events";
import type { AppState, Job, SetSummary, TracksResponse } from "./types";

export interface LogBuffer {
  lines: string[];
  /** The number (n) of the last line held. Line numbers count from 1 per job. */
  lastN: number;
}

export interface TracksEntry {
  data: TracksResponse | null;
  loading: boolean;
  error: string | null;
  errorCode: string | null;
}

export interface Data {
  conn: ConnState;
  state: AppState | null;
  bootError: { code: string; message: string } | null;
  sets: SetSummary[] | null;
  setsError: string | null;
  jobs: Record<string, Job>;
  logs: Record<string, LogBuffer>;
  tracks: Record<string, TracksEntry>;
}

const MAX_LOG = 2000;

const initial: Data = {
  conn: "connecting",
  state: null,
  bootError: null,
  sets: null,
  setsError: null,
  jobs: {},
  logs: {},
  tracks: {},
};

let data: Data = initial;
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

export function update(patch: Partial<Data> | ((d: Data) => Partial<Data>)) {
  data = { ...data, ...(typeof patch === "function" ? patch(data) : patch) };
  emit();
}

export function getData(): Data {
  return data;
}

/** For tests. */
export function resetStore(next: Partial<Data> = {}) {
  data = { ...initial, ...next };
  emit();
}

function subscribe(l: () => void) {
  listeners.add(l);
  return () => listeners.delete(l);
}

/** Select a part of the store. The selector must return something already in the store (or a
 * primitive), not a new object, or React re-renders forever. */
export function useStore<T>(select: (d: Data) => T): T {
  return useSyncExternalStore(subscribe, () => select(data));
}

// ------------------------------------------------------------------ loading

export async function loadState() {
  try {
    const state = await api.state();
    update({ state, bootError: null });
  } catch (e) {
    const err = e instanceof ApiError ? e : new ApiError(0, "network", errorText(e));
    update({ bootError: { code: err.code, message: err.message } });
  }
}

let setsTimer: ReturnType<typeof setTimeout> | null = null;
let setsInFlight = false;
let setsAgain = false;

export async function loadSets() {
  if (setsInFlight) {
    setsAgain = true;
    return;
  }
  setsInFlight = true;
  try {
    const res = await api.sets();
    update({ sets: res.sets, setsError: null });
  } catch (e) {
    update({ setsError: errorText(e) });
  } finally {
    setsInFlight = false;
    if (setsAgain) {
      setsAgain = false;
      void loadSets();
    }
  }
}

/** Sets change in bursts (a job event, then a sets event): refresh once. */
export function refreshSetsSoon(ms = 120) {
  if (setsTimer) clearTimeout(setsTimer);
  setsTimer = setTimeout(() => {
    setsTimer = null;
    void loadSets();
  }, ms);
}

export async function loadJobs() {
  try {
    const res = await api.jobs();
    update((d) => {
      const jobs: Record<string, Job> = {};
      for (const j of [...res.jobs].reverse()) see(j.id); // the list is newest first
      for (const j of res.jobs) jobs[j.id] = { ...d.jobs[j.id], ...j };
      return { jobs };
    });
  } catch {
    // the event stream fills them in
  }
}

const trackRequests = new Map<string, AbortController>();

/** Loads a set's tracks. quiet keeps what is shown while it reloads (after a fix). */
export async function loadTracks(setId: string, quiet = false) {
  trackRequests.get(setId)?.abort();
  const ctrl = new AbortController();
  trackRequests.set(setId, ctrl);
  update((d) => {
    const prev = d.tracks[setId];
    return {
      tracks: {
        ...d.tracks,
        [setId]: {
          data: quiet ? (prev?.data ?? null) : null,
          loading: true,
          error: null,
          errorCode: null,
        },
      },
    };
  });
  try {
    const res = await api.tracks(setId, ctrl.signal);
    if (ctrl.signal.aborted) return;
    update((d) => ({
      tracks: { ...d.tracks, [setId]: { data: res, loading: false, error: null, errorCode: null } },
    }));
  } catch (e) {
    if (ctrl.signal.aborted) return;
    const code = e instanceof ApiError ? e.code : "error";
    update((d) => ({
      tracks: {
        ...d.tracks,
        [setId]: { data: d.tracks[setId]?.data ?? null, loading: false, error: errorText(e), errorCode: code },
      },
    }));
  } finally {
    if (trackRequests.get(setId) === ctrl) trackRequests.delete(setId);
  }
}

/** Fills a job's log from the server (the stream then adds new lines). */
export async function loadLog(jobId: string) {
  try {
    const job = await api.job(jobId);
    const lines = job.log ?? [];
    update((d) => {
      const live = d.logs[jobId];
      // Lines that arrived on the stream while this was loading stay
      const lastN = Math.max(job.log_lines, live?.lastN ?? 0);
      const extra = live && live.lastN > job.log_lines ? live.lines.slice(-(live.lastN - job.log_lines)) : [];
      const { log: _log, ...rest } = job;
      return {
        logs: { ...d.logs, [jobId]: { lines: [...lines, ...extra].slice(-MAX_LOG), lastN } },
        jobs: { ...d.jobs, [jobId]: { ...d.jobs[jobId], ...rest } },
      };
    });
  } catch {
    // shown as an empty log
  }
}

// ------------------------------------------------------------------ live events

// The order jobs were first seen in: "created" has whole seconds only, so it breaks ties
const seen = new Map<string, number>();
let seq = 0;
function see(id: string) {
  if (!seen.has(id)) seen.set(id, ++seq);
}

export function upsertJob(job: Job) {
  see(job.id);
  update((d) => ({ jobs: { ...d.jobs, [job.id]: { ...d.jobs[job.id], ...job } } }));
}

// Log lines can come fast: they are applied once per frame
let pendingLines: { job: string; n: number; line: string }[] = [];
let flushScheduled = false;

function flushLines() {
  flushScheduled = false;
  const batch = pendingLines;
  pendingLines = [];
  if (!batch.length) return;
  update((d) => {
    const logs = { ...d.logs };
    for (const { job, n, line } of batch) {
      const buf = logs[job] ?? { lines: [], lastN: 0 };
      if (n <= buf.lastN) continue; // replayed after a reconnect
      const lines = buf.lines.length >= MAX_LOG ? buf.lines.slice(-MAX_LOG + 1) : buf.lines.slice();
      lines.push(line);
      logs[job] = { lines, lastN: n };
    }
    return { logs };
  });
}

function scheduleFlush() {
  if (flushScheduled) return;
  flushScheduled = true;
  if (typeof requestAnimationFrame === "function" && !document.hidden) requestAnimationFrame(flushLines);
  else setTimeout(flushLines, 50);
}

export function handleEvent(event: string, payload: unknown) {
  switch (event) {
    case "job":
      upsertJob(payload as Job);
      refreshSetsSoon(); // a set's busy flag follows its jobs
      break;
    case "log":
      pendingLines.push(payload as { job: string; n: number; line: string });
      scheduleFlush();
      break;
    case "sets": {
      const { set } = payload as { set: string };
      refreshSetsSoon(0);
      if (data.tracks[set]) void loadTracks(set, true);
      break;
    }
    case "state": {
      const next = payload as AppState;
      const moved = data.state && data.state.settings.music_dir !== next.settings.music_dir;
      update({ state: next });
      if (moved) {
        update({ tracks: {} });
        void loadSets();
      }
      break;
    }
  }
}

let stopListening: AbortController | null = null;

/** Start-up: state, sets and jobs, then the live stream. */
export async function boot() {
  await loadState();
  if (data.bootError) return;
  await Promise.all([loadSets(), loadJobs()]);
  stopListening?.abort();
  stopListening = new AbortController();
  let wasLost = false;
  void listen({
    signal: stopListening.signal,
    onEvent: handleEvent,
    onConn: (conn) => {
      if (conn === "open" && wasLost) {
        // Back after a drop: catch up in case the server restarted (replay can't cover that)
        void loadState();
        void loadSets();
        void loadJobs();
      }
      wasLost = conn === "lost";
      if (data.conn !== conn) update({ conn });
    },
  });
}

// ------------------------------------------------------------------ derived

export function jobsNewestFirst(jobs: Record<string, Job>): Job[] {
  return Object.values(jobs).sort(
    (a, b) => b.created.localeCompare(a.created) || (seen.get(b.id) ?? 0) - (seen.get(a.id) ?? 0),
  );
}
