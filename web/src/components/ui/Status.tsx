import {
  CheckCircleIcon,
  ClockIcon,
  DownloadSimpleIcon,
  MinusCircleIcon,
  WarningCircleIcon,
  WarningIcon,
} from "@phosphor-icons/react";
import type { StatusText, Tone } from "../../lib/format";

export const TONE_TEXT: Record<Tone, string> = {
  ok: "text-ok",
  warn: "text-warn",
  bad: "text-bad",
  work: "text-accent-fg",
  muted: "text-fg-3",
};

/** A track's status: icon, label in its state colour, and the reason in quiet text. */
export function StatusLabel({ status, className = "" }: { status: StatusText & { queued?: boolean }; className?: string }) {
  const Icon =
    status.tone === "ok"
      ? CheckCircleIcon
      : status.tone === "warn"
        ? status.label === "Missing"
          ? WarningCircleIcon
          : WarningIcon
        : status.tone === "work"
          ? status.queued
            ? ClockIcon
            : DownloadSimpleIcon
          : MinusCircleIcon;
  return (
    <span className={`flex min-w-0 items-center gap-1.5 ${className}`} title={status.full}>
      <Icon size={15} className={`shrink-0 ${TONE_TEXT[status.tone]}`} aria-hidden />
      <span className={`shrink-0 ${TONE_TEXT[status.tone]}`}>{status.label}</span>
      {status.detail && <span className="truncate text-fg-3">{status.detail}</span>}
    </span>
  );
}
