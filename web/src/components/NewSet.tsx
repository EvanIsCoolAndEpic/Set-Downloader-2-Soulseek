import { useEffect, useRef, useState } from "react";
import {
  AppleLogoIcon,
  ArrowLeftIcon,
  ArrowSquareOutIcon,
  DownloadSimpleIcon,
  FileArrowUpIcon,
  FileCsvIcon,
  ImageIcon,
  LinkSimpleIcon,
  SoundcloudLogoIcon,
  SpotifyLogoIcon,
  StopIcon,
  TextAlignLeftIcon,
  YoutubeLogoIcon,
} from "@phosphor-icons/react";
import { api, ApiError, errorText } from "../lib/api";
import {
  alternativeLabel,
  duration,
  isImageFile,
  isTracklistFile,
  limitText,
  looksLikeLink,
  originText,
  plural,
  MASHUP_HELP,
  MASHUP_LABELS,
} from "../lib/format";
import { refreshSetsSoon, upsertJob, useStore } from "../lib/store";
import { isActive, type Draft, type Job, type Mashups, type ResolveJobResult } from "../lib/types";
import { Button } from "./ui/Button";
import { Notice } from "./ui/Notice";
import { Segmented } from "./ui/Segmented";

const EXPORTIFY = "https://exportify.app";

interface Props {
  onDone: (setId: string) => void;
  onSettings: () => void;
}

interface Problem {
  message: string;
  code: string;
  help?: string;
  kind?: string;
}

/** A new set from anything: a link (YouTube, SoundCloud, Mixcloud, Spotify, Apple Music), pasted
 * text, or a dropped file (a saved 1001Tracklists page, an Exportify CSV, a screenshot...). */
