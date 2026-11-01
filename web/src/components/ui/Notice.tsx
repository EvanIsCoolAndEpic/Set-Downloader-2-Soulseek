import type { ReactNode } from "react";
import { InfoIcon, WarningCircleIcon, XCircleIcon } from "@phosphor-icons/react";

type Tone = "info" | "warn" | "bad";

const TONES: Record<Tone, { box: string; icon: string; Icon: typeof InfoIcon }> = {
  info: { box: "border-line bg-side", icon: "text-fg-2", Icon: InfoIcon },
  warn: {
    box: "border-[color-mix(in_oklab,var(--warn)_30%,var(--bg))] bg-[color-mix(in_oklab,var(--warn)_7%,var(--bg))]",
    icon: "text-warn",
    Icon: WarningCircleIcon,
  },
  bad: {
    box: "border-[color-mix(in_oklab,var(--bad)_30%,var(--bg))] bg-[color-mix(in_oklab,var(--bad)_7%,var(--bg))]",
    icon: "text-bad",
    Icon: XCircleIcon,
  },
};

/** An inline message in plain words, with an optional action. */
export function Notice({
  tone = "info",
  title,
  children,
  action,
  className = "",
}: {
  tone?: Tone;
  title?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const t = TONES[tone];
  return (
    <div
      role={tone === "info" ? "status" : "alert"}
      className={`flex items-start gap-3 rounded-panel border px-3.5 py-3 ${t.box} ${className}`}
    >
      <t.Icon size={16} className={`mt-px shrink-0 ${t.icon}`} />
      <div className="min-w-0 flex-1 text-sm">
        {title && <p className="font-medium text-fg">{title}</p>}
        {children && <div className={`text-fg-2 ${title ? "mt-0.5" : ""}`}>{children}</div>}
      </div>
      {action && <div className="shrink-0 self-center">{action}</div>}
    </div>
  );
}
