import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { ArrowElbowDownRightIcon } from "@phosphor-icons/react";
import { baseName, fixAction, trackStatus, type StatusText } from "../lib/format";
import type { Job, Track } from "../lib/types";
import { StatusLabel } from "./ui/Status";
import { Bar, skeletonWidth } from "./ui/Skeleton";

// Number, track, status, file. The file column only shows when the list is wide enough.
const GRID =
  "grid grid-cols-[2.75rem_minmax(0,1.7fr)_minmax(9.5rem,1fr)] @3xl:grid-cols-[2.75rem_minmax(0,1.6fr)_minmax(10rem,1fr)_minmax(0,1fr)] items-center gap-x-3";

interface Props {
  tracks: Track[];
  selectedRow: number | null;
  onSelect: (row: number) => void;
  onOpen: (row: number) => void;
  /** Jobs changing a track's file (fixes, cuts, conversions) that are queued or running, by row. */
  working: Map<number, Job>;
  emptyText?: string;
}

/** The set's tracks: up/down moves, Enter opens the fix panel, a click does both. */
export function TrackList({ tracks, selectedRow, onSelect, onOpen, working, emptyText }: Props) {
  const listRef = useRef<HTMLDivElement>(null);

  // Keep the selected row in view as it moves
  useEffect(() => {
    if (selectedRow == null) return;
    const el = listRef.current?.querySelector<HTMLElement>(`[data-row="${selectedRow}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [selectedRow]);

  function onKeyDown(e: KeyboardEvent) {
    if (!tracks.length) return;
    const i = tracks.findIndex((t) => t.row === selectedRow);
    let next = -1;
    if (e.key === "ArrowDown") next = i < 0 ? 0 : Math.min(i + 1, tracks.length - 1);
    else if (e.key === "ArrowUp") next = i < 0 ? 0 : Math.max(i - 1, 0);
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tracks.length - 1;
    else if (e.key === "Enter" && i >= 0) {
      e.preventDefault();
      onOpen(tracks[i].row);
      return;
    }
    if (next >= 0) {
      e.preventDefault();
      onSelect(tracks[next].row);
    }
  }

  return (
    <div className="@container flex min-h-0 flex-1 flex-col">
      <div
        className={`${GRID} sticky top-0 z-10 border-b border-line bg-bg px-4 py-1.5 text-2xs font-medium text-fg-3`}
        aria-hidden
      >
        <span className="text-right">#</span>
        <span>Track</span>
        <span>Status</span>
        <span className="hidden @3xl:block">File</span>
      </div>
      {tracks.length === 0 ? (
        <p className="px-6 py-10 text-center text-sm text-fg-3">{emptyText ?? "No tracks."}</p>
      ) : (
        <div
          ref={listRef}
          role="listbox"
          aria-label="Tracks"
          tabIndex={0}
          aria-activedescendant={selectedRow != null ? `track-${selectedRow}` : undefined}
          onKeyDown={onKeyDown}
          onFocus={() => {
            if (selectedRow == null && tracks.length) onSelect(tracks[0].row);
          }}
          className="min-h-0 flex-1 overflow-y-auto px-2 py-1 outline-none focus-visible:outline-none [&:focus-visible_[aria-selected=true]]:outline-2 [&:focus-visible_[aria-selected=true]]:-outline-offset-2 [&:focus-visible_[aria-selected=true]]:outline-accent-fg"
        >
          {tracks.map((t) => (
            <TrackRow
              key={t.row}
              track={t}
              selected={t.row === selectedRow}
              job={working.get(t.row)}
              onClick={() => {
                onSelect(t.row);
                onOpen(t.row);
              }}
            />
          ))}
        </div>
      )}
    </div>
  );
}

const FIX_WORDS = { undo: "Undoing", pick: "Downloading", search: "Searching", own: "Copying" } as const;

function workingStatus(job: Job): StatusText & { queued: boolean } {
  const queued = job.state === "queued";
  const doing = job.kind === "cut" ? "Cutting" : job.kind === "finish" ? "Converting" : FIX_WORDS[fixAction(job.title)];
  const label = queued ? "Queued" : job.state === "stopping" ? "Stopping" : doing;
  return { tone: "work", label, detail: "", full: `${label}: ${job.title}`, queued };
}

function TrackRow({ track: t, selected, job, onClick }: { track: Track; selected: boolean; job?: Job; onClick: () => void }) {
  const status = job ? workingStatus(job) : trackStatus(t);
  const changed = useChanged(`${status.tone}:${status.label}:${status.detail}`);
  const isId = t.unidentified && !t.file;
  return (
    <div
      id={`track-${t.row}`}
      data-row={t.row}
      role="option"
      aria-selected={selected}
      onClick={onClick}
      className={`${GRID} h-8 rounded-control px-2 text-sm ${selected ? "bg-selected" : "hover:bg-hover"}`}
    >
      <span className="flex justify-end font-mono tabular text-xs text-fg-3">
        {t.kind === "component" ? (
          <ArrowElbowDownRightIcon size={14} aria-label="Part of the mashup above" />
        ) : (
          t.number
        )}
      </span>
      <span className="truncate" title={t.label ? `${t.display}  [${t.label}]` : t.display}>
        {isId ? (
          <span className="text-fg-3">{t.display}</span>
        ) : (
          <>
            <span className="text-fg-2">{t.artist}</span>
            <span className="text-fg-3"> - </span>
            <span className="font-medium text-fg">{t.title}</span>
          </>
        )}
      </span>
      <StatusLabel status={status} className={`text-xs ${changed ? "anim-rise" : ""}`} />
      <span className="hidden truncate font-mono text-xs text-fg-3 @3xl:block" title={t.file || undefined}>
        {t.file ? baseName(t.file) : ""}
      </span>
    </div>
  );
}

/** True for a moment after the value changes (not on first render): drives a row's status
 * change animation. */
function useChanged(value: string): boolean {
  const prev = useRef(value);
  const [on, setOn] = useState(false);
  useEffect(() => {
    if (prev.current === value) return;
    prev.current = value;
    setOn(true);
    const t = setTimeout(() => setOn(false), 260);
    return () => clearTimeout(t);
  }, [value]);
  return on;
}

export function TrackListSkeleton({ rows = 9 }: { rows?: number }) {
  return (
    <div className="@container flex min-h-0 flex-1 flex-col" aria-busy="true" aria-label="Loading tracks">
      <div className={`${GRID} border-b border-line px-4 py-1.5 text-2xs font-medium text-fg-3`} aria-hidden>
        <span className="text-right">#</span>
        <span>Track</span>
        <span>Status</span>
        <span className="hidden @3xl:block">File</span>
      </div>
      <div className="px-2 py-1">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className={`${GRID} h-8 px-2`}>
            <span className="flex justify-end">
              <Bar w={14} h={8} />
            </span>
            <Bar w={skeletonWidth(i)} />
            <Bar w={i % 3 === 1 ? 96 : 52} h={8} />
            <span className="hidden @3xl:block">
              <Bar w={skeletonWidth(i + 3)} h={8} />
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
