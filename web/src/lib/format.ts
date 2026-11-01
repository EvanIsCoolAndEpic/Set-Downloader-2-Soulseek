// Formatting and wording. Status wording follows the Mixxx fork's Fix Tracks dialog (API.md).

import type { Alternative, Draft, FileSource, OutputFormat, Quality, SearchResult, Source, Track } from "./types";

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

/** Where a file came from, as the track list and the fix panel say it. */
export const SOURCE_LABELS: Record<FileSource, string> = {
  soulseek: "Soulseek",
  youtube: "YouTube (lossy)",
  soundcloud: "SoundCloud",
  mix: "Cut from the mix",
  own: "Your file",
};

const SOURCE_TIPS: Record<FileSource, string> = {
  soulseek: "Downloaded from Soulseek",
  youtube: "From YouTube: lossy, about 128 to 160 kbps. A retry still looks on Soulseek for it.",
  soundcloud: "From SoundCloud: lossy, often 128 kbps",
  mix: "Cut out of the set's recording, from its time to the next track's",
  own: "A file you chose",
};

/** Where a found track's file came from: its fix's source, else the set's Soulseek download. */
export function fileSource(t: Pick<Track, "status" | "fix" | "fix_in_use">): FileSource | null {
  if (t.status !== "found") return null;
  if (t.fix_in_use && t.fix?.source) return t.fix.source;
  return "soulseek";
}

/** A track's status, checked in the order the API describes. A found track says where its file
 * came from. */
export function trackStatus(t: Pick<Track, "status" | "fix" | "fix_in_use" | "reason" | "retry_query">): StatusText {
  if (t.status === "found" && t.fix_in_use) {
    const source = t.fix?.source ?? "soulseek";
    const picked = source === "soulseek";
    return {
      tone: "ok",
      label: SOURCE_LABELS[source] ?? SOURCE_LABELS.soulseek,
      detail: picked ? "picked" : "",
      full: picked ? "Picked on Soulseek" : (SOURCE_TIPS[source] ?? ""),
    };
  }
  if (t.status === "found" && t.fix?.file) {
    const detail = t.reason || "your file is gone";
    return { tone: "warn", label: "Found, but", detail, full: `Found, but ${detail}` };
  }
  if (t.status === "found") return { tone: "ok", label: "Soulseek", detail: "", full: SOURCE_TIPS.soulseek };
  if (t.status === "missing") {
    const retry = t.retry_query ? ` (retries search for "${t.retry_query}")` : "";
    const detail = t.reason === "not attempted" ? "not looked for yet" : t.reason || "not found";
    return { tone: "warn", label: "Missing", detail, full: `Missing: ${detail}${retry}` };
  }
  return { tone: "muted", label: "Not searched (ID)", detail: "", full: "Not searched (ID)" };
}

/** Rows the Fix Tracks dialog shows by default: missing, IDs, or fixed. */
export function needsAttention(t: Pick<Track, "status" | "fix">): boolean {
  return t.status !== "found" || t.fix !== null;
}

/** "28 Soulseek, 4 YouTube, 2 from the mix, 3 missing" for a set's tracks (rows that count). */
export function breakdown(tracks: Pick<Track, "status" | "fix" | "fix_in_use" | "selectable">[]): string {
  const counts: Record<string, number> = {};
  for (const t of tracks) {
    if (!t.selectable) continue;
    const src = fileSource(t);
    const key = src === "soundcloud" ? "youtube" : (src ?? (t.status === "missing" ? "missing" : ""));
    if (key) counts[key] = (counts[key] ?? 0) + 1;
  }
  const words: [string, string][] = [
    ["soulseek", "Soulseek"],
    ["youtube", "YouTube"],
    ["mix", "from the mix"],
    ["own", "your own"],
    ["missing", "missing"],
  ];
  const parts = words.filter(([k]) => counts[k]).map(([k, w]) => `${counts[k]} ${w}`);
  return parts.length ? parts.join(", ") : "No tracks to download.";
}

/** What a fix job does, from its title ("Kettle - Ghosts: download the picked file"). */
export function fixAction(title: string): "undo" | "pick" | "search" | "own" {
  if (title.endsWith(": undo the fix")) return "undo";
  if (/: download the picked (file|video|track)$/.test(title)) return "pick";
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

export const TRACKLIST_EXTENSIONS = ["html", "htm", "txt", "csv", "json", "png", "jpg", "jpeg", "heic", "heif"];

export function isTracklistFile(name: string): boolean {
  return TRACKLIST_EXTENSIONS.includes(extension(name));
}

export function isImageFile(name: string): boolean {
  return ["png", "jpg", "jpeg", "heic", "heif"].includes(extension(name));
}

/** A single line that is a web address (what the server reads with a job). */
export function looksLikeLink(text: string): boolean {
  const s = text.trim();
  if (!s || /\s/.test(s)) return false;
  return /^https?:\/\//i.test(s) || /^spotify:(playlist|album|track):\w+$/.test(s) || /^(www\.)?[\w-]+(\.[\w-]+)+\/\S*$/i.test(s);
}

const KIND_NAMES: Record<string, string> = {
  "1001tracklists": "1001Tracklists page",
  youtube: "YouTube video",
  soundcloud: "SoundCloud",
  mixcloud: "Mixcloud show",
  spotify: "Spotify",
  apple: "Apple Music",
  web: "Web page",
};

/** What a set's link is, for its header ("1001Tracklists page", "YouTube video"...). */
export function linkName(kind: string, url: string): string {
  if (KIND_NAMES[kind]) return KIND_NAMES[kind];
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "Web page";
  }
}

