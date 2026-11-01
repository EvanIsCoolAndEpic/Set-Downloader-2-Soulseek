import { useEffect, useMemo, useRef, useState } from "react";
import { CaretDownIcon, CaretUpIcon, StopIcon } from "@phosphor-icons/react";
import { api, errorText } from "../lib/api";
import { jobsNewestFirst, loadLog, upsertJob, useStore } from "../lib/store";
import { isActive, type Job, type SetResult } from "../lib/types";
import { Button, IconButton } from "./ui/Button";

/** The running job, slim; expands into its live log and the queue. */
export function JobBar({ onOpenSet }: { onOpenSet: (id: string) => void }) {
  const jobsMap = useStore((d) => d.jobs);
  const logs = useStore((d) => d.logs);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const logRef = useRef<HTMLDivElement>(null);

  const jobs = useMemo(() => jobsNewestFirst(jobsMap), [jobsMap]);
  const running = jobs.find((j) => j.state === "running" || j.state === "stopping") ?? null;
  const queued = jobs.filter((j) => j.state === "queued").reverse();
  const last = running ?? jobs.find((j) => !isActive(j)) ?? null;
  const log = last ? logs[last.id] : undefined;

  useEffect(() => {
    if (open && last && !logs[last.id]) void loadLog(last.id);
  }, [open, last?.id]);

  useEffect(() => {
    if (open && logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [open, log?.lastN]);

  if (!last) return null;

  async function stop(job: Job) {
    try {
      const res = await api.stopJob(job.id);
      upsertJob(res.job);
    } catch (e) {
      setError(errorText(e));
    }
  }

  const lastLine = log?.lines[log.lines.length - 1] ?? last.message;

  return (
    <footer className="col-span-2 border-t border-line bg-side">
      {open && (
        <div className="grid max-h-[40vh] grid-cols-[minmax(0,1fr)_260px] border-b border-line anim-fade">
          <div ref={logRef} className="overflow-auto px-4 py-3 font-mono text-[11px] leading-relaxed text-fg-2">
            {(log?.lines ?? []).map((l, i) => (
              <div key={i} className="whitespace-pre-wrap break-all">
                {l}
              </div>
            ))}
            {!log?.lines.length && <div className="text-fg-3">No output yet.</div>}
          </div>
          <div className="overflow-auto border-l border-line px-3 py-3">
            <h3 className="mb-2 text-xs font-medium text-fg-2">Up next</h3>
            {queued.length === 0 && <p className="text-xs text-fg-3">Nothing waiting.</p>}
            {queued.map((j) => (
              <div key={j.id} className="flex items-center justify-between gap-2 py-1 text-xs">
                <span className="truncate">{j.title}</span>
                <Button size="sm" variant="ghost" onClick={() => void stop(j)}>
                  Cancel
                </Button>
              </div>
            ))}
          </div>
        </div>
      )}
      <div className="flex h-11 items-center gap-3 px-4">
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <div className="flex min-w-0 items-baseline gap-2 text-xs">
            <span className="shrink-0 font-medium">{last.title}</span>
            <span className="shrink-0 text-fg-3">{stateText(last)}</span>
            <span className="truncate font-mono text-[11px] text-fg-3">{error ?? lastLine}</span>
          </div>
          {running && <div className="progress" aria-hidden />}
        </div>
        {last.set && !isActive(last) && (
          <Button size="sm" variant="ghost" onClick={() => onOpenSet(last.set!)}>
            Open set
          </Button>
        )}
        {running && (
          <Button size="sm" icon={<StopIcon size={13} weight="fill" aria-hidden />} onClick={() => void stop(running)} disabled={running.state === "stopping"}>
            {running.state === "stopping" ? "Stopping" : "Stop"}
          </Button>
        )}
        <IconButton label={open ? "Hide log" : "Show log"} size="sm" onClick={() => setOpen((o) => !o)}>
          {open ? <CaretDownIcon size={14} /> : <CaretUpIcon size={14} />}
        </IconButton>
      </div>
    </footer>
  );
}

function stateText(job: Job): string {
  if (job.state === "queued") return job.waiting === "soulseek" ? "waiting for Soulseek" : "queued";
  if (job.state === "running") return "running";
  if (job.state === "stopping") return "stopping";
  if (job.state === "stopped") return "stopped";
  if (job.state === "failed") return job.error ? `failed: ${job.error}` : "failed";
  const r = job.result as SetResult | null;
  if (job.kind === "download" && r && "found" in r) return `done, ${r.found} of ${r.total} found`;
  return "done";
}
