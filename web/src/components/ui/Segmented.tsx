import { useRef, type KeyboardEvent, type ReactNode } from "react";

export interface SegmentOption<T extends string> {
  value: T;
  label: ReactNode;
  /** A count shown after the label, in mono. */
  count?: number;
  title?: string;
}

interface Props<T extends string> {
  value: T;
  options: SegmentOption<T>[];
  onChange: (value: T) => void;
  label: string;
  size?: "sm" | "md";
  disabled?: boolean;
}

/** A segmented control (a radio group): arrow keys move between the choices. */
export function Segmented<T extends string>({ value, options, onChange, label, size = "md", disabled }: Props<T>) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const height = size === "sm" ? "h-7" : "h-8";

  function onKey(e: KeyboardEvent, i: number) {
    const step = e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : e.key === "ArrowLeft" || e.key === "ArrowUp" ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = (i + step + options.length) % options.length;
    onChange(options[next].value);
    refs.current[next]?.focus();
  }

  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={`inline-flex items-stretch gap-0.5 rounded-control border border-line bg-side p-0.5 ${height} ${disabled ? "opacity-45" : ""}`}
    >
      {options.map((o, i) => {
        const on = o.value === value;
        return (
          <button
            key={o.value}
            ref={(el) => {
              refs.current[i] = el;
            }}
            type="button"
            role="radio"
            aria-checked={on}
            tabIndex={on ? 0 : -1}
            disabled={disabled}
            title={o.title}
            onClick={() => onChange(o.value)}
            onKeyDown={(e) => onKey(e, i)}
            className={`inline-flex items-center gap-1.5 rounded-inner px-2.5 text-xs font-medium whitespace-nowrap ${
              on ? "bg-panel text-fg shadow-pop" : "text-fg-2 hover:text-fg"
            }`}
          >
            {o.label}
            {o.count !== undefined && (
              <span className={`font-mono tabular text-2xs ${on ? "text-fg-2" : "text-fg-3"}`}>{o.count}</span>
            )}
          </button>
        );
      })}
    </div>
  );
}