export function NewSet({ onDone, onSettings }: Props) {
  const state = useStore((d) => d.state);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [mashups, setMashups] = useState<Mashups>("components");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<"reading" | "starting" | "picking" | null>(null);
  const [reading, setReading] = useState("");
  const [problem, setProblem] = useState<Problem | null>(null);
  const [over, setOver] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const job = useStore((d) => (jobId ? d.jobs[jobId] : undefined));

  function show(d: Draft) {
    setDraft(d);
    setMashups(d.mashups);
    setProblem(null);
  }

  function fail(e: unknown) {
    const err = e instanceof ApiError ? e : new ApiError(0, "error", errorText(e));
    setProblem({ message: err.message, code: err.code });
  }

  // A link's job ended: its draft, or why not
  useEffect(() => {
    if (!job || isActive(job)) return;
    const r = job.result as ResolveJobResult | null;
    setJobId(null);
    if (job.state === "done" && r?.draft) {
      api.draft(r.draft).then(show, fail);
    } else if (job.state === "failed") {
      setProblem({ message: job.message || "That link couldn't be read.", code: "resolve_failed", help: r?.help, kind: r?.kind });
    }
  }, [job?.state]); // eslint-disable-line react-hooks/exhaustive-deps

  async function read(make: () => Promise<Draft | { job: Job }>, what: string) {
    setBusy("reading");
    setReading(what);
    setProblem(null);
    try {
      const res = await make();
      if ("job" in res) {
        upsertJob(res.job);
        setJobId(res.job.id);
      } else {
        show(res);
      }
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }

  function readText() {
    const input = text.trim();
    if (!input) return;
    void read(async () => {
      const res = await api.resolve(input);
      return "draft" in res ? res.draft : res;
    }, looksLikeLink(input) ? "Opening the link" : "Reading the tracklist");
  }

  function readFile(file: File | undefined) {
    if (!file) return;
    if (!isTracklistFile(file.name)) {
      setProblem({
        code: "not_a_tracklist",
        message: "That file isn't one Set Downloader reads. Drop a saved page (.html), a .txt or .csv list, a tracklist .json, or a screenshot.",
      });
      return;
    }
    if (state && file.size > state.limits.page_bytes) {
      setProblem({ code: "too_large", message: `That file is too big: the limit is ${limitText(state.limits.page_bytes)}.` });
      return;
    }
    const what = isImageFile(file.name) ? "Reading the picture" : file.name.toLowerCase().endsWith(".csv") ? "Reading the playlist" : "Reading the file";
    void read(() => api.draftFromFile(file), what);
  }

  function onPaste(e: React.ClipboardEvent) {
    // A screenshot pasted from the clipboard
    const file = Array.from(e.clipboardData.files).find((f) => f.type.startsWith("image/"));
    if (!file) return;
    e.preventDefault();
    const stamp = new Date().toISOString().slice(0, 16).replace("T", " at ").replace(":", ".");
    const ext = file.type === "image/jpeg" ? "jpg" : "png";
    readFile(new File([file], `Screenshot ${stamp}.${ext}`, { type: file.type }));
  }

  async function pick(n: number) {
    if (!draft || n === draft.picked) return;
    setBusy("picking");
    setProblem(null);
    try {
      show(await api.pick(draft.id, n));
    } catch (e) {
      fail(e);
    } finally {
      setBusy(null);
    }
  }

  async function start() {
    if (!draft) return;
    setBusy("starting");
    setProblem(null);
    try {
      const { job } = await api.downloadDraft(draft.id, mashups);
      upsertJob(job);
      refreshSetsSoon(0);
      onDone(job.set ?? draft.set);
    } catch (e) {
      fail(e);
      setBusy(null);
    }
  }

  const soulseekOn = !!state?.settings.sources.includes("soulseek");
  const needsLogin = soulseekOn && state?.login.source === "none";
  const noSockseek = soulseekOn && state && !state.sockseek.found;

  if (draft) {
    const count = draft.counts[mashups];
    return (
      <div className="mx-auto flex max-w-4xl flex-col gap-5 px-8 py-7 anim-rise">
        <div className="flex items-start justify-between gap-6">
          <div className="min-w-0">
            <button
              type="button"
              onClick={() => setDraft(null)}
              className="mb-2 inline-flex items-center gap-1.5 rounded-control text-xs text-fg-2 hover:text-fg"
            >
              <ArrowLeftIcon size={13} aria-hidden /> Another tracklist
            </button>
            <h1 className="selectable truncate text-xl font-semibold tracking-tight">{draft.title}</h1>
            <p className="mt-1.5 flex items-center gap-1.5 text-sm text-fg-2">
              <KindIcon kind={draft.kind} originKind={draft.origin.kind} />
              <span className="min-w-0 truncate">{originText(draft)}</span>
            </p>
            <p className="mt-1 text-sm text-fg-2">
              <span className="font-mono tabular">{count}</span> of {plural(draft.tracks.length, "row")} will download
              {draft.unidentified > 0 && <>, {draft.unidentified} unidentified</>}
              {draft.set_exists && <>. This set is already in your music folder; missing tracks are tried again.</>}
            </p>
          </div>
          <Button
            variant="primary"
            icon={<DownloadSimpleIcon size={16} aria-hidden />}
            onClick={() => void start()}
            disabled={busy !== null || count === 0}
          >
            {busy === "starting" ? "Starting" : "Download"}
          </Button>
        </div>

        {draft.alternatives.length > 1 && (
          <Alternatives draft={draft} busy={busy === "picking"} onPick={(n) => void pick(n)} />
        )}

        {draft.has_mashups && (
          <div className="flex items-center gap-3">
            <Segmented
              label="Mashups"
              value={mashups}
              onChange={setMashups}
              options={(["components", "original", "both"] as Mashups[]).map((m) => ({
                value: m,
                label: MASHUP_LABELS[m],
                count: draft.counts[m],
              }))}
            />
            <span className="text-xs text-fg-3">{MASHUP_HELP[mashups]}</span>
          </div>
        )}

        {draft.warnings.map((w) => (
          <Notice
            key={w}
            action={
              /exportify/i.test(w) ? (
                <Button size="sm" icon={<ArrowSquareOutIcon size={13} aria-hidden />} onClick={() => void api.openUrl(EXPORTIFY)}>
                  Exportify
                </Button>
              ) : undefined
            }
          >
            {w}
          </Notice>
        ))}
        {draft.albums > 0 && (
          <Notice>
            {plural(draft.albums, "row is a whole album", "rows are whole albums")}. Albums aren't downloaded yet: only the
            tracks are.
          </Notice>
        )}

        {(needsLogin || noSockseek) && (
          <Notice
            tone="warn"
            title={needsLogin ? "Add your Soulseek login first" : "sockseek wasn't found"}
            action={
              <Button size="sm" onClick={onSettings}>
                Settings
              </Button>
            }
          >
            {needsLogin
              ? "Downloads from Soulseek need an account. Or turn Soulseek off in Settings to get the tracks from YouTube."
              : "Set Downloader needs sockseek to download from Soulseek."}
          </Notice>
        )}
        {problem && <ProblemNotice problem={problem} />}

        <ol className={`flex flex-col transition-opacity ${busy === "picking" ? "opacity-50" : ""}`}>
          {draft.tracks.map((t) => {
            const on = t.downloads[mashups];
            return (
              <li
                key={t.row}
                className={`grid ${draft.cues ? "grid-cols-[3rem_4rem_minmax(0,1fr)_4rem]" : "grid-cols-[3rem_minmax(0,1fr)_4rem]"} items-center gap-3 rounded-control px-2 py-1.5 text-sm ${on ? "" : "text-fg-3"}`}
              >
                <span className="font-mono text-xs tabular text-fg-3">{t.number || "w/"}</span>
                {draft.cues > 0 && <span className="font-mono text-xs tabular text-fg-3">{t.cue != null ? duration(t.cue) : ""}</span>}
                <span className="truncate">
                  {t.display}
                  {!on && (
                    <span className="ml-2 text-xs">
                      {t.kind === "album" ? "album, not downloaded" : t.unidentified ? "unidentified" : "not downloaded"}
                    </span>
                  )}
                </span>
                <span className="text-right font-mono text-xs tabular text-fg-3">{duration(t.duration)}</span>
              </li>
            );
          })}
        </ol>
      </div>
    );
  }

  const working = busy === "reading" || !!job;
  const link = looksLikeLink(text);

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5 px-8 py-10">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">New set</h1>
        <p className="mt-1 text-sm text-fg-2">Paste a link or a tracklist, or drop a file. Set Downloader finds the tracks in it.</p>
      </div>

      <form
        className="flex flex-col gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          readText();
        }}
      >
        <label htmlFor="paste" className="text-xs font-medium text-fg-2">
          A link or a tracklist
        </label>
        <textarea
          id="paste"
          value={text}
          onChange={(e) => setText(e.target.value)}
          onPaste={onPaste}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              readText();
            }
          }}
          disabled={working}
          placeholder={"https://www.youtube.com/watch?v=...\n\nor a tracklist, one track per line:\n01. Artist - Title\n02. Artist - Title"}
          rows={link ? 2 : 7}
          spellCheck={false}
          className="w-full resize-y rounded-control border border-field bg-input px-3 py-2 font-mono text-xs text-fg outline-none placeholder:text-fg-3 focus-visible:border-accent-fg focus-visible:outline-2 focus-visible:outline-accent-fg/40 disabled:opacity-60"
        />
        <div className="flex items-center gap-3">
          <Button type="submit" variant={text.trim() ? "primary" : "secondary"} disabled={!text.trim() || working}>
            {busy === "reading" && reading !== "Reading the picture" ? reading : link ? "Read link" : "Read tracklist"}
          </Button>
          <span className="text-xs text-fg-3">
            YouTube and SoundCloud comments, Mixcloud, Spotify, Apple Music, or any list
          </span>
        </div>
      </form>

      {job && <ResolveProgress job={job} url={text.trim()} />}
      {problem && <ProblemNotice problem={problem} />}

      <button
        type="button"
        onClick={() => fileRef.current?.click()}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          readFile(e.dataTransfer.files[0]);
        }}
        disabled={working}
        className={`flex flex-col items-center gap-2 rounded-panel border border-dashed px-6 py-10 text-center transition-colors disabled:opacity-60 ${
          over ? "border-accent-fg bg-selected" : "border-line-strong hover:bg-hover"
        }`}
      >
        <FileArrowUpIcon size={28} className="text-fg-3" aria-hidden />
        <span className="text-sm font-medium">{busy === "reading" && !link ? reading : "Drop a file here, or choose one"}</span>
        {busy === "reading" && reading === "Reading the picture" ? (
          <span className="text-xs text-fg-3">The first picture can take a minute: macOS gets its text recognition ready.</span>
        ) : (
          <span className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-xs text-fg-3">
            <span>A saved 1001Tracklists page (File &gt; Save Page As)</span>
            <span className="inline-flex items-center gap-1">
              <FileCsvIcon size={13} aria-hidden /> Exportify CSV
            </span>
            <span className="inline-flex items-center gap-1">
              <ImageIcon size={13} aria-hidden /> Screenshot
            </span>
            <span>.txt, .json{state ? `, up to ${limitText(state.limits.page_bytes)}` : ""}</span>
          </span>
        )}
      </button>
      <input
        ref={fileRef}
        type="file"
        accept=".html,.htm,.txt,.csv,.json,.png,.jpg,.jpeg,.heic,.heif"
        className="hidden"
        onChange={(e) => {
          readFile(e.target.files?.[0]);
          e.target.value = "";
        }}
      />
      <p className="text-xs text-fg-3">
        Spotify playlists over 100 tracks: export them with{" "}
        <button type="button" onClick={() => void api.openUrl(EXPORTIFY)} className="rounded-sm text-accent-fg hover:underline">
          Exportify
        </button>{" "}
        and drop the .csv here. You can also paste a screenshot.
      </p>
    </div>
  );
}

