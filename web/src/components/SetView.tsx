import { useEffect, useMemo, useState } from "react";
import { ArrowClockwiseIcon, ArrowSquareOutIcon, DownloadSimpleIcon, FolderOpenIcon } from "@phosphor-icons/react";
import { api, ApiError, errorText } from "../lib/api";
import { haveFileText, needsAttention, when, MASHUP_LABELS } from "../lib/format";
import { loadTracks, useStore } from "../lib/store";
import { isActive, type Job, type SetSummary } from "../lib/types";
import { Button, IconButton } from "./ui/Button";
import { Notice } from "./ui/Notice";
import { Segmented } from "./ui/Segmented";
import { TrackList, TrackListSkeleton } from "./TrackList";
import { Bar } from "./ui/Skeleton";

export type TrackFilter = "attention" | "all";

interface Props {
  set: SetSummary;
  filter: TrackFilter | undefined;
  onFilter: (f: TrackFilter) => void;
  selectedRow: number | null;
  onSelect: (row: number) => void;
  onOpen: (row: number) => void;
  onSettings: () => void;
}

export function SetView({ set, filter, onFilter, selectedRow, onSelect, onOpen, onSettings }: Props) {
  const entry = useStore((d) => d.tracks[set.id]);
  const jobs = useStore((d) => d.jobs);
  const [actionError, setActionError] = useState<ApiError | null>(null);

  // Tracks are loaded when the set is opened (and again after its jobs end: see the store)
  useEffect(() => {
    setActionError(null);
    if (!set.pending) void loadTracks(set.id, true);
  }, [set.id, set.pending]);

  const download = useMemo(
    () => Object.values(jobs).find((j) => j.kind === "download" && j.set === set.id && isActive(j)) ?? null,
    [jobs, set.id],
  );
  const working = useMemo(() => {
    const m = new Map<number, Job>();
    for (const j of Object.values(jobs)) if (j.kind === "fix" && j.set === set.id && j.row != null && isActive(j)) m.set(j.row, j);
    return m;
  }, [jobs, set.id]);

  const data = entry?.data && entry.data.set === set.id ? entry.data : null;
  const selectable = useMemo(() => (data ? data.tracks.filter((t) => t.selectable) : []), [data]);
  const attention = useMemo(() => selectable.filter(needsAttention), [selectable]);
  const found = data ? data.found : set.found;
  const missing = data ? data.missing : set.missing;
  const effectiveFilter: TrackFilter = filter ?? (missing > 0 || attention.length > 0 ? "attention" : "all");
  const shown = effectiveFilter === "all" ? selectable : attention;
  const hasMashups = !!data?.tracks.some((t) => t.kind === "mashup");

  if (set.pending || entry?.errorCode === "not_ready") return <PendingSet set={set} job={download} />;

  async function retry() {
    setActionError(null);
    try {
      await api.retrySet(set.id);
    } catch (e) {
      setActionError(e instanceof ApiError ? e : new ApiError(0, "error", errorText(e)));
    }
  }

  async function reveal() {
    setActionError(null);
    try {
      await api.reveal({ set: set.id });
    } catch (e) {
      setActionError(e instanceof ApiError ? e : new ApiError(0, "error", errorText(e)));
    }
  }

  const retryLabel = download ? (download.state === "queued" ? "Queued" : "Downloading") : "Retry missing";

  return (
    <section aria-label={set.title} className="flex min-h-0 min-w-0 flex-1 flex-col">
      <header className="flex items-start gap-4 px-6 pt-5 pb-4">
        <div className="min-w-0 flex-1">
          <h1 className="selectable line-clamp-2 text-xl font-semibold tracking-tight text-fg">{set.title || set.name}</h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-2">
            <span className="tabular">{set.error ? "This set's page can't be read." : haveFileText(found, found + missing)}</span>
            {hasMashups && <span>Mashups: {MASHUP_LABELS[set.mashups].toLowerCase()}</span>}
            {set.updated && <span>Updated {when(set.updated)}</span>}
            {set.url && (
              <button
                type="button"
                onClick={() => void api.openUrl(set.url)}
                className="inline-flex items-center gap-1 rounded-sm text-accent-fg hover:underline"
              >
                1001Tracklists page
                <ArrowSquareOutIcon size={12} aria-hidden />
              </button>
            )}
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-2 pt-0.5">
          <IconButton label="Show in Finder" onClick={() => void reveal()}>
            <FolderOpenIcon size={16} />
          </IconButton>
          {(missing > 0 || download) && (
            <Button
              variant="primary"
              icon={download ? <DownloadSimpleIcon size={15} /> : <ArrowClockwiseIcon size={15} />}
              disabled={!!download}
              onClick={() => void retry()}
              title="Retrying only searches for what's still missing, then rebuilds the playlist in set order."
            >
              {retryLabel}
            </Button>
          )}
        </div>
      </header>

      {actionError && (
        <div className="px-6 pb-3">
          <Notice
            tone={actionError.code === "login_required" || actionError.code === "sockseek_missing" ? "warn" : "bad"}
            action={
              actionError.code === "login_required" || actionError.code === "sockseek_missing" ? (
                <Button size="sm" onClick={onSettings}>
                  Open settings
                </Button>
              ) : undefined
            }
          >
            {actionError.message}
          </Notice>
        </div>
      )}

      {set.error ? (
        <div className="px-6">
          <Notice tone="bad" title="This set can't be read">
            {set.error}
          </Notice>
        </div>
      ) : entry?.error && !data ? (
        <div className="px-6">
          <Notice
            tone="bad"
            title="Couldn't read the set's tracks"
            action={
              <Button size="sm" onClick={() => void loadTracks(set.id)}>
                Try again
              </Button>
            }
          >
            {entry.error}
          </Notice>
        </div>
      ) : !data ? (
        <>
          <Toolbar />
          <TrackListSkeleton rows={Math.min(Math.max(set.total, 6), 12)} />
        </>
      ) : (
        <>
          <Toolbar>
            <Segmented
              size="sm"
              label="Show"
              value={effectiveFilter}
              onChange={onFilter}
              options={[
                { value: "attention", label: "Missing and fixed", count: attention.length },
                { value: "all", label: "All tracks", count: selectable.length },
              ]}
            />
            <p className="min-w-0 truncate text-xs text-fg-3">
              {missing > 0
                ? "Pick a track to search Soulseek with other words, or to use a file of your own."
                : "Pick a track to replace a wrong version."}
            </p>
          </Toolbar>
          <TrackList
            tracks={shown}
            selectedRow={selectedRow}
            onSelect={onSelect}
            onOpen={onOpen}
            working={working}
            emptyText="Nothing missing or fixed: every track has a file."
          />
        </>
      )}
    </section>
  );
}

