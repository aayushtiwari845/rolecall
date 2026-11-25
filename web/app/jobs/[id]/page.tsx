"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowUpRight, Bookmark, BookmarkCheck, Check, Sparkles } from "lucide-react";
import Link from "next/link";
import { use, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { JobRow } from "@/components/job-row";
import { useToast } from "@/components/toast";
import { Button, ButtonLink, Empty, Score, Spinner } from "@/components/ui";
import { ApiError, api, track } from "@/lib/api";
import { ago, FAMILY_LABEL, LEVEL_LABEL, REMOTE_LABEL, salary, sourceLabel } from "@/lib/format";
import type { JobDetail, JobItem } from "@/lib/types";

const FEATURE_LABEL: Record<string, string> = {
  skills: "Skills",
  level: "Level",
  role: "Role",
  location: "Location",
  recency: "Freshness",
  affinity: "Like your saves",
};

interface Fit {
  verdict: string;
  strengths: string[];
  gaps: string[];
  tips: string[];
}

function Breakdown({ m }: { m: JobItem }) {
  const rows = Object.entries(FEATURE_LABEL).map(([k, label]) => ({ k, label, v: m.features[k] ?? 0 }));
  return (
    <div className="grid gap-2.5">
      {rows.map((r) => (
        <div key={r.k} className="grid grid-cols-[7.5rem_1fr_2.5rem] items-center gap-3 text-sm">
          <span className="text-ink-2">{r.label}</span>
          <span className="h-2 overflow-hidden rounded-full bg-panel-2">
            <span
              className={`block h-full rounded-full ${r.v >= 0.75 ? "bg-green" : r.v >= 0.45 ? "bg-amber" : "bg-red"}`}
              style={{ width: `${Math.round(r.v * 100)}%`, transition: "width 700ms cubic-bezier(0.16,1,0.3,1)" }}
            />
          </span>
          <span className="text-right tabular-nums text-ink-2">{Math.round(r.v * 100)}</span>
        </div>
      ))}
    </div>
  );
}

function FitCheck({ jobId }: { jobId: string }) {
  const m = useMutation({ mutationFn: () => api.post<Fit>(`/jobs/${jobId}/explain`) });
  if (!m.data && !m.isPending)
    return (
      <div className="rounded-md border border-rule bg-panel p-5">
        <p className="font-semibold">Honest fit check</p>
        <p className="mt-1 text-sm text-ink-2">An AI reads this posting against your resume: strengths, gaps, what to highlight.</p>
        <Button className="mt-4" variant="outline" onClick={() => m.mutate()}>
          <Sparkles className="size-4" /> Check my fit
        </Button>
        {m.error && <p className="mt-3 text-sm text-red">{m.error instanceof ApiError ? m.error.message : "Something went wrong."}</p>}
      </div>
    );
  if (m.isPending)
    return (
      <div className="flex items-center gap-3 rounded-md border border-rule bg-panel p-5 text-ink-2">
        <Spinner /> Reading the posting against your resume…
      </div>
    );
  const d = m.data!;
  const block = (title: string, items: string[], tone: string) =>
    items.length > 0 && (
      <div>
        <p className={`label mb-2 ${tone}`}>{title}</p>
        <ul className="grid gap-2 text-sm leading-relaxed text-ink">
          {items.map((s) => (
            <li key={s}>{s}</li>
          ))}
        </ul>
      </div>
    );
  return (
    <div className="grid gap-5 rounded-md border border-rule bg-panel p-5">
      <p className="text-base font-semibold leading-snug">{d.verdict}</p>
      {block("Strengths", d.strengths, "text-green")}
      {block("Gaps", d.gaps, "text-red")}
      {block("Before you apply", d.tips, "text-amber-text")}
    </div>
  );
}

export default function JobPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const qc = useQueryClient();
  const toast = useToast();
  const { data: job, isLoading, error } = useQuery({ queryKey: ["job", id], queryFn: () => api.get<JobDetail>(`/jobs/${id}`) });
  const { data: similar } = useQuery({ queryKey: ["similar", id], queryFn: () => api.get<{ items: JobItem[] }>(`/jobs/${id}/similar`) });
  const [saved, setSaved] = useState<boolean | null>(null);
  const isSaved = saved ?? job?.saved ?? false;

  async function toggle(status = "saved") {
    if (!job) return;
    try {
      if (isSaved && status === "saved") {
        await api.del(`/applications/job/${job.id}`);
        setSaved(false);
      } else {
        await api.post("/applications", { job_id: job.id, status });
        setSaved(true);
        toast({ text: status === "applied" ? "Marked as applied in your tracker" : "Saved to your tracker" });
      }
      qc.invalidateQueries({ queryKey: ["applications"] });
    } catch {
      toast({ text: "Couldn't update the tracker.", tone: "error" });
    }
  }

  if (isLoading)
    return (
      <AppShell>
        <div className="grid min-h-[40vh] place-items-center">
          <Spinner className="size-6 text-ink-2" />
        </div>
      </AppShell>
    );
  if (error || !job)
    return (
      <AppShell>
        <Empty title="Role not found">It may have been taken down by the company.</Empty>
      </AppShell>
    );

  const m = job.match;
  const pay = salary(job.salary);
  const facts = [
    ["Level", job.seniority ? LEVEL_LABEL[job.seniority] : "Not stated"],
    ["Role", job.role_family ? FAMILY_LABEL[job.role_family] : "Software"],
    ["Where", [job.cities.join(", "), job.remote_type ? REMOTE_LABEL[job.remote_type] : null].filter(Boolean).join(" · ") || job.location || "Not stated"],
    ["Experience", job.min_yoe != null ? `${job.min_yoe}${job.max_yoe ? `–${job.max_yoe}` : "+"} years` : "Not stated"],
    ["Pay", pay ?? "Not listed"],
    ["Found", `${ago(job.first_seen_at)} on the ${sourceLabel(job.source)}`],
  ];

  return (
    <AppShell>
      <Link href="/feed" className="mb-6 inline-flex items-center gap-1.5 text-sm text-ink-2 hover:text-ink">
        <ArrowLeft className="size-4" /> Back to scorecard
      </Link>

      <div className="grid gap-10 lg:grid-cols-[1fr_22rem] lg:gap-14">
        <article className="min-w-0">
          <p className="text-lg text-ink-2">{job.company}</p>
          <h1 className="mt-1 text-[2rem] font-bold leading-tight tracking-tight md:text-[2.5rem]">{job.title}</h1>
          {job.status !== "open" && (
            <p className="mt-3 inline-block rounded-md bg-red/10 px-3 py-1 text-sm text-red">This role has closed</p>
          )}
          <div className="mt-6 flex flex-wrap gap-2">
            <ButtonLink
              href={job.apply_url}
              target="_blank"
              rel="noopener noreferrer"
              variant="primary"
              size="lg"
              onClick={() => track(job.id, "apply_click", { surface: "job" })}
            >
              Apply on {job.company}’s site <ArrowUpRight className="size-5" />
            </ButtonLink>
            <Button size="lg" variant="outline" onClick={() => toggle()}>
              {isSaved ? <BookmarkCheck className="size-5 text-pen" /> : <Bookmark className="size-5" />}
              {isSaved ? "Saved" : "Save"}
            </Button>
            <Button size="lg" variant="ghost" onClick={() => toggle("applied")}>
              I applied
            </Button>
          </div>

          <dl className="ruled mt-10 border-y border-rule">
            {facts.map(([k, v]) => (
              <div key={k} className="grid grid-cols-[8rem_1fr] gap-4 py-3 text-sm md:grid-cols-[10rem_1fr]">
                <dt className="text-ink-3">{k}</dt>
                <dd className="text-ink">{v}</dd>
              </div>
            ))}
          </dl>

          {job.summary && <p className="mt-8 max-w-[68ch] text-lg leading-relaxed text-ink">{job.summary}</p>}

          {job.skills.length > 0 && (
            <div className="mt-8">
              <p className="label mb-3 text-ink-2">Skills mentioned</p>
              <p className="flex flex-wrap gap-x-4 gap-y-2 text-sm">
                {job.skills.map((s) => {
                  const have = m?.matched_skills.includes(s);
                  return (
                    <span key={s} className={`inline-flex items-center gap-1 ${have ? "font-semibold text-green" : "text-ink-2"}`}>
                      {have && <Check className="size-3.5" aria-label="on your resume" />}
                      {s}
                    </span>
                  );
                })}
              </p>
            </div>
          )}

          <div className="mt-10 max-w-[72ch] whitespace-pre-line text-[0.9375rem] leading-7 text-ink-2">{job.description}</div>
        </article>

        <aside className="grid content-start gap-8 lg:sticky lg:top-24 lg:self-start">
          {m && (
            <div className="rounded-md border border-rule bg-panel p-5">
              <div className="flex items-center gap-5">
                <Score value={m.match} size="lg" />
                <div className="grid gap-1 text-sm">
                  {m.reasons.slice(0, 3).map((r) => (
                    <p key={r} className="text-ink">
                      {r}
                    </p>
                  ))}
                  {m.warnings.map((w) => (
                    <p key={w} className="text-red">
                      {w}
                    </p>
                  ))}
                </div>
              </div>
              <div className="mt-6 border-t border-rule pt-5">
                <Breakdown m={m} />
              </div>
              {m.missing_skills.length > 0 && (
                <p className="mt-5 text-sm text-ink-2">
                  Asks for skills not on your resume: <span className="text-ink">{m.missing_skills.join(", ")}</span>
                </p>
              )}
            </div>
          )}
          <FitCheck jobId={job.id} />
        </aside>
      </div>

      {similar && similar.items.length > 0 && (
        <section className="mt-16">
          <h2 className="score text-[2.25rem] font-extrabold uppercase">Similar roles</h2>
          <div className="ruled mt-4 border-y border-rule">
            {similar.items.map((j) => (
              <JobRow key={j.id} job={j} compact />
            ))}
          </div>
        </section>
      )}
    </AppShell>
  );
}
