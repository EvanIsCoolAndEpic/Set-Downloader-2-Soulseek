import { useRef, useState } from "react";
import { ArrowLeftIcon, DownloadSimpleIcon, FileArrowUpIcon } from "@phosphor-icons/react";
import { api, errorText } from "../lib/api";
import { duration, isTracklistFile, limitText, plural, MASHUP_HELP, MASHUP_LABELS } from "../lib/format";
import { refreshSetsSoon, upsertJob, useStore } from "../lib/store";
import type { Draft, Mashups } from "../lib/types";
import { Button } from "./ui/Button";
import { Notice } from "./ui/Notice";
import { Segmented } from "./ui/Segmented";

interface Props {
  onDone: (setId: string) => void;
  onSettings: () => void;
}

/** A new set: drop a saved 1001Tracklists page or paste a tracklist, check what downloads, go. */
export function NewSet({ onDone, onSettings }: Props) {
  const state = useStore((d) => d.state);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [mashups, setMashups] = useState<Mashups>("components");
  const [text, setText] = useState("");
  const [busy, setBusy] = useState<"reading" | "starting" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [over, setOver] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function read(make: () => Promise<Draft>) {
    setBusy("reading");
    setError(null);
    try {
      const d = await make();
      setDraft(d);
      setMashups(d.mashups);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(null);
    }
  }

  function readFile(file: File | undefined) {
    if (!file) return;
    if (!isTracklistFile(file.name)) {
      setError("That isn't a tracklist. Drop a saved 1001Tracklists page (.html) or a .txt tracklist.");
      return;
    }
    void read(() => api.draftFromFile(file));
  }

  async function start() {
    if (!draft) return;
    setBusy("starting");
    setError(null);
    try {
      const { job } = await api.downloadDraft(draft.id, mashups);
      upsertJob(job);
      refreshSetsSoon(0);
      onDone(job.set ?? draft.set);
    } catch (e) {
      setError(errorText(e));
      setBusy(null);
    }
  }

  const needsLogin = state?.login.source === "none";
  const noSockseek = state && !state.sockseek.found;

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
            <h1 className="truncate text-xl font-semibold tracking-tight">{draft.title}</h1>
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
            {needsLogin ? "Downloads need a Soulseek account." : "Set Downloader needs sockseek to download."}
          </Notice>
        )}
        {error && <Notice tone="bad">{error}</Notice>}

        <ol className="flex flex-col">
          {draft.tracks.map((t) => {
            const on = t.downloads[mashups];
            return (
              <li
                key={t.row}
                className={`grid grid-cols-[3rem_minmax(0,1fr)_4rem] items-center gap-3 rounded-control px-2 py-1.5 text-sm ${on ? "" : "text-fg-3"}`}
              >
                <span className="font-mono text-xs tabular text-fg-3">{t.number || "w/"}</span>
                <span className="truncate">
                  {t.display}
                  {!on && <span className="ml-2 text-xs">{t.unidentified ? "unidentified" : "not downloaded"}</span>}
                </span>
                <span className="text-right font-mono text-xs tabular text-fg-3">{duration(t.duration)}</span>
              </li>
            );
          })}
        </ol>
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5 px-8 py-10">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">New set</h1>
        <p className="mt-1 text-sm text-fg-2">Drop a saved 1001Tracklists page, or paste a tracklist.</p>
      </div>

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
        disabled={busy !== null}
        className={`flex flex-col items-center gap-2 rounded-panel border border-dashed px-6 py-12 text-center transition-colors ${
          over ? "border-accent-fg bg-selected" : "border-line-strong hover:bg-hover"
        }`}
      >
        <FileArrowUpIcon size={28} className="text-fg-3" aria-hidden />
        <span className="text-sm font-medium">{busy === "reading" ? "Reading the page" : "Drop the page here, or choose it"}</span>
        <span className="text-xs text-fg-3">
          In your browser, File &gt; Save Page As on the 1001Tracklists set page
          {state ? `, up to ${limitText(state.limits.page_bytes)}` : ""}
        </span>
      </button>
      <input
        ref={fileRef}
        type="file"
        accept=".html,.htm,.txt"
        className="hidden"
        onChange={(e) => {
          readFile(e.target.files?.[0]);
          e.target.value = "";
        }}
      />

      <div className="flex flex-col gap-2">
        <label htmlFor="paste" className="text-xs font-medium text-fg-2">
          Or paste a tracklist
        </label>
        <textarea
          id="paste"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={"01. Artist - Title\n02. Artist - Title"}
          rows={7}
          className="w-full rounded-control border border-field bg-input px-3 py-2 font-mono text-xs text-fg outline-none placeholder:text-fg-3 focus-visible:border-accent-fg focus-visible:outline-2 focus-visible:outline-accent-fg/40"
        />
        <div>
          <Button onClick={() => void read(() => api.draftFromText(text))} disabled={!text.trim() || busy !== null}>
            Read tracklist
          </Button>
        </div>
      </div>

      {error && <Notice tone="bad">{error}</Notice>}
    </div>
  );
}