function Toolbar({ children }: { children?: React.ReactNode }) {
  return (
    <div className="flex h-11 shrink-0 items-center gap-4 border-t border-line px-6">
      {children ?? (
        <>
          <Bar w={220} h={20} className="rounded-control" />
        </>
      )}
    </div>
  );
}

/** A new set whose first download is still running: its folder isn't complete yet. */
function PendingSet({ set, job }: { set: SetSummary; job: Job | null }) {
  const last = useStore((d) => (job ? d.logs[job.id]?.lines.at(-1) : undefined));
  const waiting = job?.state === "queued";
  return (
    <section aria-label={set.title} className="flex min-h-0 min-w-0 flex-1 flex-col">
      <header className="px-6 pt-5 pb-4">
        <h1 className="selectable line-clamp-2 text-xl font-semibold tracking-tight text-fg">{set.title}</h1>
        <p className="mt-1.5 text-xs text-fg-2 tabular">{set.total} tracks to download</p>
      </header>
      <div className="flex flex-1 flex-col items-center justify-center gap-3 border-t border-line px-6 pb-16 text-center">
        <DownloadSimpleIcon size={28} className="text-fg-3" aria-hidden />
        <div>
          <p className="text-base font-medium text-fg">{waiting ? "Waiting to start" : "Downloading the set"}</p>
          <p className="mt-1 max-w-[46ch] text-sm text-fg-2">
            {waiting
              ? job?.waiting === "soulseek"
                ? "Another Soulseek job is running. This one starts when it finishes."
                : "This starts in a moment."
              : "The tracks show up here when the first download finishes."}
          </p>
        </div>
        {job && !waiting && <div className="progress mt-1 w-40" role="progressbar" aria-label="Downloading" />}
        {last && <p className="max-w-[60ch] truncate font-mono text-xs text-fg-3">{last}</p>}
      </div>
    </section>
  );
}