/** The source's icon, before the line saying where the list came from. */
function KindIcon({ kind, originKind }: { kind: string; originKind?: string }) {
  const props = { size: 15, className: "shrink-0 text-fg-3", "aria-hidden": true } as const;
  if (kind === "youtube") return <YoutubeLogoIcon {...props} />;
  if (kind === "soundcloud") return <SoundcloudLogoIcon {...props} />;
  if (kind === "spotify" || kind === "exportify") return <SpotifyLogoIcon {...props} />;
  if (kind === "apple") return <AppleLogoIcon {...props} />;
  if (kind === "image") return <ImageIcon {...props} />;
  if (originKind === "csv" || kind === "csv") return <FileCsvIcon {...props} />;
  if (kind === "text") return <TextAlignLeftIcon {...props} />;
  return <LinkSimpleIcon {...props} />;
}

const LINK_HINTS: [RegExp, string][] = [
  [/youtu\.?be/i, "Looking through the description, the chapters and the top comments. This can take half a minute."],
  [/soundcloud/i, "Looking through the description and the comments."],
  [/mixcloud/i, "Looking for the show's tracklist, the description and the comments."],
  [/spotify/i, "Reading the playlist's public page."],
  [/music\.apple/i, "Reading the playlist's public page."],
];

/** A link being read: what's happening, and Stop. */
function ResolveProgress({ job, url }: { job: Job; url: string }) {
  const hint = LINK_HINTS.find(([re]) => re.test(url))?.[1] ?? "Reading the page.";
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setSeconds((s) => s + 1), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <div role="status" className="anim-fade flex flex-col gap-3 rounded-panel border border-line bg-panel px-4 py-3.5 shadow-panel">
      <div className="flex items-start gap-3">
        <LinkSimpleIcon size={18} className="mt-0.5 shrink-0 text-accent-fg" aria-hidden />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-fg">
            {job.state === "stopping" ? "Stopping" : `${job.title}...`}
          </p>
          <p className="mt-0.5 text-xs text-fg-2">{hint}</p>
        </div>
        <span className="shrink-0 pt-0.5 font-mono text-xs tabular text-fg-3">{seconds}s</span>
        <Button
          size="sm"
          variant="ghost"
          icon={<StopIcon size={13} aria-hidden />}
          disabled={job.state === "stopping"}
          onClick={() => void api.stopJob(job.id).catch(() => {})}
        >
          Stop
        </Button>
      </div>
      <div className="progress" aria-hidden />
    </div>
  );
}

