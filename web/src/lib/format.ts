// Formatting and wording. Status wording follows the Mixxx fork's Fix Tracks dialog (API.md).

import type { SearchResult, Track } from "./types";

/** 284 -> "4:44", 3735 -> "1:02:15". */
export function duration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return "";
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = String(s % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${ss}` : `${m}:${ss}`;
}

/** 31000000 -> "31.0 MB", like the Mixxx fork (decimal megabytes). */
export function size(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "";
  if (bytes < 1_000_000) return `${Math.max(1, Math.round(bytes / 1000))} KB`;
  if (bytes < 1_000_000_000) return `${(bytes / 1_000_000).toFixed(1)} MB`;
  return `${(bytes / 1_000_000_000).toFixed(2)} GB`;
}

/** Limits are binary megabytes on the server: 20971520 -> "20 MB". */
export function limitText(bytes: number): string {
  return `${Math.round(bytes / (1024 * 1024))} MB`;
}

const LOSSLESS = new Set(["flac", "wav", "aiff", "aif", "alac", "ape", "wv"]);

/** "FLAC 16/44.1" for lossless, "MP3 320 kbps" for lossy. */
export function quality(r: Pick<SearchResult, "format" | "bitrate" | "samplerate" | "bitdepth">): string {
  const fmt = (r.format || "").toUpperCase() || "Audio";
  if (LOSSLESS.has((r.format || "").toLowerCase())) {
    if (r.bitdepth && r.samplerate) {
      const khz = Number((r.samplerate / 1000).toFixed(1));
      return `${fmt} ${r.bitdepth}/${khz}`;
    }
    return fmt;
  }
  return r.bitrate ? `${fmt} ${r.bitrate} kbps` : fmt;
}

/** Whether a result's length matches the tracklist's (within 5 seconds). */
export function lengthMatch(length: number, trackDuration: number | null): "match" | "differs" | "unknown" {
  if (!length || !trackDuration) return "unknown";
  return Math.abs(length - trackDuration) <= 5 ? "match" : "differs";
}

export function lengthTip(length: number, trackDuration: number | null): string {
  const m = lengthMatch(length, trackDuration);
  if (m === "match") return "The same length as on the tracklist";
  if (m === "differs") return `The tracklist says ${duration(trackDuration)}: maybe another version`;
  return "";
}

export type Tone = "ok" | "warn" | "bad" | "work" | "muted";

export interface StatusText {
  tone: Tone;
  label: string;
  detail: string;
  /** The whole sentence, for a tooltip or a screen reader. */
  full: string;
}

/** A track's status, checked in the order the API describes. */
export function trackStatus(t: Pick<Track, "status" | "fix" | "fix_in_use" | "reason" | "retry_query">): StatusText {
  if (t.status === "found" && t.fix_in_use) {
    const label = t.fix?.source === "own" ? "Your file" : "Picked on Soulseek";
    return { tone: "ok", label, detail: "", full: label };
  }
  if (t.status === "found" && t.fix?.file) {
    const detail = t.reason || "your file is gone";
    return { tone: "warn", label: "Found, but", detail, full: `Found, but ${detail}` };
  }
  if (t.status === "found") return { tone: "ok", label: "Found", detail: "", full: "Found" };
  if (t.status === "missing") {
    const retry = t.retry_query ? ` (retries search for "${t.retry_query}")` : "";
    const detail = t.reason || "not found";
    return { tone: "warn", label: "Missing", detail, full: `Missing: ${detail}${retry}` };
  }
  return { tone: "muted", label: "Not searched (ID)", detail: "", full: "Not searched (ID)" };
}

/** Rows the Fix Tracks dialog shows by default: missing, IDs, or fixed. */
export function needsAttention(t: Pick<Track, "status" | "fix">): boolean {
  return t.status !== "found" || t.fix !== null;
}

/** What a fix job does, from its title ("Kettle - Ghosts: download the picked file"). */
export function fixAction(title: string): "undo" | "pick" | "search" | "own" {
  if (title.endsWith(": undo the fix")) return "undo";
  if (title.endsWith(": download the picked file")) return "pick";
  if (/: search again for ".*"$/.test(title)) return "search";
  return "own";
}

export function plural(n: number, one: string, many = one + "s"): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** "6 of 7 tracks have a file." or "All 7 tracks have a file." */
export function haveFileText(found: number, total: number): string {
  if (total === 0) return "No tracks to download.";
  if (found >= total) return total === 1 ? "The track has a file." : `All ${total} tracks have a file.`;
  return `${found} of ${total} ${total === 1 ? "track has" : "tracks have"} a file.`;
}

export function baseName(path: string): string {
  const i = Math.max(path.lastIndexOf("/"), path.lastIndexOf("\\"));
  return i >= 0 ? path.slice(i + 1) : path;
}

/** "Today 20:39", "Yesterday 09:12", "Oct 28" or "Oct 28, 2025". */
export function when(iso: string | null | undefined, now = new Date()): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const time = d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  const day = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((day(now) - day(d)) / 86_400_000);
  if (diff === 0) return `Today ${time}`;
  if (diff === 1) return `Yesterday ${time}`;
  const opts: Intl.DateTimeFormatOptions = { month: "short", day: "numeric" };
  if (d.getFullYear() !== now.getFullYear()) opts.year = "numeric";
  return d.toLocaleDateString("en-US", opts);
}

export const MASHUP_LABELS = {
  components: "Parts",
  original: "Mashup",
  both: "Both",
} as const;

export const MASHUP_HELP = {
  components: "Downloads the tracks each mashup is made of. DJ edits are rarely on Soulseek.",
  original: "Downloads each mashup itself, not its parts.",
  both: "Downloads each mashup and its parts.",
} as const;

export const AUDIO_EXTENSIONS = ["mp3", "flac", "wav", "aiff", "aif", "m4a", "aac", "ogg", "opus", "alac", "wma"];

export function extension(name: string): string {
  const i = name.lastIndexOf(".");
  return i >= 0 ? name.slice(i + 1).toLowerCase() : "";
}

export function isAudioFile(name: string): boolean {
  return AUDIO_EXTENSIONS.includes(extension(name));
}

export function isTracklistFile(name: string): boolean {
  return ["html", "htm", "txt"].includes(extension(name));
}
