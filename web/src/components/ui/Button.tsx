import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from "react";

type Variant = "primary" | "secondary" | "ghost";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-accent text-on-accent hover:bg-accent-hover",
  secondary: "bg-btn text-fg border border-line-strong hover:bg-btn-hover",
  ghost: "text-fg-2 hover:bg-hover hover:text-fg",
};

const SIZES: Record<Size, string> = {
  sm: "h-7 px-2.5 gap-1.5 text-xs",
  md: "h-8 px-3 gap-2 text-sm",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
}

/** The one button. Pressing it nudges it down a little (transform only). */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", icon, className = "", children, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={`inline-flex shrink-0 items-center justify-center whitespace-nowrap rounded-control font-medium transition-transform duration-100 active:translate-y-px disabled:pointer-events-none disabled:opacity-45 ${VARIANTS[variant]} ${SIZES[size]} ${className}`}
      {...rest}
    >
      {icon}
      {children}
    </button>
  );
});

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  size?: Size;
  children: ReactNode;
}

/** A square button with only an icon; label is its accessible name and tooltip. */
export function IconButton({ label, size = "md", className = "", children, ...rest }: IconButtonProps) {
  const box = size === "sm" ? "size-7" : "size-8";
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={`inline-flex shrink-0 items-center justify-center rounded-control text-fg-2 transition-transform duration-100 hover:bg-hover hover:text-fg active:translate-y-px disabled:pointer-events-none disabled:opacity-45 ${box} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}
