"use client";

import clsx from "clsx";
import { Bookmark, BookmarkCheck, ExternalLink, X } from "lucide-react";
import Link from "next/link";
import { forwardRef } from "react";
import { ago, LEVEL_LABEL, placeOf, salary } from "@/lib/format";
import type { JobItem } from "@/lib/types";
import { Score } from "./ui";

interface Props {
  job: JobItem;
  focused?: boolean;
  dismissed?: boolean;
  onSave?: () => void;
  onDismiss?: () => void;
  onOpen?: () => void;
  compact?: boolean;
  showScore?: boolean;
}

/**
 * One role as a scorecard row: score | role and the ball-by-ball reasons | level and pay | actions.
 * Every row shares the same column order and baseline so two roles compare at a glance.
 */
export const JobRow = forwardRef<HTMLElement, Props>(function JobRow(
  { job, focused, dismissed, onSave, onDismiss, onOpen, compact, showScore = true },
  ref,
) {
  const pay = salary(job.salary);
  return (
    <article
      ref={ref}
      tabIndex={-1}
      aria-label={`${job.title} at ${job.company}`}
      className={clsx(
        "group relative grid grid-cols-[auto_1fr] items-start gap-x-4 gap-y-2 py-4 outline-none transition-[opacity,background] duration-300 sm:grid-cols-[auto_1fr_auto] sm:gap-x-6",
        compact ? "py-3" : "md:py-5",
        focused && "bg-panel-2/70 [box-shadow:-12px_0_0_var(--panel-2),12px_0_0_var(--panel-2)]",
        dismissed && "opacity-40",
      )}
    >
      {showScore && (
        <div className="row-span-2 pt-0.5 sm:row-span-1">
          <Score value={job.match} saved={job.saved} size={compact ? "sm" : "md"} />
        </div>
      )}

      <div className={clsx("min-w-0", !showScore && "col-span-2 sm:col-span-1")}>
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <Link
            href={`/jobs/${job.id}`}
            onClick={onOpen}
            className="text-[1.0625rem] font-semibold leading-snug text-ink decoration-amber hover:underline"
          >
            {job.title}
          </Link>
        </div>
        <p className="mt-1 text-sm text-ink-2">
          <span className="font-medium text-ink">{job.company}</span>
          <span className="mx-1.5 text-ink-3">·</span>
          {placeOf(job)}
          {job.posted_at && (
            <>
              <span className="mx-1.5 text-ink-3">·</span>
              <time dateTime={job.posted_at}>{ago(job.posted_at)}</time>
            </>
          )}
        </p>
        {!compact && (job.reasons.length > 0 || job.warnings.length > 0) && (
          <ul className="mt-2.5 flex flex-wrap gap-x-4 gap-y-1 text-[0.8125rem] leading-snug">
            {job.reasons.slice(0, 3).map((r) => (
              <li key={r} className="flex items-baseline gap-1.5 text-ink-2">
                <span aria-hidden className="size-1.5 shrink-0 translate-y-[-1px] rounded-full bg-green" />
                {r}
              </li>
            ))}
            {job.warnings.slice(0, 2).map((w) => (
              <li key={w} className="flex items-baseline gap-1.5 text-red">
                <span aria-hidden className="size-1.5 shrink-0 translate-y-[-1px] rounded-full bg-red" />
                {w}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="col-span-2 flex items-center justify-between gap-4 sm:col-span-1 sm:flex-col sm:items-end sm:justify-start">
        <div className="flex items-baseline gap-3 text-right text-sm">
          {job.seniority && <span className="label text-ink-2">{LEVEL_LABEL[job.seniority]}</span>}
          {pay && <span className="font-medium tabular-nums text-amber-text">{pay}</span>}
        </div>
        <div className="flex items-center gap-1">
          {onSave && (
            <button
              onClick={onSave}
              aria-label={job.saved ? "Remove from saved" : "Save"}
              title={job.saved ? "Saved (s to unsave)" : "Save (s)"}
              className={clsx(
                "grid size-9 place-items-center rounded-md transition-colors hover:bg-panel-2",
                job.saved ? "text-pen" : "text-ink-2 hover:text-ink",
              )}
            >
              {job.saved ? <BookmarkCheck className="size-[18px]" /> : <Bookmark className="size-[18px]" />}
            </button>
          )}
          {onDismiss && (
            <button
              onClick={onDismiss}
              aria-label="Not for me"
              title="Not for me (d)"
              className="grid size-9 place-items-center rounded-md text-ink-2 transition-colors hover:bg-red/10 hover:text-red"
            >
              <X className="size-[18px]" />
            </button>
          )}
          <a
            href={job.url}
            target="_blank"
            rel="noopener noreferrer"
            onClick={onOpen}
            aria-label="Open original posting"
            title="Open posting"
            className="grid size-9 place-items-center rounded-md text-ink-2 transition-colors hover:bg-panel-2 hover:text-ink"
          >
            <ExternalLink className="size-[17px]" />
          </a>
        </div>
      </div>

      {dismissed && (
        <span
          aria-hidden
          className="pointer-events-none absolute left-0 right-0 top-1/2 h-[2px] origin-left bg-red"
          style={{ animation: "strike 380ms cubic-bezier(0.16,1,0.3,1) both" }}
        />
      )}
    </article>
  );
});
