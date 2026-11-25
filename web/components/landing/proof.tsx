"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { num } from "@/lib/format";

interface EvalRow {
  suite: string;
  variant: string;
  metrics: Record<string, number | string | null>;
}

export function EvalProof() {
  const { data } = useQuery({ queryKey: ["evals"], queryFn: () => api.get<{ latest: EvalRow[] }>("/evals") });
  const find = (suite: string, variant: string) => data?.latest.find((r) => r.suite === suite && r.variant === variant)?.metrics;
  const ret = find("retrieval", "hybrid_rerank");
  const lex = find("retrieval", "lexical");
  const rec = find("recommendation", "full_ranker");
  const dense = find("recommendation", "dense_only");
  const ext = find("extraction", "rules");
  const pct = (v: unknown) => (typeof v === "number" ? Math.round(v * 100) : null);

  const rows = [
    {
      value: pct(ret?.["recall@10"]),
      unit: "%",
      text: "of the time, the role you were describing is in the first 10 search results",
      vs: lex ? `keyword search alone: ${pct(lex["recall@10"])}%` : null,
    },
    {
      value: rec ? Math.round(Number(rec["ndcg@10"]) * 100) : null,
      unit: "",
      text: "nDCG@10 for the personalised scorecard across sample profiles (out of 100)",
      vs: dense ? `embeddings alone: ${Math.round(Number(dense["ndcg@10"]) * 100)}` : null,
    },
    {
      value: pct(ext?.macro_acc),
      unit: "%",
      text: "field accuracy reading level, role, work mode and experience off hand-labelled postings",
      vs: ext?.cases ? `${num(Number(ext.cases))} labelled postings` : null,
    },
  ].filter((r) => r.value !== null);

  if (!rows.length) return null;
  return (
    <div className="ruled border-y border-rule">
      {rows.map((r) => (
        <div key={r.text} className="grid grid-cols-[7.5rem_1fr] items-baseline gap-6 py-6 md:grid-cols-[11rem_1fr_auto]">
          <span className="score text-[3.5rem] font-extrabold text-ink md:text-[5rem]">
            {r.value}
            <span className="text-[0.5em] text-ink-2">{r.unit}</span>
          </span>
          <p className="text-base text-ink md:text-lg">{r.text}</p>
          {r.vs && <p className="col-start-2 text-sm text-ink-3 md:col-start-3">{r.vs}</p>}
        </div>
      ))}
      <p className="py-4 text-sm text-ink-2">
        Measured by the system on its own live index.{" "}
        <Link href="/evals" className="text-ink underline">
          See every run and how it is measured
        </Link>
        .
      </p>
    </div>
  );
}
