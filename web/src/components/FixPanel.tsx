import { useEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent } from "react";
import {
  SparkleIcon,
  ArrowCounterClockwiseIcon,
  ArrowSquareOutIcon,
  CheckCircleIcon,
  DownloadSimpleIcon,
  FolderOpenIcon,
  MagnifyingGlassIcon,
  ScissorsIcon,
  SealCheckIcon,
  StopIcon,
  UploadSimpleIcon,
  XCircleIcon,
  XIcon,
  YoutubeLogoIcon,
} from "@phosphor-icons/react";
import { api, ApiError, errorText } from "../lib/api";
import {
  AUDIO_EXTENSIONS,
  baseName,
  buyLinks,
  duration,
  fixAction,
  isAudioFile,
  lengthMatch,
  lengthTip,
  limitText,
  quality,
  size,
  trackStatus,
} from "../lib/format";
import { getData, useStore } from "../lib/store";
import {
  changesTrack,
  isActive,
  type Job,
  type LikelyFile,
  type SearchJobResult,
  type SearchResult,
  type SuggestJobResult,
  type Track,
  type VideoResult,
} from "../lib/types";
import { Button, IconButton } from "./ui/Button";
import { inputClass, FieldError } from "./ui/Field";
import { Notice } from "./ui/Notice";
import { StatusLabel } from "./ui/Status";
import { Bar, skeletonWidth } from "./ui/Skeleton";

interface Props {
  setId: string;
  /** The set has a recording to cut tracks out of. */
  hasRecording: boolean;
  track: Track;
  closing: boolean;
  onClose: () => void;
  onSettings: () => void;
  /** An audio file dropped anywhere on the window while this panel is open. */
  dropped: { file: File; nonce: number } | null;
}

/** Fix one track: search Soulseek with other words and pick a file, find it on YouTube, cut it out
 * of the set's recording, use a file of your own, or undo the fix. Wording follows the Mixxx
 * fork's Fix Tracks dialog. */
