/** An on/off switch (role="switch"): the accent when on. */
export function Switch({
  checked,
  onChange,
  label,
  disabled,
  id,
}: {
  checked: boolean;
  onChange: (on: boolean) => void;
  label: string;
  disabled?: boolean;
  id?: string;
}) {
  return (
    <button
      id={id}
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-[18px] w-8 shrink-0 items-center rounded-control border transition-colors duration-150 disabled:opacity-45 ${
        checked ? "border-accent bg-accent" : "border-field bg-input"
      }`}
    >
      <span
        aria-hidden
        className={`absolute size-3 rounded-inner transition-transform duration-150 ease-out ${
          checked ? "translate-x-[15px] bg-on-accent" : "translate-x-[2px] bg-fg-3"
        }`}
      />
    </button>
  );
}
