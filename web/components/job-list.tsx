"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { track } from "@/lib/api";
import { useHotkeys } from "@/lib/hooks";
import { useJobActions } from "@/lib/job-actions";
import type { JobItem } from "@/lib/types";
import { JobRow } from "./job-row";
import { Button, Spinner } from "./ui";

interface Props {
  jobs: JobItem[];
  setJobs: (fn: (jobs: JobItem[]) => JobItem[]) => void;
  surface: "feed" | "search";
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
  query?: string;
}

/** A keyboard-driven scorecard: j/k to move, s to save, d to hide, o to open. */
export function JobList({ jobs, setJobs, surface, hasMore, loadingMore, onLoadMore, query }: Props) {
  const [focus, setFocus] = useState(-1);
  const [gone, setGone] = useState<Set<string>>(new Set());
  const rows = useRef<(HTMLElement | null)[]>([]);
  const sentinel = useRef<HTMLDivElement>(null);
  const router = useRouter();
  const { toggleSave, dismiss } = useJobActions(setJobs, surface);

  const doDismiss = (job: JobItem) => {
    setGone((g) => new Set(g).add(job.id));
    dismiss(
      job,
      (id) => setJobs((js) => js.filter((j) => j.id !== id)),
      (restored) => {
        setGone((g) => {
          const n = new Set(g);
          n.delete(restored.id);
          return n;
        });
        setJobs((js) => (js.some((j) => j.id === restored.id) ? js : [restored, ...js]));
      },
    );
  };

  const move = (d: number) =>
    setFocus((f) => {
      const n = Math.max(0, Math.min(jobs.length - 1, f + d));
      rows.current[n]?.scrollIntoView({ block: "nearest", behavior: "smooth" });
      rows.current[n]?.focus({ preventScroll: true });
      return n;
    });

  const current = focus >= 0 ? jobs[focus] : undefined;
  useHotkeys(
    {
      j: () => move(1),
      k: () => move(-1),
      ArrowDown: () => move(1),
      ArrowUp: () => move(-1),
      s: () => current && toggleSave(current),
      d: () => current && doDismiss(current),
      o: () => current && router.push(`/jobs/${current.id}`),
      Enter: () => current && router.push(`/jobs/${current.id}`),
    },
    [jobs, focus, current],
  );

  useEffect(() => {
    const el = sentinel.current;
    if (!el || !hasMore) return;
    const io = new IntersectionObserver((e) => e[0].isIntersecting && !loadingMore && onLoadMore(), { rootMargin: "600px" });
    io.observe(el);
    return () => io.disconnect();
  }, [hasMore, loadingMore, onLoadMore]);

  return (
    <div>
      <div className="ruled border-y border-rule">
        {jobs.map((j, i) => (
          <JobRow
            key={j.id}
            ref={(el) => {
              rows.current[i] = el;
            }}
            job={j}
            focused={i === focus}
            dismissed={gone.has(j.id)}
            onSave={() => toggleSave(j)}
            onDismiss={() => doDismiss(j)}
            onOpen={() => track(j.id, "click", { surface, position: i, query })}
          />
        ))}
      </div>
      <div ref={sentinel} className="flex justify-center py-8">
        {loadingMore ? (
          <Spinner className="text-ink-2" />
        ) : hasMore ? (
          <Button variant="ghost" onClick={onLoadMore}>
            Load more roles
          </Button>
        ) : jobs.length > 0 ? (
          <p className="text-sm text-ink-3">That’s everything matching right now. New roles arrive every few hours.</p>
        ) : null}
      </div>
    </div>
  );
}

export function KeysHelp() {
  const keys = [
    ["j / k", "next / previous"],
    ["s", "save to tracker"],
    ["d", "not for me"],
    ["o", "open role"],
  ];
  return (
    <dl className="grid grid-cols-[3.5rem_1fr] gap-x-3 gap-y-1.5 text-sm">
      {keys.map(([k, v]) => (
        <div key={k} className="contents">
          <dt>
            <kbd className="rounded border border-rule-strong bg-panel px-1.5 py-0.5 font-sans text-xs text-ink">{k}</kbd>
          </dt>
          <dd className="text-ink-2">{v}</dd>
        </div>
      ))}
    </dl>
  );
}