/** Where a draft's tracklist came from, in one line: "From the comments on Kettle | Rooftop
 * Session, 5 tracks with times", "Exportify: Liked Songs, 312 tracks", "From a screenshot". */
export function originText(
  d: Pick<Draft, "kind" | "origin" | "from" | "title" | "tracks" | "cues" | "source" | "albums" | "file">,
): string {
  const n = d.tracks.filter((t) => t.kind !== "component").length - d.albums;
  const count = d.cues > 0 ? `${plural(n, "track")} with times` : plural(n, "track");
  const albums = d.albums ? `, ${plural(d.albums, "album")}` : "";
  const from = d.from?.source ?? "";
  const video = d.kind === "soundcloud" ? "the upload" : d.kind === "mixcloud" ? "the show" : "the video";
  const where: Record<string, string> = {
    description: `From the description of ${d.title}`,
    chapters: `From the chapters of ${d.title}`,
    comment: `From the comments on ${d.title}`,
    comments: `Pieced together from the comments on ${d.title}`,
    sections: `From Mixcloud's tracklist for ${d.title}`,
  };
  let head: string;
  if (where[from]) head = where[from];
  else if (d.kind === "1001tracklists") head = "From a saved 1001Tracklists page";
  else if (d.kind === "youtube" && d.origin.url && /[?&]list=|\/playlist/.test(d.origin.url)) head = `YouTube playlist: ${d.title}`;
  else if (d.kind === "youtube" || d.kind === "soundcloud" || d.kind === "mixcloud") head = `From ${video}: ${d.title}`;
  else if (d.kind === "exportify") head = `Exportify: ${d.title}`;
  else if (d.kind === "spotify") head = `Spotify: ${d.title}`;
  else if (d.kind === "apple") head = `Apple Music: ${d.title}`;
  else if (d.kind === "image") head = "From a screenshot";
  else if (d.kind === "csv") head = `From a spreadsheet: ${d.title}`;
  else if (d.kind === "web") head = "From a web page";
  else if (d.source === "text") head = d.file.startsWith("Pasted tracklist") ? "From pasted text" : "From a text file";
  else if (d.origin.kind === "page") head = "From a saved page";
  else head = "From a tracklist file";
  return `${head}, ${count}${albums}`;
}

/** An alternative's name in the switcher: "Comment by @x (820 likes, pinned)". */
export function alternativeLabel(a: Pick<Alternative, "label" | "source">): string {
  const l = a.label || a.source || "Tracklist";
  return l.charAt(0).toUpperCase() + l.slice(1);
}

export const QUALITY_LABELS: Record<Quality, string> = {
  lossless: "Lossless only",
  best: "Best available",
  fast: "Fast",
};

export const QUALITY_HELP: Record<Quality, string> = {
  lossless: "Only FLAC, WAV or AIFF from Soulseek. Tracks nobody shares lossless stay missing (or come from YouTube, if it's on).",
  best: "Lossless when someone has it, else the best MP3. Waits for each search to finish.",
  fast: "Takes the first good file Soulseek offers, with shorter searches. Quicker, sometimes a worse copy.",
};

export const FORMAT_LABELS: Record<OutputFormat, string> = {
  keep: "Keep",
  flac: "FLAC",
  aiff: "AIFF",
  mp3: "MP3 320",
  wav: "WAV",
};

export const FORMAT_HELP: Record<OutputFormat, string> = {
  keep: "Files stay as they were downloaded.",
  flac: "Every file becomes FLAC. A lossy file stays lossy: converting doesn't bring quality back.",
  aiff: "Every file becomes AIFF, which plays everywhere, CDJs included. A lossy file stays lossy.",
  mp3: "Every file becomes a 320 kbps MP3. Lossless files lose a little quality.",
  wav: "Every file becomes WAV. Few players read tags in WAV files. A lossy file stays lossy.",
};

export const SOURCE_INFO: Record<Source, { name: string; help: string }> = {
  soulseek: { name: "Soulseek", help: "Files from other people's libraries, lossless when someone shares it. Needs a login." },
  youtube: {
    name: "YouTube",
    help: "YouTube Music, YouTube and SoundCloud, for what Soulseek doesn't have. Only results that surely are the track. Lossy.",
  },
  mix: {
    name: "Cut from the set",
    help: "For a set with a recording and track times, like a YouTube mix: what's still missing is cut out of the recording.",
  },
};

/** Searches for buying a track, opened in the browser. */
export function buyLinks(t: Pick<Track, "artist" | "title">): { name: string; url: string }[] {
  const q = encodeURIComponent(`${t.artist} ${t.title}`.trim());
  return [
    { name: "Bandcamp", url: `https://bandcamp.com/search?q=${q}&item_type=t` },
    { name: "Beatport", url: `https://www.beatport.com/search?q=${q}` },
  ];
}
