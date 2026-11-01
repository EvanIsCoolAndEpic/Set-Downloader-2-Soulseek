import { GearIcon, PlusIcon, WarningCircleIcon } from "@phosphor-icons/react";
import { useStore } from "../lib/store";
import type { SetSummary } from "../lib/types";
import { Button } from "./ui/Button";
import { Bar, skeletonWidth } from "./ui/Skeleton";
import type { View } from "../App";

interface Props {
  view: View;
  onView: (view: View) => void;
}

export function Sidebar({ view, onView }: Props) {
  const sets = useStore((d) => d.sets);
  const setsError = useStore((d) => d.setsError);
  const state = useStore((d) => d.state);
  const needsSetup = !!state && (state.login.source === "none" || !state.sockseek.found);

  return (
    <nav aria-label="Sets" className="flex min-h-0 flex-col border-r border-line bg-side">
      <div className="flex items-center justify-between gap-2 px-4 pt-4 pb-3">
        <span className="text-sm font-semibold tracking-tight text-fg">Set Downloader</span>
        <Button
          size="sm"
          icon={<PlusIcon size={14} />}
          onClick={() => onView({ kind: "new" })}
          aria-keyshortcuts="Meta+N"
          title="New set (Cmd+N)"
          className={view.kind === "new" ? "border-accent-fg/50" : ""}
        >
          New set
        </Button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-2">
        {sets === null && !setsError && <SetsSkeleton />}
        {setsError && sets === null && <p className="px-2 py-2 text-xs text-bad">{setsError}</p>}
        {sets && sets.length === 0 && (
          <p className="px-2 py-2 text-xs text-fg-3">No sets yet. Downloaded sets show up here.</p>
        )}
        {sets && sets.length > 0 && (
          <ul className="flex flex-col gap-px">
            {sets.map((s) => (
              <li key={s.id}>
                <SetItem set={s} selected={view.kind === "set" && view.id === s.id} onSelect={() => onView({ kind: "set", id: s.id })} />
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="border-t border-line p-2">
        <button
          type="button"
          onClick={() => onView({ kind: "settings" })}
          aria-current={view.kind === "settings" ? "page" : undefined}
          className={`flex h-8 w-full items-center gap-2 rounded-control px-2 text-sm ${
            view.kind === "settings" ? "bg-selected text-fg" : "text-fg-2 hover:bg-hover hover:text-fg"
          }`}
        >
          <GearIcon size={16} aria-hidden />
          <span className="flex-1 text-left">Settings</span>
          {needsSetup && (
            <span className="flex items-center gap-1 text-xs text-warn">
              <WarningCircleIcon size={14} aria-hidden />
              {state!.login.source === "none" ? "Login needed" : "sockseek missing"}
            </span>
          )}
        </button>
      </div>
    </nav>
  );
}

function SetItem({ set, selected, onSelect }: { set: SetSummary; selected: boolean; onSelect: () => void }) {
  const busy = set.busy === "running" ? "Downloading" : set.busy === "queued" ? "Queued" : null;
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-current={selected ? "page" : undefined}
      className={`flex w-full flex-col gap-0.5 rounded-control px-2.5 py-2 text-left ${
        selected ? "bg-selected" : "hover:bg-hover"
      }`}
    >
      <span className="line-clamp-2 text-sm leading-[18px] font-medium text-fg">{set.title || set.name}</span>
      <span className="flex items-center gap-2 text-xs">
        {set.error ? (
          <span className="truncate text-bad">Can't read this set</span>
        ) : set.pending ? (
          <span className="text-fg-3">First download</span>
        ) : (
          <span className="font-mono tabular text-fg-2" aria-label={`${set.found} of ${set.total} tracks have a file`}>
            {set.found}/{set.total}
          </span>
        )}
        {busy && <span className={`ml-auto ${set.busy === "running" ? "text-accent-fg" : "text-fg-3"}`}>{busy}</span>}
      </span>
    </button>
  );
}

function SetsSkeleton() {
  return (
    <ul aria-label="Loading sets" className="flex flex-col gap-px">
      {Array.from({ length: 5 }, (_, i) => (
        <li key={i} className="flex flex-col gap-2 px-2.5 py-2.5">
          <Bar w={skeletonWidth(i + 2)} h={10} />
          <Bar w={28} h={8} />
        </li>
      ))}
    </ul>
  );
}
