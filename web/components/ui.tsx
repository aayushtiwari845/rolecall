"use client";

import clsx from "clsx";
import Link from "next/link";
import { forwardRef } from "react";

/** Three stumps and two bails: the Rolecall mark. */
export function Stumps({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden className={className} fill="none">
      <path d="M5 4.5h6M13 4.5h6" stroke="var(--amber)" strokeWidth="2" strokeLinecap="round" />
      <path d="M6 7.5v13M12 7.5v13M18 7.5v13" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
    </svg>
  );
}

export function Wordmark({ className, href = "/" }: { className?: string; href?: string }) {
  return (
    <Link href={href} className={clsx("inline-flex items-center gap-1.5", className)} aria-label="Rolecall home">
      <Stumps className="size-6" />
      <span className="score text-[1.6rem] font-extrabold uppercase tracking-wide">Rolecall</span>
    </Link>
  );
}

type Variant = "primary" | "ghost" | "outline" | "danger" | "board";

const VARIANTS: Record<Variant, string> = {
  primary:
    "bg-amber text-amber-ink hover:brightness-105 active:brightness-95 shadow-[0_2px_0_rgb(0_0_0/0.25)] font-semibold",
  outline: "border border-rule-strong text-ink hover:bg-panel-2",
  ghost: "text-ink-2 hover:text-ink hover:bg-panel-2",
  danger: "border border-red/50 text-red hover:bg-red/10",
  board: "border border-board-rule text-chalk hover:bg-board-2",
};

export const Button = forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "lg" }
>(function Button({ variant = "outline", size = "md", className, ...props }, ref) {
  return (
    <button
      ref={ref}
      {...props}
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-md transition-[background,filter,color] duration-150 disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" && "h-8 px-3 text-sm",
        size === "md" && "h-10 px-4 text-sm",
        size === "lg" && "h-12 px-6 text-base",
        VARIANTS[variant],
        className,
      )}
    />
  );
});

export function ButtonLink({
  href,
  variant = "outline",
  size = "md",
  className,
  children,
  ...rest
}: { href: string; variant?: Variant; size?: "sm" | "md" | "lg"; className?: string; children: React.ReactNode } & Omit<
  React.AnchorHTMLAttributes<HTMLAnchorElement>,
  "href"
>) {
  const cls = clsx(
    "inline-flex items-center justify-center gap-2 rounded-md transition-[background,filter,color] duration-150",
    size === "sm" && "h-8 px-3 text-sm",
    size === "md" && "h-10 px-4 text-sm",
    size === "lg" && "h-12 px-6 text-base",
    VARIANTS[variant],
    className,
  );
  if (href.startsWith("http") || href.startsWith("/api/"))
    return (
      <a href={href} className={cls} {...rest}>
        {children}
      </a>
    );
  return (
    <Link href={href} className={cls} {...rest}>
      {children}
    </Link>
  );
}

/** A toggleable option in a set (filters, preferences). */
export function Toggle({
  on,
  onClick,
  children,
  className,
}: {
  on: boolean;
  onClick: () => void;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={clsx(
        "h-8 rounded-[3px] border px-2.5 text-sm transition-colors",
        on ? "border-ink bg-ink text-bg" : "border-rule-strong text-ink-2 hover:border-ink-3 hover:text-ink",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function ToggleSet<T extends string>({
  options,
  value,
  onChange,
  labels,
}: {
  options: readonly T[];
  value: T[];
  onChange: (v: T[]) => void;
  labels?: Partial<Record<T, string>>;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {options.map((o) => (
        <Toggle
          key={o}
          on={value.includes(o)}
          onClick={() => onChange(value.includes(o) ? value.filter((x) => x !== o) : [...value, o])}
        >
          {labels?.[o] ?? o}
        </Toggle>
      ))}
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="grid gap-2">
      <div className="flex items-baseline justify-between gap-4">
        <span className="label text-ink-2">{label}</span>
        {hint && <span className="text-xs text-ink-3">{hint}</span>}
      </div>
      {children}
    </div>
  );
}

export function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={clsx(
        "h-10 w-full rounded-md border border-rule-strong bg-panel px-3 text-sm text-ink outline-none transition-colors focus:border-amber",
        props.className,
      )}
    />
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      aria-label="Loading"
      role="status"
      className={clsx("inline-block size-4 animate-spin rounded-full border-2 border-current border-t-transparent", className)}
    />
  );
}

/** Hand-drawn pen ring, drawn around a saved role's score like a scorer circling a milestone. */
export function PenRing({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 100 70" className={clsx("pointer-events-none absolute", className)} aria-hidden fill="none">
      <path
        d="M52 6C27 4 6 15 5 33c-1 18 21 31 48 31 26 0 43-12 42-29C94 18 76 7 50 8c-12 .4-22 3-29 8"
        stroke="var(--pen)"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeDasharray="260"
        style={{ animation: "ring 650ms cubic-bezier(0.16,1,0.3,1)" }}
      />
    </svg>
  );
}

/** The match number, set like a batter's score. */
export function Score({ value, saved, size = "md" }: { value: number; saved?: boolean; size?: "sm" | "md" | "lg" }) {
  const tone = value >= 75 ? "text-green" : value >= 55 ? "text-ink" : "text-ink-3";
  return (
    <span className="relative inline-flex w-[3.2rem] flex-col items-center">
      <span
        className={clsx(
          "score font-extrabold",
          tone,
          size === "sm" && "text-[1.75rem]",
          size === "md" && "text-[2.6rem]",
          size === "lg" && "text-[4.5rem]",
        )}
      >
        {value}
      </span>
      <span className="label mt-1 text-[0.6rem] text-ink-3">match</span>
      {saved && <PenRing className="-inset-x-3 -inset-y-2.5 h-[130%] w-[150%]" />}
    </span>
  );
}

export function Empty({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <div className="grid place-items-center gap-3 border-y border-rule py-16 text-center">
      <p className="score text-3xl font-bold uppercase text-ink-2">{title}</p>
      {children && <div className="max-w-md text-sm text-ink-2">{children}</div>}
    </div>
  );
}

export function Skeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="ruled border-y border-rule" aria-busy>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-5 py-5">
          <div className="h-10 w-12 animate-pulse rounded bg-panel-2" />
          <div className="grid flex-1 gap-2">
            <div className="h-4 w-2/5 animate-pulse rounded bg-panel-2" />
            <div className="h-3 w-3/5 animate-pulse rounded bg-panel-2" />
          </div>
        </div>
      ))}
    </div>
  );
}
