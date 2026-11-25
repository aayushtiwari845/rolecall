"use client";

import { useQuery } from "@tanstack/react-query";
import { AppShell, PageHead } from "@/components/app-shell";
import { Empty, Spinner } from "@/components/ui";
import { api } from "@/lib/api";
import { num } from "@/lib/format";

interface Metrics {
  index: Record<string, number>;
  users: Record<string, number>;
  funnel_7d: Record<string, number | null>;
  daily_active: { day: string; users: number }[];
  daily_new_jobs: { day: string; jobs: number }[];
  sources: { kind: string; status: string | null; count: number; open_jobs: number }[];
  failing_sources: { kind: string; key: string; error: string; failures: number }[];
  ingest_24h: { kind: string; runs: number; created: number; closed: number; avg_seconds: number }[];
  llm_7d: { provider: string; purpose: string; calls: number; ok: number; tokens: number; avg_latency_ms: number; cache_hits: number }[];
}

const nice = (k: string) => k.replace(/_/g, " ").replace(/\b7d\b/, "(7 days)").replace(/\b1d\b/, "(24h)");

function Board({ title, data, pct = [] }: { title: string; data: Record<string, number | null>; pct?: string[] }) {
  return (
    <div className="board rounded-md">
      <p className="label border-b border-board-rule px-4 py-2.5 text-chalk-2">{title}</p>
      <div className="grid grid-cols-2 sm:grid-cols-3">
        {Object.entries(data).map(([k, v]) => (
          <div key={k} className="border-b border-r border-board-rule px-4 py-4">
            <p className="score text-[2.25rem] font-extrabold text-chalk">
              {v == null ? "–" : pct.includes(k) ? `${(v * 100).toFixed(1)}%` : num(v)}
            </p>
            <p className="label mt-1 text-[0.6rem] text-chalk-2">{nice(k)}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function Table({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-rule-strong text-left">
            {head.map((h) => (
              <th key={h} className="label px-2 py-2 font-semibold text-ink-2">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-rule">
              {r.map((c, j) => (
                <td key={j} className={`px-2 py-2 ${typeof c === "number" ? "tabular-nums" : ""}`}>
                  {typeof c === "number" ? num(c) : c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function AdminPage() {
  const { data, isLoading, error } = useQuery({ queryKey: ["admin"], queryFn: () => api.get<Metrics>("/admin/metrics"), refetchInterval: 60_000 });
  return (
    <AppShell wide>
      <PageHead title="Admin" sub="Index health, ingestion, engagement and AI usage. Refreshes every minute." />
      {isLoading ? (
        <Spinner />
      ) : error || !data ? (
        <Empty title="Admins only" />
      ) : (
        <div className="grid gap-12">
          <div className="grid gap-4 xl:grid-cols-3">
            <Board title="Index" data={data.index} />
            <Board title="Users" data={data.users} />
            <Board title="Funnel, last 7 days" data={data.funnel_7d} pct={["ctr", "save_rate"]} />
          </div>
          <div className="grid gap-12 xl:grid-cols-2">
            <section>
              <h2 className="score mb-3 text-2xl font-bold uppercase">Sources</h2>
              <Table head={["Kind", "Status", "Boards", "Open roles"]} rows={data.sources.map((s) => [s.kind, s.status ?? "never run", s.count, s.open_jobs])} />
            </section>
            <section>
              <h2 className="score mb-3 text-2xl font-bold uppercase">Crawls, last 24h</h2>
              <Table head={["Kind", "Runs", "New", "Closed", "Avg sec"]} rows={data.ingest_24h.map((r) => [r.kind, r.runs, r.created, r.closed, r.avg_seconds])} />
            </section>
            <section>
              <h2 className="score mb-3 text-2xl font-bold uppercase">AI calls, last 7 days</h2>
              <Table
                head={["Provider", "Purpose", "Calls", "OK", "Tokens", "Avg ms", "Cached"]}
                rows={data.llm_7d.map((r) => [r.provider || "cache", r.purpose, r.calls, r.ok, r.tokens, r.avg_latency_ms, r.cache_hits])}
              />
            </section>
            <section>
              <h2 className="score mb-3 text-2xl font-bold uppercase">Failing boards</h2>
              {data.failing_sources.length === 0 ? (
                <p className="text-sm text-ink-2">None. Every board answered on its last run.</p>
              ) : (
                <Table head={["Board", "Failures", "Error"]} rows={data.failing_sources.map((f) => [`${f.kind}:${f.key}`, f.failures, f.error.slice(0, 80)])} />
              )}
            </section>
            <section>
              <h2 className="score mb-3 text-2xl font-bold uppercase">New roles per day</h2>
              <Table head={["Day", "New roles"]} rows={data.daily_new_jobs.slice(-14).reverse().map((d) => [d.day, d.jobs])} />
            </section>
            <section>
              <h2 className="score mb-3 text-2xl font-bold uppercase">Active users per day</h2>
              <Table head={["Day", "Users"]} rows={data.daily_active.slice(-14).reverse().map((d) => [d.day, d.users])} />
            </section>
          </div>
        </div>
      )}
    </AppShell>
  );
}
