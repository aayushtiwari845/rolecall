"use client";

import { Search as SearchIcon, X } from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { AppShell, PageHead } from "@/components/app-shell";
import { JobList } from "@/components/job-list";
import { Button, Empty, Field, Skeleton, Toggle, ToggleSet } from "@/components/ui";
import { api } from "@/lib/api";
import { CITIES, FAMILIES, FAMILY_LABEL, LEVEL_LABEL, LEVELS } from "@/lib/format";
import { usePagedJobs } from "@/lib/paged-jobs";
import type { Family, JobFilters, JobItem, Level } from "@/lib/types";

const EMPTY: JobFilters = {
  seniorities: [],
  include_unknown_level: true,
  role_families: [],
  employment_types: [],
  cities: [],
  remote_india: false,
  remote_global: false,
  onsite_anywhere: false,
  countries: [],
  companies: [],
  exclude_companies: [],
  company_tags: [],
  posted_within_days: null,
  min_salary_inr: null,
  salary_disclosed: false,
  skills: [],
};

const SUGGESTIONS = [
  "backend intern python Bengaluru",
  "machine learning new grad remote",
  "LLM agents RAG engineer",
  "data engineer spark airflow",
  "frontend react typescript",
  "SRE kubernetes",
];

const TAGS = [
  ["in", "Indian companies"],
  ["ai", "AI-native"],
  ["fintech", "Fintech"],
  ["quant", "Quant / trading"],
  ["devtools", "Dev tools"],
] as const;

function countFilters(f: JobFilters) {
  return (
    f.seniorities.length +
    f.role_families.length +
    f.cities.length +
    f.company_tags.length +
    (f.remote_india ? 1 : 0) +
    (f.remote_global ? 1 : 0) +
    (f.posted_within_days ? 1 : 0) +
    (f.salary_disclosed ? 1 : 0)
  );
}

function SearchInner() {
  const params = useSearchParams();
  const router = useRouter();
  const [q, setQ] = useState(params.get("q") ?? "");
  const [submitted, setSubmitted] = useState(params.get("q") ?? "");
  const [filters, setFilters] = useState<JobFilters>(EMPTY);
  const [showFilters, setShowFilters] = useState(false);
  const set = <K extends keyof JobFilters>(k: K, v: JobFilters[K]) => setFilters((f) => ({ ...f, [k]: v }));
  const active = countFilters(filters);

  const enabled = !!submitted || active > 0;
  const { jobs, setJobs, loading, loadingMore, hasMore, loadMore } = usePagedJobs<object>(
    ["search", submitted, filters],
    (offset, limit) => api.post<{ items: JobItem[] }>("/search", { q: submitted, filters, limit, offset }),
    enabled,
  );

  function submit(value: string) {
    setSubmitted(value.trim());
    router.replace(value.trim() ? `/search?q=${encodeURIComponent(value.trim())}` : "/search");
  }

  return (
    <AppShell>
      <PageHead title="Search" sub="Describe the role in your own words. Results are ranked for your resume too." />
      <form
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          submit(q);
        }}
        className="flex items-center gap-2 border-b-2 border-ink pb-2"
      >
        <SearchIcon className="size-6 shrink-0 text-ink-2" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="e.g. backend internship in Bengaluru using Go"
          aria-label="Search roles"
          autoFocus
          className="h-12 min-w-0 flex-1 bg-transparent text-xl outline-none placeholder:text-ink-3 md:text-2xl"
        />
        {q && (
          <button type="button" aria-label="Clear" onClick={() => { setQ(""); submit(""); }} className="grid size-9 place-items-center rounded-md text-ink-2 hover:bg-panel-2">
            <X className="size-5" />
          </button>
        )}
        <Button type="submit" variant="primary">
          Search
        </Button>
      </form>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Toggle on={showFilters} onClick={() => setShowFilters((s) => !s)}>
          Filters{active ? ` · ${active}` : ""}
        </Toggle>
        {[1, 7].map((d) => (
          <Toggle key={d} on={filters.posted_within_days === d} onClick={() => set("posted_within_days", filters.posted_within_days === d ? null : d)}>
            {d === 1 ? "Last 24h" : "This week"}
          </Toggle>
        ))}
        <Toggle on={filters.remote_india || filters.remote_global} onClick={() => setFilters((f) => ({ ...f, remote_india: !(f.remote_india || f.remote_global), remote_global: !(f.remote_india || f.remote_global) }))}>
          Remote
        </Toggle>
        <Toggle on={filters.salary_disclosed} onClick={() => set("salary_disclosed", !filters.salary_disclosed)}>
          Pay listed
        </Toggle>
        {active > 0 && (
          <Button variant="ghost" size="sm" onClick={() => setFilters(EMPTY)}>
            Clear filters
          </Button>
        )}
      </div>

      {showFilters && (
        <div className="mt-4 grid gap-6 rounded-md border border-rule bg-panel p-5 md:grid-cols-2">
          <Field label="Level">
            <ToggleSet<Level> options={LEVELS} value={filters.seniorities as Level[]} onChange={(v) => set("seniorities", v)} labels={LEVEL_LABEL} />
          </Field>
          <Field label="Role">
            <ToggleSet<Family> options={FAMILIES} value={filters.role_families as Family[]} onChange={(v) => set("role_families", v)} labels={FAMILY_LABEL} />
          </Field>
          <Field label="City">
            <ToggleSet<string> options={CITIES} value={filters.cities} onChange={(v) => set("cities", v)} />
          </Field>
          <Field label="Companies">
            <ToggleSet<string>
              options={TAGS.map((t) => t[0])}
              value={filters.company_tags}
              onChange={(v) => set("company_tags", v)}
              labels={Object.fromEntries(TAGS)}
            />
          </Field>
        </div>
      )}

      <div className="mt-8">
        {!submitted && active === 0 ? (
          <div>
            <p className="label mb-3 text-ink-2">Try</p>
            <div className="flex flex-wrap gap-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => {
                    setQ(s);
                    submit(s);
                  }}
                  className="rounded-[3px] border border-rule-strong px-3 py-1.5 text-sm text-ink-2 hover:border-ink-3 hover:text-ink"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : loading ? (
          <Skeleton rows={6} />
        ) : jobs.length === 0 ? (
          <Empty title="No roles found">Try fewer words, or remove a filter or two.</Empty>
        ) : (
          <JobList jobs={jobs} setJobs={setJobs} surface="search" hasMore={hasMore} loadingMore={loadingMore} onLoadMore={loadMore} query={submitted} />
        )}
      </div>
    </AppShell>
  );
}

export default function SearchPage() {
  return (
    <Suspense>
      <SearchInner />
    </Suspense>
  );
}
