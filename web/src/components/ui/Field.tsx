import { forwardRef, useId, type InputHTMLAttributes, type ReactNode } from "react";
import { WarningCircleIcon } from "@phosphor-icons/react";

export const inputClass =
  "h-8 w-full min-w-0 rounded-control border border-field bg-input px-2.5 text-sm text-fg outline-none focus-visible:border-accent-fg focus-visible:outline-2 focus-visible:outline-offset-0 focus-visible:outline-accent-fg/40 disabled:opacity-45";

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string;
  help?: ReactNode;
  error?: string | null;
  mono?: boolean;
}

/** A labelled input: label above, help and error below. */
export const Field = forwardRef<HTMLInputElement, FieldProps>(function Field(
  { label, help, error, mono, className = "", id, ...rest },
  ref,
) {
  const auto = useId();
  const inputId = id ?? auto;
  const helpId = `${inputId}-help`;
  const errId = `${inputId}-err`;
  return (
    <div className={`flex min-w-0 flex-col gap-1.5 ${className}`}>
      <label htmlFor={inputId} className="text-xs font-medium text-fg-2">
        {label}
      </label>
      <input
        ref={ref}
        id={inputId}
        aria-invalid={error ? true : undefined}
        aria-describedby={[help ? helpId : "", error ? errId : ""].filter(Boolean).join(" ") || undefined}
        className={`${inputClass} ${mono ? "font-mono text-xs" : ""} ${error ? "border-bad" : ""}`}
        {...rest}
      />
      {help && (
        <p id={helpId} className="text-xs text-fg-3">
          {help}
        </p>
      )}
      <FieldError id={errId} message={error} />
    </div>
  );
});

export function FieldError({ message, id }: { message?: string | null; id?: string }) {
  if (!message) return null;
  return (
    <p id={id} role="alert" className="anim-fade flex items-start gap-1.5 text-xs text-bad">
      <WarningCircleIcon size={14} className="mt-px shrink-0" />
      <span>{message}</span>
    </p>
  );
}