export function FixPanel({ setId, hasRecording, track, closing, onClose, onSettings, dropped }: Props) {
  const jobs = useStore((d) => d.jobs);
  const uploadLimit = useStore((d) => d.state?.limits.upload_bytes ?? 0);
  const queryLimit = useStore((d) => d.state?.limits.query_chars ?? 300);

  const initialQuery = track.fix?.query || (track.unidentified ? "" : track.search);
  const [query, setQuery] = useState(initialQuery);
  const [searchId, setSearchId] = useState<string | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const [fixId, setFixId] = useState<string | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [uploading, setUploading] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const searchIdRef = useRef<string | null>(null);
  searchIdRef.current = searchId;

  const search = searchId ? jobs[searchId] : undefined;
  const fixJob = useMemo<Job | undefined>(() => {
    // A fix of this track that is running now, else the last one started here
    const active = Object.values(jobs).find((j) => changesTrack(j) && j.set === setId && j.row === track.row && isActive(j));
    return active ?? (fixId ? jobs[fixId] : undefined);
  }, [jobs, setId, track.row, fixId]);
  const fixing = !!fixJob && isActive(fixJob);
  // A search's results, or the files a "find likely matches" or "find on YouTube" job scored
  const done = search?.state === "done" ? search.result : null;
  const result = done && "results" in done ? (done as SearchJobResult) : null;
  const likely = done && "tracks" in done ? ((done as SuggestJobResult).tracks[0]?.candidates ?? []) : null;
  const results: (SearchResult | LikelyFile | VideoResult)[] = likely ?? result?.results ?? [];
  const pickedResult = results.find((x) => x.link === picked);
  const pickedVideo = !!pickedResult && "source" in pickedResult && !pickedResult.link.startsWith("slsk://");

  // Another track: start over, and stop a search that was for the old one
  useEffect(() => {
    setQuery(track.fix?.query || (track.unidentified ? "" : track.search));
    setPicked(null);
    setFixId(null);
    setError(null);
    setSearchId(null);
    requestAnimationFrame(() => inputRef.current?.focus());
    return () => {
      // Cleanup runs outside render: read the store directly
      const id = searchIdRef.current;
      const job = id ? getData().jobs[id] : undefined;
      if (id && job && isActive(job)) void api.stopJob(id).catch(() => {});
    };
    // identity changes when the set is imported again and the row is another track
  }, [setId, track.row, track.identity]); // eslint-disable-line react-hooks/exhaustive-deps

  // An audio file dropped on the window
  useEffect(() => {
    if (dropped) void useOwnFile(dropped.file);
  }, [dropped?.nonce]); // eslint-disable-line react-hooks/exhaustive-deps

  async function runSearch() {
    const q = query.trim();
    if (!q) return;
    setError(null);
    setPicked(null);
    if (search && isActive(search)) void api.stopJob(search.id).catch(() => {});
    try {
      const { job } = await api.search(q);
      setSearchId(job.id);
    } catch (e) {
      setError(asApiError(e));
    }
  }

  async function findLikely() {
    setError(null);
    setPicked(null);
    if (search && isActive(search)) void api.stopJob(search.id).catch(() => {});
    try {
      const { job } = await api.suggest(setId, track.row, track.identity);
      setSearchId(job.id);
    } catch (e) {
      setError(asApiError(e));
    }
  }

  async function findOnYoutube() {
    setError(null);
    setPicked(null);
    if (search && isActive(search)) void api.stopJob(search.id).catch(() => {});
    try {
      const { job } = await api.findOnYoutube(setId, track.row, track.identity);
      setSearchId(job.id);
    } catch (e) {
      setError(asApiError(e));
    }
  }

  async function cutFromSet() {
    setError(null);
    try {
      const { job } = await api.cutFromSet(setId, track.row, track.identity);
      setFixId(job.id);
    } catch (e) {
      setError(asApiError(e));
    }
  }

  async function stopSearch() {
    if (search) await api.stopJob(search.id).catch(() => {});
  }

  async function downloadPicked() {
    const r = results.find((x) => x.link === picked);
    const q = r && "query" in r ? r.query : result?.query;
    if (!r || !q) return;
    setError(null);
    try {
      const { job } = await api.fix(setId, track.row, { identity: track.identity, link: r.link, query: q });
      setFixId(job.id);
    } catch (e) {
      setError(asApiError(e));
    }
  }

  async function useOwnFile(file: File) {
    setError(null);
    if (!isAudioFile(file.name)) {
      setError(new ApiError(415, "not_audio", `${file.name} isn't an audio file this can use (${AUDIO_EXTENSIONS.join(", ")}).`));
      return;
    }
    if (uploadLimit && file.size > uploadLimit) {
      setError(new ApiError(413, "too_large", `That file is too big: the limit is ${limitText(uploadLimit)}.`));
      return;
    }
    setUploading(file.name);
    try {
      const { upload } = await api.upload(file);
      try {
        const { job } = await api.fix(setId, track.row, { identity: track.identity, upload: upload.id });
        setFixId(job.id);
      } catch (e) {
        void api.deleteUpload(upload.id).catch(() => {});
        throw e;
      }
    } catch (e) {
      setError(asApiError(e));
    } finally {
      setUploading(null);
    }
  }

  async function undo() {
    setError(null);
    try {
      const { job } = await api.fix(setId, track.row, { identity: track.identity, clear: true });
      setFixId(job.id);
    } catch (e) {
      setError(asApiError(e));
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    e.stopPropagation();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) void useOwnFile(file);
  }

  const status = trackStatus(track);
  const needsLogin = error?.code === "login_required" || error?.code === "sockseek_missing";
  const canCut = hasRecording && track.cue != null;

  return (
    <aside
      aria-label={`Fix ${track.display}`}
      className={`relative flex w-[380px] shrink-0 flex-col border-l border-line bg-panel xl:w-[420px] ${closing ? "anim-panel-out" : "anim-panel-in"}`}
      onDragOver={(e) => {
        if (e.dataTransfer.types.includes("Files")) {
          e.preventDefault();
          setDragOver(true);
        }
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragOver(false);
      }}
      onDrop={onDrop}
    >
      <header className="flex items-start gap-2 px-5 pt-4 pb-3">
        <div className="min-w-0 flex-1">
          <h2 className="selectable text-base font-semibold text-fg">{track.display}</h2>
          <div className="mt-1 flex items-center gap-3 text-xs">
            <StatusLabel status={status} />
            {track.duration ? <span className="shrink-0 font-mono tabular text-fg-3">{duration(track.duration)}</span> : null}
          </div>
        </div>
        <IconButton label="Close (Esc)" size="sm" onClick={onClose}>
          <XIcon size={16} />
        </IconButton>
      </header>

      {track.file && (
        <div className="mx-5 mb-3 flex items-center gap-2 rounded-control border border-line px-2.5 py-1.5">
          <span className="min-w-0 flex-1 truncate font-mono text-xs text-fg-2" title={track.file}>
            {baseName(track.file)}
          </span>
          <IconButton label="Show in Finder" size="sm" onClick={() => void api.reveal({ path: track.file }).catch((e) => setError(asApiError(e)))}>
            <FolderOpenIcon size={15} />
          </IconButton>
        </div>
      )}

      <form
        className="flex flex-col gap-1.5 border-t border-line px-5 pt-3 pb-3"
        onSubmit={(e) => {
          e.preventDefault();
          void runSearch();
        }}
      >
        <label htmlFor="fix-query" className="text-xs font-medium text-fg-2">
          Search Soulseek for
        </label>
        <div className="flex gap-2">
          <input
            id="fix-query"
            ref={inputRef}
            value={query}
            maxLength={queryLimit}
            onChange={(e) => setQuery(e.target.value)}
            placeholder='Artist - Title, or any words'
            autoComplete="off"
            spellCheck={false}
            className={inputClass}
          />
          {search && isActive(search) ? (
            <Button icon={<StopIcon size={14} />} onClick={() => void stopSearch()}>
              Stop
            </Button>
          ) : (
            <Button type="submit" icon={<MagnifyingGlassIcon size={15} />} disabled={!query.trim()}>
              Search
            </Button>
          )}
        </div>
        {!track.unidentified && (
          <button
            type="button"
            onClick={() => void findLikely()}
            disabled={!!search && isActive(search)}
            className="mt-1 inline-flex items-center gap-1.5 self-start rounded-control text-xs font-medium text-accent-fg hover:underline disabled:opacity-45"
          >
            <SparkleIcon size={13} aria-hidden />
            Find likely matches under other names
          </button>
        )}
        {(!track.unidentified || canCut) && (
          <div className="mt-2 flex flex-wrap gap-2">
            {!track.unidentified && (
              <Button
                size="sm"
                icon={<YoutubeLogoIcon size={14} aria-hidden />}
                onClick={() => void findOnYoutube()}
                disabled={!!search && isActive(search)}
                title="Looks for the track on YouTube Music, YouTube and SoundCloud. Their audio is lossy (about 128 to 160 kbps)."
              >
                Find on YouTube
              </Button>
            )}
            {canCut && (
              <Button
                size="sm"
                icon={<ScissorsIcon size={14} aria-hidden />}
                onClick={() => void cutFromSet()}
                disabled={fixing}
                title={`Cuts the track out of the set's recording, from ${duration(track.cue)} to the next track's time.`}
              >
                Cut from the set
              </Button>
            )}
          </div>
        )}
      </form>

      <div className="flex min-h-0 flex-1 flex-col">
        <SearchState job={search} count={results.length} hasDuration={!!track.duration} />
        {search && isActive(search) && <ResultsSkeleton />}
        {results.length > 0 && (
          <Results results={results} picked={picked} onPick={setPicked} onChoose={() => void downloadPicked()} trackDuration={track.duration} />
        )}
        {!search && <div className="flex-1" />}
      </div>

      <footer className="flex flex-col gap-2.5 border-t border-line px-5 pt-3 pb-4">
        {error && (
          needsLogin ? (
            <Notice tone="warn" action={<Button size="sm" onClick={onSettings}>Open settings</Button>}>
              {error.message}
            </Notice>
          ) : (
            <FieldError message={error.message} />
          )
        )}
        {fixJob && <FixProgress job={fixJob} />}
        {uploading && !fixJob && (
          <p className="flex items-center gap-2 text-xs text-fg-2">
            <span className="progress w-12" aria-hidden />
            <span className="truncate">Copying {uploading}...</span>
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="primary"
            icon={<DownloadSimpleIcon size={15} />}
            disabled={!picked || fixing}
            onClick={() => void downloadPicked()}
            title={
              pickedVideo
                ? "Downloads its audio into the set's folder and uses it for the track. It's lossy: a retry still looks on Soulseek."
                : "Downloads this file into the set's folder and uses it for the track. A file that's there already is kept."
            }
          >
            Download selected
          </Button>
          <Button
            icon={<UploadSimpleIcon size={15} />}
            disabled={fixing || !!uploading}
            onClick={() => fileRef.current?.click()}
            title="A file you found yourself: it's copied into the set's folder."
          >
            Use my own file
          </Button>
          {track.fix && (
            <Button
              variant="ghost"
              icon={<ArrowCounterClockwiseIcon size={15} />}
              disabled={fixing}
              onClick={() => void undo()}
              title="Goes back to what the set's search found (the files stay in the folder)."
            >
              Undo fix
            </Button>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-3">
          <span>Nothing right? Leave it missing, drop an audio file here, or buy it:</span>
          {!track.unidentified &&
            buyLinks(track).map((b) => (
              <button
                key={b.name}
                type="button"
                onClick={() => void api.openUrl(b.url).catch((e) => setError(asApiError(e)))}
                className="inline-flex items-center gap-1 rounded-sm font-medium text-accent-fg hover:underline"
                title={`Search ${b.name} for ${track.display}`}
              >
                {b.name}
                <ArrowSquareOutIcon size={11} aria-hidden />
              </button>
            ))}
        </div>
        <input
          ref={fileRef}
          type="file"
          hidden
          accept={AUDIO_EXTENSIONS.map((x) => "." + x).join(",")}
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (f) void useOwnFile(f);
          }}
        />
      </footer>

      {dragOver && (
        <div className="anim-fade pointer-events-none absolute inset-2 flex items-center justify-center rounded-panel border-2 border-dashed border-accent-fg bg-[color-mix(in_oklab,var(--panel)_88%,transparent)]">
          <p className="flex items-center gap-2 text-sm font-medium text-fg">
            <UploadSimpleIcon size={16} className="text-accent-fg" aria-hidden />
            Drop to use this file for the track
          </p>
        </div>
      )}
    </aside>
  );
}

function asApiError(e: unknown): ApiError {
  return e instanceof ApiError ? e : new ApiError(0, "error", errorText(e));
}

/** What the search is doing, in one line. */
function SearchState({ job, count, hasDuration }: { job?: Job; count: number; hasDuration: boolean }) {
  if (!job) return null;
  let text: string;
  let tone = "text-fg-2";
  if (job.state === "queued" && job.waiting !== "youtube") {
    text =
      job.waiting === "soulseek"
        ? `Waiting for the download that's running to finish...${job.ahead ? ` (${job.ahead} ahead)` : ""}`
        : "Starting the search...";
  } else if (job.state === "queued" && job.waiting === "youtube") {
    text = `Waiting for the YouTube job that's running to finish...${job.ahead ? ` (${job.ahead} ahead)` : ""}`;
  } else if (job.state === "running" && job.kind === "suggest") {
    text = "Trying other names on Soulseek, broadest last...";
  } else if (job.state === "running" && job.kind === "fallback") {
    text = job.progress?.text ? `Looking on YouTube Music, YouTube and SoundCloud: ${job.progress.text}...` : "Looking on YouTube Music, YouTube and SoundCloud...";
  } else if (job.state === "running") {
    text = `Searching Soulseek for "${(job.title.match(/^Search: "(.*)"$/) ?? [])[1] ?? ""}"...`;
  } else if (job.state === "stopping") {
    text = "Stopping the search...";
  } else if (job.state === "done") {
    text = count ? `${job.message}${hasDuration ? " Green lengths match the tracklist." : ""}` : job.message;
    if (!count) tone = "text-warn";
  } else if (job.state === "stopped") {
    text = "Search stopped.";
  } else {
    text = job.message || "The search failed.";
    tone = "text-bad";
  }
  return (
    <p role="status" className={`anim-fade px-5 pt-3 pb-2 text-xs ${tone}`}>
      {text}
    </p>
  );
}

function ResultsSkeleton() {
  return (
    <div aria-hidden className="flex flex-col gap-1 px-3">
      {Array.from({ length: 4 }, (_, i) => (
        <div key={i} className="flex flex-col gap-2 rounded-control px-2.5 py-2.5">
          <Bar w={skeletonWidth(i + 1)} h={9} />
          <div className="flex gap-3">
            <Bar w={64} h={8} />
            <Bar w={30} h={8} />
            <Bar w={44} h={8} />
            <Bar w={52} h={8} />
          </div>
        </div>
      ))}
    </div>
  );
}

function Results({
  results,
  picked,
  onPick,
  onChoose,
  trackDuration,
}: {
  results: (SearchResult | LikelyFile | VideoResult)[];
  picked: string | null;
  onPick: (link: string) => void;
  onChoose: () => void;
  trackDuration: number | null;
}) {
  const refs = useRef<(HTMLDivElement | null)[]>([]);
  function onKey(e: KeyboardEvent, i: number) {
    let next = -1;
    if (e.key === "ArrowDown") next = Math.min(i + 1, results.length - 1);
    else if (e.key === "ArrowUp") next = Math.max(i - 1, 0);
    else if (e.key === "Enter" && picked) {
      e.preventDefault();
      onChoose();
      return;
    }
    if (next >= 0) {
      e.preventDefault();
      onPick(results[next].link);
      refs.current[next]?.focus();
    }
  }
  return (
    <div role="radiogroup" aria-label="Search results" className="min-h-0 flex-1 overflow-y-auto px-3 pb-2">
      {results.map((r, i) => {
        const on = r.link === picked;
        const match = lengthMatch(r.length, trackDuration);
        return (
          <div
            key={r.link}
            ref={(el) => {
              refs.current[i] = el;
            }}
            role="radio"
            aria-checked={on}
            tabIndex={on || (!picked && i === 0) ? 0 : -1}
            onClick={() => onPick(r.link)}
            onDoubleClick={() => {
              onPick(r.link);
              onChoose();
            }}
            onKeyDown={(e) => onKey(e, i)}
            className={`anim-fade flex flex-col gap-1 rounded-control border px-2.5 py-2 ${
              on ? "border-accent-fg/60 bg-selected" : "border-transparent hover:bg-hover"
            }`}
          >
            <span className="truncate font-mono text-xs text-fg" title={r.path}>
              {r.name}
            </span>
            {"confidence" in r && (
              <span className="flex min-w-0 items-baseline gap-2 text-2xs">
                <span className={`shrink-0 font-medium ${CONFIDENCE[r.confidence].tone}`}>{CONFIDENCE[r.confidence].label}</span>
                <span className="truncate text-fg-3">{r.reasons.join(", ")}</span>
              </span>
            )}
            <span className="grid grid-cols-[minmax(0,1.1fr)_auto_auto_minmax(0,1fr)] items-center gap-x-3 font-mono tabular text-2xs text-fg-2">
              <span className="truncate">{"source" in r && !r.link.startsWith("slsk://") && !r.bitrate ? "Lossy" : quality(r)}</span>
              <span
                className={match === "match" ? "text-ok" : match === "differs" ? "text-warn" : ""}
                title={lengthTip(r.length, trackDuration) || undefined}
              >
                {r.length ? duration(r.length) : "-:--"}
              </span>
              <span>{size(r.size)}</span>
              {"source" in r && !r.link.startsWith("slsk://") ? (
                <span className="flex min-w-0 items-center justify-end gap-1 truncate text-right" title={r.uploader || r.user}>
                  {r.official && <SealCheckIcon size={12} className="shrink-0 text-accent-fg" aria-label="Official upload" />}
                  {r.source === "soundcloud" ? "SoundCloud" : "YouTube"}
                </span>
              ) : (
                <span
                  className="truncate text-right"
                  title={r.free_slot ? "Has a free upload slot: downloads right away" : "No free upload slot: the download may wait in a queue"}
                >
                  {r.user}
                  {!r.free_slot && <span className="text-fg-3"> (queue)</span>}
                </span>
              )}
            </span>
          </div>
        );
      })}
    </div>
  );
}

const CONFIDENCE = {
  high: { label: "Surely the track", tone: "text-ok" },
  medium: { label: "Likely", tone: "text-accent-fg" },
  low: { label: "Unlikely", tone: "text-fg-3" },
} as const;

const RUNNING_WORDS = {
  pick: (title: string) => (/(video|track)$/.test(title) ? "Downloading its audio..." : "Downloading the picked file..."),
  search: (title: string) => `Searching again for "${(title.match(/search again for "(.*)"$/) ?? [])[1] ?? ""}"...`,
  own: (title: string) => `Using ${title.replace(/^.*: use /, "")}...`,
  undo: () => "Undoing the fix...",
};

/** A fix job of this track: what it's doing, Stop, and how it ended. */
function FixProgress({ job }: { job: Job }) {
  const last = useStore((d) => d.logs[job.id]?.lines.at(-1));
  if (isActive(job)) {
    const running =
      job.kind === "cut"
        ? "Cutting it out of the set's recording..."
        : job.kind === "finish"
          ? "Converting the file and writing its tags..."
          : RUNNING_WORDS[fixAction(job.title)](job.title);
    const what =
      job.state === "queued"
        ? job.waiting === "soulseek"
          ? "Waiting for the download that's running to finish..."
          : job.waiting === "youtube"
            ? "Waiting for the YouTube job that's running to finish..."
            : job.waiting === "set"
              ? "Waiting for the set's other job to finish..."
              : "Starting..."
        : job.state === "stopping"
          ? "Stopping..."
          : running;
    return (
      <div className="anim-fade flex flex-col gap-1.5">
        <div className="flex items-center gap-2 text-xs text-fg">
          <span className="min-w-0 flex-1 truncate">{what}</span>
          {job.state !== "stopping" && (
            <Button size="sm" variant="ghost" icon={<StopIcon size={13} />} onClick={() => void api.stopJob(job.id).catch(() => {})}>
              Stop
            </Button>
          )}
        </div>
        {job.state === "running" &&
          (job.progress ? (
            <div className="meter" role="progressbar" aria-label={what} aria-valuenow={Math.round(job.progress.fraction * 100)}>
              <span style={{ transform: `scaleX(${job.progress.fraction})` }} />
            </div>
          ) : (
            <div className="progress" role="progressbar" aria-label={what} />
          ))}
        {last && job.state === "running" && <p className="truncate font-mono text-2xs text-fg-3">{last}</p>}
      </div>
    );
  }
  const ok = job.state === "done";
  const Icon = ok ? CheckCircleIcon : XCircleIcon;
  return (
    <p role="status" className={`anim-rise flex items-start gap-1.5 text-xs ${ok ? "text-fg-2" : job.state === "stopped" ? "text-fg-2" : "text-bad"}`}>
      <Icon size={14} className={`mt-px shrink-0 ${ok ? "text-ok" : job.state === "stopped" ? "text-fg-3" : "text-bad"}`} aria-hidden />
      <span>{job.message || (ok ? "Done." : "It didn't work.")}</span>
    </p>
  );
}
