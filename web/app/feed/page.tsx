"use client";

import { useQuery } from "@tanstack/react-query";
import { SlidersHorizontal } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { AppShell, PageHead } from "@/components/app-shell";
import { JobList, KeysHelp } from "@/components/job-list";
import { ButtonLink, Empty, Skeleton, Toggle } from "@/components/ui";
import { api } from "@/lib/api";
import { num } from "@/lib/format";
import { usePagedJobs } from "@/lib/paged-jobs";
import type { Application, JobFilters, JobItem, Resume } from "@/lib/types";

const WINDOWS = [
  { label: "Any time", days: null },
  { label: "This week", days: 7 },
  { label: "Last 24h", days: 1 },
] as const;

interface FeedResponse {
  items: JobItem[];
  filters: JobFilters;
  has_profile: boolean;
}

function Innings() {
  const { data } = useQuery({
    queryKey: ["applications"],
    queryFn: () => api.get<{ items: Application[] }>("/applications"),
  });
  const apps = data?.items ?? [];
  const count = (s: string[]) => apps.filter((a) => s.includes(a.status)).length;
  const cells = [
    { n: count(["saved"]), l: "Saved" },
    { n: count(["applied", "oa"]), l: "Applied" },
    { n: count(["interview"]), l: "Interviews" },
    { n: count(["offer"]), l: "Offers" },
  ];
  return (
    <div className="board rounded-md">
      <p className="label border-b border-board-rule px-4 py-2.5 text-chalk-2">Your hunt so far</p>
      <div className="grid grid-cols-2">
        {cells.map((c, i) => (
          <div key={c.l} className={`px-4 py-3.5 ${i % 2 ? "border-l border-board-rule" : ""} ${i > 1 ? "border-t border-board-rule" : ""}`}>
            <p className="score text-[2.25rem] font-extrabold text-chalk">{c.n}</p>
            <p className="label mt-1 text-[0.6rem] text-chalk-2">{c.l}</p>
          </div>
        ))}
      </div>
      <Link href="/tracker" className="block border-t border-board-rule px-4 py-2.5 text-sm text-chalk-2 hover:text-chalk">
        Open tracker →
      </Link>
    </div>
  );
}

export default function FeedPage() {
  const { data: resumes } = useQuery({ queryKey: ["resumes"], queryFn: () => api.get<{ items: Resume[] }>("/resumes") });
  const [resumeId, setResumeId] = useState<string | null>(null);
  const [days, setDays] = useState<number | null>(null);
  const { jobs, setJobs, meta, loading, loadingMore, hasMore, loadMore, error } = usePagedJobs<Omit<FeedResponse, "items">>(
    ["feed", resumeId, days],
    (offset, limit) => api.post<FeedResponse>("/feed", { resume_id: resumeId, posted_within_days: days, limit, offset }),
  );
  const hasProfile = meta?.has_profile ?? true;

  const list = resumes?.items ?? [];
  const active = list.find((r) => r.id === resumeId) ?? list.find((r) => r.is_default) ?? list[0];

  return (
    <AppShell>
      <PageHead
        title="Your scorecard"
        sub={
          active ? (
            <>
              Ranked for <span className="font-medium text-ink">{active.label}</span>
              {active.headline ? ` · ${active.headline}` : ""}
            </>
          ) : (
            "Add a resume to rank roles for you. Until then you’re seeing your preferences only."
          )
        }
      >
        {list.length > 1 && (
          <label className="flex items-center gap-2 text-sm">
            <span className="text-ink-2">Resume</span>
            <select
              value={active?.id ?? ""}
              onChange={(e) => setResumeId(e.target.value)}
              className="h-9 rounded-md border border-rule-strong bg-panel px-2 text-sm text-ink"
            >
              {list.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
        )}
        <ButtonLink href="/settings#preferences" variant="ghost" size="sm">
          <SlidersHorizontal className="size-4" /> Preferences
        </ButtonLink>
      </PageHead>

      <div className="grid gap-10 lg:grid-cols-[1fr_17rem]">
        <div className="min-w-0">
          <div className="mb-4 flex flex-wrap items-center gap-1.5">
            {WINDOWS.map((w) => (
              <Toggle key={w.label} on={days === w.days} onClick={() => setDays(w.days)}>
                {w.label}
              </Toggle>
            ))}
            {!loading && (
              <span className="ml-auto text-sm text-ink-3">
                {num(jobs.length)}
                {hasMore ? "+" : ""} roles
              </span>
            )}
          </div>

          {error ? (
            <Empty title="No signal">Couldn’t load your scorecard. Check your connection and refresh.</Empty>
          ) : loading ? (
            <Skeleton rows={7} />
          ) : jobs.length === 0 ? (
            <Empty title="Nothing on the board yet">
              No open roles match your preferences{days ? " in that window" : ""}. Try widening the levels, cities or remote options in{" "}
              <Link href="/settings#preferences" className="text-ink underline">
                preferences
              </Link>
              .
            </Empty>
          ) : (
            <>
              {!hasProfile && (
                <p className="mb-4 rounded-md border border-amber/50 bg-amber/10 px-4 py-3 text-sm text-ink">
                  Upload a resume in{" "}
                  <Link href="/settings#resumes" className="font-semibold underline">
                    Settings
                  </Link>{" "}
                  and these scores will reflect your skills.
                </p>
              )}
              <JobList jobs={jobs} setJobs={setJobs} surface="feed" hasMore={hasMore} loadingMore={loadingMore} onLoadMore={loadMore} />
            </>
          )}
        </div>

        <aside className="hidden lg:block">
          <div className="sticky top-24 grid gap-8">
            <Innings />
            <div>
              <p className="label mb-3 text-ink-2">Keyboard</p>
              <KeysHelp />
            </div>
            <p className="text-sm leading-relaxed text-ink-3">
              Saving and hiding roles teaches your scorecard. Hidden roles stay hidden; similar ones drop lower.
            </p>
          </div>
        </aside>
      </div>
    </AppShell>
  );
}
