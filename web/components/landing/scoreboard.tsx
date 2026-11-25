"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { api } from "@/lib/api";
import { ago, LEVEL_LABEL, num } from "@/lib/format";
import { useStats } from "@/lib/hooks";
import type { LatestJob } from "@/lib/types";
import { ButtonLink } from "../ui";

function Plate({ value, label, delay = 0, big }: { value: number | undefined; label: string; delay?: number; big?: boolean }) {
  return (
    <div className="grid content-end gap-2 border-board-rule p-4 md:p-6 [&:not(:first-child)]:border-l">
      <span
        key={value === undefined ? "pending" : "ready"}
        className={`score flip-in font-extrabold text-chalk ${big ? "text-[4.5rem] md:text-[8rem]" : "text-[3.25rem] md:text-[5.25rem]"}`}
        style={{ animationDelay: `${delay}ms` }}
      >
        {value === undefined ? "–" : num(value)}
      </span>
      <span className="label text-chalk-2">{label}</span>
    </div>
  );
}

export function Scoreboard() {
  const { data: stats } = useStats();
  const updated = stats ? ago(stats.last_crawl) : null;
  return (
    <section className="board relative overflow-hidden rounded-md">
      <div className="flex items-center justify-between border-b border-board-rule px-4 py-3 md:px-6">
        <span className="label flex items-center gap-2 text-chalk-2">
          <span className="live-dot size-2 rounded-full bg-[#45dd8c]" aria-hidden />
          Live index{updated && ` · crawled ${updated}`}
        </span>
        <span className="label text-chalk-2">{stats ? `${num(stats.companies)} companies` : ""}</span>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-[1.4fr_1fr_1fr]">
        <div className="col-span-2 md:col-span-1">
          <Plate value={stats?.new_today} label="New roles in the last 24 hours" big />
        </div>
        <Plate value={stats?.india_jobs} label="In India or remote-India" delay={120} />
        <Plate value={stats?.early_career_jobs} label="Internship & new grad" delay={240} />
      </div>
      <div className="grid grid-cols-2 border-t border-board-rule md:grid-cols-[1.4fr_1fr_1fr]">
        <div className="col-span-2 flex items-center px-4 py-4 md:col-span-1 md:px-6">
          <p className="text-sm text-chalk-2">
            <span className="score text-2xl font-bold text-chalk">{stats ? num(stats.open_jobs) : "–"}</span> open tech roles,
            checked every few hours
          </p>
        </div>
        <div className="border-board-rule px-4 py-4 md:border-l md:px-6">
          <p className="text-sm text-chalk-2">
            <span className="score text-2xl font-bold text-chalk">{stats ? num(stats.new_this_week) : "–"}</span> this week
          </p>
        </div>
        <div className="border-l border-board-rule px-4 py-4 md:px-6">
          <p className="text-sm text-chalk-2">
            <span className="score text-2xl font-bold text-chalk">{stats ? num(stats.sources) : "–"}</span> live boards
          </p>
        </div>
      </div>
    </section>
  );
}

export function Commentary({ limit = 12 }: { limit?: number }) {
  const { data } = useQuery({
    queryKey: ["commentary", limit],
    queryFn: () => api.get<{ items: LatestJob[] }>(`/commentary?limit=${limit}`),
    refetchInterval: 60_000,
  });
  const items = data?.items ?? [];
  return (
    <section aria-label="Just posted" className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-rule pb-3">
        <h2 className="label flex items-center gap-2 text-ink-2">
          <span className="live-dot size-2 rounded-full bg-green" aria-hidden />
          Just posted
        </h2>
        <span className="text-xs text-ink-3">updates every minute</span>
      </div>
      <ol className="ruled flex-1">
        {items.length === 0 &&
          Array.from({ length: 8 }).map((_, i) => (
            <li key={i} className="py-3">
              <div className="h-4 w-3/4 animate-pulse rounded bg-panel-2" />
            </li>
          ))}
        {items.map((j, i) => (
          <li key={j.id} className="ball-in grid grid-cols-[2.4rem_1fr] gap-3 py-3" style={{ animationDelay: `${i * 60}ms` }}>
            <span className="score pt-0.5 text-lg font-bold text-ink-3">{String(i + 1).padStart(2, "0")}</span>
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-ink">{j.title}</p>
              <p className="truncate text-xs text-ink-2">
                {j.company} · {j.location || "Location n/a"}
                {j.seniority && ` · ${LEVEL_LABEL[j.seniority]}`} · {ago(j.first_seen_at)}
              </p>
            </div>
          </li>
        ))}
      </ol>
      <ButtonLink href="/login" variant="ghost" size="sm" className="mt-3 self-start px-0 text-ink hover:bg-transparent hover:underline">
        See which ones fit you <ArrowRight className="size-4" />
      </ButtonLink>
    </section>
  );
}