/** What went wrong, with help for Spotify and 1001Tracklists links. */
function ProblemNotice({ problem }: { problem: Problem }) {
  const spotify = problem.kind === "spotify" || /exportify/i.test(problem.message);
  if (spotify) {
    return (
      <Notice
        tone="warn"
        title="This Spotify link can't be read"
        action={
          <Button size="sm" icon={<ArrowSquareOutIcon size={13} aria-hidden />} onClick={() => void api.openUrl(EXPORTIFY)}>
            Open Exportify
          </Button>
        }
      >
        {problem.message.split(/(?<=\.)\s/)[0]}{" "}
        {problem.help ||
          "Export the playlist with Exportify (exportify.app): sign in with Spotify, press Export next to the playlist, then drop the .csv file here."}
      </Notice>
    );
  }
  if (problem.code === "save_the_page") {
    return (
      <Notice tone="warn" title="Save the 1001Tracklists page first">
        {problem.message}
      </Notice>
    );
  }
  return <Notice tone="bad">{problem.message}</Notice>;
}

/** The other tracklists a link gave (each comment, the description...): a small switcher. */
function Alternatives({ draft, busy, onPick }: { draft: Draft; busy: boolean; onPick: (n: number) => void }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const alts = draft.alternatives;
  function onKey(e: React.KeyboardEvent, i: number) {
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = (i + step + alts.length) % alts.length;
    refs.current[next]?.focus();
    onPick(alts[next].pick);
  }
  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs font-medium text-fg-2">
        {alts.length} tracklists found. {busy ? "Switching..." : "Pick another if this one looks wrong."}
      </p>
      <div role="radiogroup" aria-label="Tracklists found" className="flex flex-wrap gap-1.5">
        {alts.map((a, i) => {
          const on = a.pick === draft.picked;
          return (
            <button
              key={a.pick}
              ref={(el) => {
                refs.current[i] = el;
              }}
              type="button"
              role="radio"
              aria-checked={on}
              tabIndex={on ? 0 : -1}
              disabled={busy}
              onClick={() => onPick(a.pick)}
              onKeyDown={(e) => onKey(e, i)}
              title={alternativeLabel(a)}
              className={`inline-flex h-7 max-w-full items-center gap-2 rounded-control border px-2.5 text-xs disabled:opacity-60 ${
                on ? "border-accent-fg/60 bg-selected text-fg" : "border-line text-fg-2 hover:bg-hover hover:text-fg"
              }`}
            >
              <span className="max-w-[44ch] truncate">{alternativeLabel(a)}</span>
              <span className={`shrink-0 font-mono tabular text-2xs ${on ? "text-fg-2" : "text-fg-3"}`}>
                {a.count}
                {a.cues ? " timed" : ""}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
