"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import type { JobItem } from "@/lib/types";
import { JobRow } from "../job-row";
import { Skeleton, Toggle } from "../ui";

interface DemoProfile {
  id: string;
  label: string;
  skills: string[];
}

export function DemoFeed() {
  const { data: profiles } = useQuery({
    queryKey: ["demo-profiles"],
    queryFn: () => api.get<{ items: DemoProfile[] }>("/demo/profiles"),
  });
  const [pid, setPid] = useState("backend_new_grad");
  const { data, isFetching } = useQuery({
    queryKey: ["demo-feed", pid],
    queryFn: () => api.post<{ profile: string; items: JobItem[] }>("/demo/feed", { profile: pid, limit: 6 }),
    staleTime: 5 * 60_000,
  });
  const current = profiles?.items.find((p) => p.id === pid);
  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <span className="label mr-2 text-ink-2">Try a sample profile</span>
        {(profiles?.items ?? []).map((p) => (
          <Toggle key={p.id} on={p.id === pid} onClick={() => setPid(p.id)}>
            {p.label}
          </Toggle>
        ))}
      </div>
      {current && (
        <p className="mt-3 text-sm text-ink-2">
          Skills on this sample resume: <span className="text-ink">{current.skills.slice(0, 9).join(", ")}</span>
        </p>
      )}
      <div className="mt-6 border-y border-rule">
        {isFetching && !data ? (
          <Skeleton rows={4} />
        ) : (
          <div className={`ruled transition-opacity ${isFetching ? "opacity-50" : ""}`}>
            {(data?.items ?? []).map((j) => (
              <JobRow key={j.id} job={j} />
            ))}
            {data && data.items.length === 0 && (
              <p className="py-10 text-center text-sm text-ink-2">The index is still filling up. Check back in a few minutes.</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
