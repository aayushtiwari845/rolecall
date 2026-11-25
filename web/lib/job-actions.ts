"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback } from "react";
import { useToast } from "@/components/toast";
import { api, track } from "./api";
import type { JobItem } from "./types";

/** Save / unsave / dismiss with optimistic local state and an undo toast. */
export function useJobActions(setJobs: (fn: (jobs: JobItem[]) => JobItem[]) => void, surface: string) {
  const toast = useToast();
  const qc = useQueryClient();

  const toggleSave = useCallback(
    async (job: JobItem) => {
      const next = !job.saved;
      setJobs((js) => js.map((j) => (j.id === job.id ? { ...j, saved: next } : j)));
      try {
        if (next) {
          await api.post("/applications", { job_id: job.id, status: "saved" });
          toast({ text: `Saved ${job.company} to your tracker` });
        } else {
          await api.del(`/applications/job/${job.id}`);
        }
        qc.invalidateQueries({ queryKey: ["applications"] });
      } catch {
        setJobs((js) => js.map((j) => (j.id === job.id ? { ...j, saved: !next } : j)));
        toast({ text: "Couldn't update that. Try again.", tone: "error" });
      }
    },
    [setJobs, toast, qc],
  );

  const dismiss = useCallback(
    (job: JobItem, onGone: (id: string) => void, onRestore: (job: JobItem) => void) => {
      track(job.id, "dismiss", { surface });
      setTimeout(() => onGone(job.id), 420);
      toast({
        text: "Hidden. You’ll see fewer like it.",
        action: {
          label: "Undo",
          run: () => {
            track(job.id, "undismiss", { surface });
            onRestore(job);
          },
        },
      });
    },
    [surface, toast],
  );

  return { toggleSave, dismiss };
}
