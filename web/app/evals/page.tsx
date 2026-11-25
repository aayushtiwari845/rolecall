"use client";

import { useQuery } from "@tanstack/react-query";
import { ThemeToggle } from "@/components/app-shell";
import { Empty, Spinner, Wordmark } from "@/components/ui";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";

interface Row {
  suite: string;
  variant: string;
  metrics: Record<string, number | string | null | object>;
  created_at: string;
}

const SUITES: { id: string; title: string; how: string; best: string[] }[] = [
  {
    id: "retrieval",
    title: "Search",
    how: "Known-item search. For a stratified sample of live roles, write the query a student might type for that role (by an LLM when available, otherwise from templates over the role’s fields), then check where the role lands. Compares keyword search, embeddings, both fused with reciprocal rank fusion, and fusion plus a cross-encoder reranker.",
    best: ["recall@10", "mrr@10", "ndcg@10"],
  },
  {
    id: "recsys",
    title: "Scorecard quality",
    how: "Twenty-eight realistic personas: ten for tuning, six held out for ship decisions, and twelve fresh ones written after tuning and judged blind. Roles pooled from eight different rankers and the tuned configurations were each graded 0–3 against a written rubric. Reported on the two held-out sets only: graded nDCG@10 with a 95% bootstrap interval, precision, MAP, bpref (robust to unjudged roles), share of top-10 results breaking a persona's hard expectations (level, experience, location), diversity, stability when one skill is removed, and latency.",
    best: ["ndcg@10", "p@10", "map", "bpref", "success@5"],
  },
  {
    id: "recommendation",
    title: "Recommendations (quick check)",
    how: "Sample profiles (backend new grad, ML intern, data engineer, frontend, SRE). Each ranking variant’s top results are pooled and judged once on a 0–3 scale, by an LLM judge when available or by transparent rules otherwise. Also tracks company diversity and catalogue coverage.",
    best: ["ndcg@10", "p@10", "company_diversity"],
  },
  {
    id: "extraction",
    title: "Reading postings",
    how: "Field accuracy against hand-labelled postings: level, role, work mode, employment type and minimum years. Rules alone versus rules refined by an LLM.",
    best: ["macro_acc", "seniority_acc", "role_family_acc"],
  },
  {
    id: "agent",
    title: "Assistant",
    how: "Scripted conversations with expected tools. Passes when the assistant picks the right tools, references only real roles, and answers without errors.",
    best: ["pass_rate", "tool_selection_acc", "grounded_rate"],
  },
];

function fmt(v: unknown): string {
  if (typeof v === "number") return v <= 1 && v >= 0 && !Number.isInteger(v) ? v.toFixed(3) : String(v);
  if (v == null) return "–";
  if (typeof v === "object") return "…";
  return String(v);
}

export default function EvalsPage() {
  const { data, isLoading } = useQuery({ queryKey: ["evals"], queryFn: () => api.get<{ latest: Row[] }>("/evals") });
  return (
    <div className="min-h-dvh">
      <header className="mx-auto flex h-16 max-w-[1240px] items-center gap-6 px-4 md:px-6">
        <Wordmark />
        <div className="ml-auto">
          <ThemeToggle />
        </div>
      </header>
      <main className="mx-auto max-w-[1240px] px-4 pb-24 pt-8 md:px-6">
        <h1 className="score text-[3.5rem] font-extrabold uppercase leading-[0.9] md:text-[5rem]">How good is it?</h1>
        <p className="mt-5 max-w-[64ch] text-lg text-ink-2">
          Every number below is produced by the system testing itself against its own live index. The best value in each column is
          marked. Runs are repeatable from the repository with one command.
        </p>
        {isLoading ? (
          <Spinner className="mt-10" />
        ) : !data?.latest.length ? (
          <div className="mt-10">
            <Empty title="No runs yet">Evaluations run nightly once the index has data.</Empty>
          </div>
        ) : (
          SUITES.map((s) => {
            const rows = data.latest.filter((r) => r.suite === s.id);
            if (!rows.length) return null;
            const cols = Object.keys(rows[0].metrics).filter((k) => k !== "details");
            const bestOf = (c: string) => Math.max(...rows.map((r) => (typeof r.metrics[c] === "number" ? (r.metrics[c] as number) : -Infinity)));
            return (
              <section key={s.id} className="mt-16 grid gap-6 lg:grid-cols-[19rem_1fr] lg:gap-12">
                <div>
                  <h2 className="score text-[2.5rem] font-extrabold uppercase">{s.title}</h2>
                  <p className="mt-3 text-sm leading-relaxed text-ink-2">{s.how}</p>
                  <p className="mt-3 text-xs text-ink-3">Last run {ago(rows[0].created_at)}</p>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-rule-strong text-left">
                        <th className="label px-2 py-2 text-ink-2">Variant</th>
                        {cols.map((c) => (
                          <th key={c} className="label whitespace-nowrap px-2 py-2 text-right text-ink-2">
                            {c.replace(/_/g, " ")}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((r) => (
                        <tr key={r.variant} className="border-b border-rule">
                          <td className="whitespace-nowrap px-2 py-3 font-medium">{r.variant.replace(/_/g, " ")}</td>
                          {cols.map((c) => {
                            const v = r.metrics[c];
                            const best = s.best.includes(c) && typeof v === "number" && v === bestOf(c) && rows.length > 1;
                            return (
                              <td key={c} className={`px-2 py-3 text-right tabular-nums ${best ? "font-bold text-green" : "text-ink-2"}`}>
                                {fmt(v)}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            );
          })
        )}
      </main>
    </div>
  );
}
