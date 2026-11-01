import { useCallback, useEffect, useRef, useState } from "react";
import { getToken } from "./lib/api";
import { isAudioFile } from "./lib/format";
import { boot, useStore } from "./lib/store";
import { FixPanel } from "./components/FixPanel";
import { JobBar } from "./components/JobBar";
import { NewSet } from "./components/NewSet";
import { SetView, type TrackFilter } from "./components/SetView";
import { Settings } from "./components/Settings";
import { Sidebar } from "./components/Sidebar";
import { Notice } from "./components/ui/Notice";

export type View = { kind: "new" } | { kind: "settings" } | { kind: "set"; id: string };

export function App() {
  const conn = useStore((d) => d.conn);
  const bootError = useStore((d) => d.bootError);
  const sets = useStore((d) => d.sets);
  const tracks = useStore((d) => d.tracks);
  const [view, setView] = useState<View | null>(null);
  const [filters, setFilters] = useState<Record<string, TrackFilter>>({});
  const [selected, setSelected] = useState<number | null>(null);
  const [fixRow, setFixRow] = useState<number | null>(null);
  const [closing, setClosing] = useState(false);
  const [dropped, setDropped] = useState<{ file: File; nonce: number } | null>(null);
  const closeTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    void boot();
  }, []);

  // First view: the newest set, or New set when there are none
  useEffect(() => {
    if (view || !sets) return;
    setView(sets.length ? { kind: "set", id: sets[0].id } : { kind: "new" });
  }, [sets, view]);

  const go = useCallback((next: View) => {
    setView(next);
    setSelected(null);
    setFixRow(null);
    setClosing(false);
  }, []);

  const closeFix = useCallback(() => {
    if (fixRow === null) return;
    setClosing(true);
    if (closeTimer.current) clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => {
      setFixRow(null);
      setClosing(false);
    }, 160);
  }, [fixRow]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "n") {
        e.preventDefault();
        go({ kind: "new" });
      } else if (e.key === "Escape" && fixRow !== null) {
        closeFix();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go, closeFix, fixRow]);

  const set = view?.kind === "set" ? (sets?.find((s) => s.id === view.id) ?? null) : null;
  const fixTrack =
    set && fixRow !== null ? (tracks[set.id]?.data?.tracks.find((t) => t.row === fixRow) ?? null) : null;

  // An audio file dropped anywhere while the fix panel is open goes to it
  const onDrop = (e: React.DragEvent) => {
    const file = e.dataTransfer.files[0];
    if (!file || !fixTrack || !isAudioFile(file.name)) return;
    e.preventDefault();
    setDropped({ file, nonce: Date.now() });
  };

  if (!getToken() || conn === "unauthorized") {
    return (
      <Shell>
        <Notice tone="bad" title="This page can't talk to Set Downloader">
          Open it from the Set Downloader app, which adds the key this page needs.
        </Notice>
      </Shell>
    );
  }
  if (bootError) {
    return (
      <Shell>
        <Notice tone="bad" title="Set Downloader isn't answering">
          {bootError.message}
        </Notice>
      </Shell>
    );
  }

  return (
    <div
      className="grid h-[100dvh] grid-cols-[248px_minmax(0,1fr)] grid-rows-[minmax(0,1fr)_auto] bg-bg text-fg"
      onDragOver={(e) => fixTrack && e.preventDefault()}
      onDrop={onDrop}
    >
      <Sidebar view={view ?? { kind: "new" }} onView={go} />
      <main className="flex min-h-0 min-w-0">
        <div className="min-w-0 flex-1 overflow-auto">
          {view?.kind === "new" && <NewSet onDone={(id) => go({ kind: "set", id })} onSettings={() => go({ kind: "settings" })} />}
          {view?.kind === "settings" && <Settings />}
          {view?.kind === "set" && set && (
            <SetView
              set={set}
              filter={filters[set.id]}
              onFilter={(f) => setFilters((m) => ({ ...m, [set.id]: f }))}
              selectedRow={selected}
              onSelect={setSelected}
              onOpen={(row) => {
                setSelected(row);
                setFixRow(row);
                setClosing(false);
              }}
              onSettings={() => go({ kind: "settings" })}
            />
          )}
          {view?.kind === "set" && !set && sets && (
            <div className="p-8 text-sm text-fg-2">That set isn't in the music folder anymore.</div>
          )}
        </div>
        {set && fixTrack && (
          <FixPanel
            key={`${set.id}:${fixTrack.row}`}
            setId={set.id}
            hasRecording={!!set.recording}
            track={fixTrack}
            closing={closing}
            onClose={closeFix}
            onSettings={() => go({ kind: "settings" })}
            dropped={dropped}
          />
        )}
      </main>
      <JobBar onOpenSet={(id) => go({ kind: "set", id })} />
    </div>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid h-[100dvh] place-items-center bg-bg p-8 text-fg">
      <div className="w-full max-w-md">{children}</div>
    </div>
  );
}
