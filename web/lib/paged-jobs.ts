"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";
import type { JobItem } from "./types";

const PAGE = 20;

type Page<M> = { items: JobItem[] } & M;
type Patch = Partial<JobItem> | null; // null = removed from view

/**
 * Paginated job lists with a local patch layer, so saves, hides and undos update
 * instantly without refetching or mutating the query cache.
 */
export function usePagedJobs<M extends object>(
  key: unknown[],
  fetchPage: (offset: number, limit: number) => Promise<Page<M>>,
  enabled = true,
) {
  const [patches, setPatches] = useState<Record<string, Patch>>({});
  const [restored, setRestored] = useState<JobItem[]>([]);
  const q = useInfiniteQuery({
    queryKey: key,
    queryFn: ({ pageParam }) => fetchPage(pageParam, PAGE),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => (last.items.length === PAGE ? pages.length * PAGE : undefined),
    enabled,
    staleTime: 60_000,
  });

  const base = useMemo(() => {
    const seen = new Set<string>();
    const out: JobItem[] = [];
    for (const p of q.data?.pages ?? [])
      for (const j of p.items) {
        if (seen.has(j.id)) continue;
        seen.add(j.id);
        out.push(j);
      }
    return out;
  }, [q.data]);

  const jobs = useMemo(() => {
    const extra = restored.filter((r) => !base.some((b) => b.id === r.id));
    return [...extra, ...base].flatMap((j) => {
      const p = patches[j.id];
      if (p === null) return [];
      return [p ? { ...j, ...p } : j];
    });
  }, [base, patches, restored]);

  const jobsRef = useRef(jobs);
  useLayoutEffect(() => {
    jobsRef.current = jobs;
  }, [jobs]);

  const setJobs = useCallback((fn: (js: JobItem[]) => JobItem[]) => {
    const prev = jobsRef.current;
    const next = fn(prev);
    const nextIds = new Set(next.map((j) => j.id));
    setPatches((ps) => {
      const out = { ...ps };
      for (const j of prev) if (!nextIds.has(j.id)) out[j.id] = null;
      for (const j of next) {
        const old = prev.find((o) => o.id === j.id);
        if (!old) delete out[j.id];
        else if (old.saved !== j.saved) out[j.id] = { ...(out[j.id] ?? {}), saved: j.saved };
      }
      return out;
    });
    const added = next.filter((j) => !prev.some((o) => o.id === j.id));
    if (added.length) setRestored((r) => [...added, ...r]);
  }, []);

  const first = q.data?.pages[0];
  return {
    jobs,
    setJobs,
    meta: first as (Page<M> | undefined),
    loading: q.isPending && enabled,
    loadingMore: q.isFetchingNextPage,
    hasMore: !!q.hasNextPage,
    loadMore: () => void q.fetchNextPage(),
    error: q.error,
  };
}
