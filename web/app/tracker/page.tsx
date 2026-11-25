"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { Download, ExternalLink, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { AppShell, PageHead } from "@/components/app-shell";
import { useToast } from "@/components/toast";
import { Button, ButtonLink, Empty, Input, Skeleton } from "@/components/ui";
import { api } from "@/lib/api";
import { ago } from "@/lib/format";
import type { Application, AppStatus } from "@/lib/types";

const COLUMNS: { status: AppStatus; label: string; tone: string }[] = [
  { status: "saved", label: "Saved", tone: "text-ink-2" },
  { status: "applied", label: "Applied", tone: "text-pen" },
  { status: "oa", label: "Online test", tone: "text-amber-text" },
  { status: "interview", label: "Interview", tone: "text-amber-text" },
  { status: "offer", label: "Offer", tone: "text-green" },
  { status: "rejected", label: "Rejected", tone: "text-red" },
];
const LABEL = Object.fromEntries([...COLUMNS.map((c) => [c.status, c.label]), ["withdrawn", "Withdrawn"]]) as Record<AppStatus, string>;

function Card({
  app,
  onMove,
  onDelete,
  onNotes,
}: {
  app: Application;
  onMove: (s: AppStatus) => void;
  onDelete: () => void;
  onNotes: (n: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [notes, setNotes] = useState(app.notes);
  // A rejection is a wicket: struck through in red, like the scorer marks it.
  const struck = app.status === "rejected" || app.status === "withdrawn";
  return (
    <li
      draggable
      onDragStart={(e) => e.dataTransfer.setData("text/plain", app.id)}
      className={clsx(
        "group cursor-grab rounded-md border border-rule bg-panel p-3 transition-shadow hover:shadow-[0_4px_14px_rgb(0_0_0/0.12)] active:cursor-grabbing",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          {app.job_id ? (
            <Link
              href={`/jobs/${app.job_id}`}
              className={clsx("block text-sm font-semibold leading-snug hover:underline", struck && "line-through decoration-red decoration-2")}
            >
              {app.title}
            </Link>
          ) : (
            <p className={clsx("text-sm font-semibold leading-snug", struck && "line-through decoration-red decoration-2")}>{app.title}</p>
          )}
          <p className="mt-0.5 truncate text-xs text-ink-2">
            {app.company}
            {app.job_open === false && <span className="ml-1.5 text-red">· closed</span>}
          </p>
        </div>
        {app.url && (
          <a href={app.url} target="_blank" rel="noopener noreferrer" aria-label="Open posting" className="shrink-0 text-ink-3 hover:text-ink">
            <ExternalLink className="size-4" />
          </a>
        )}
      </div>
      <div className="mt-2 flex items-center justify-between gap-2">
        <select
          aria-label="Move to"
          value={app.status}
          onChange={(e) => onMove(e.target.value as AppStatus)}
          className="h-7 rounded border border-rule bg-panel px-1 text-xs text-ink-2"
        >
          {Object.entries(LABEL).map(([v, l]) => (
            <option key={v} value={v}>
              {l}
            </option>
          ))}
        </select>
        <span className="text-[0.6875rem] text-ink-3">{ago(app.applied_at ?? app.created_at)}</span>
      </div>
      <button onClick={() => setOpen((o) => !o)} className="mt-2 text-left text-xs text-ink-3 hover:text-ink">
        {app.notes ? app.notes.slice(0, 80) : open ? "" : "+ note"}
      </button>
      {open && (
        <div className="mt-2 grid gap-2">
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            placeholder="Referral from…, OA on Friday…"
            className="w-full rounded border border-rule-strong bg-bg p-2 text-xs outline-none focus:border-amber"
          />
          <div className="flex justify-between">
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                onNotes(notes);
                setOpen(false);
              }}
            >
              Save note
            </Button>
            <button onClick={onDelete} aria-label="Remove from tracker" className="grid size-8 place-items-center rounded text-ink-3 hover:bg-red/10 hover:text-red">
              <Trash2 className="size-4" />
            </button>
          </div>
        </div>
      )}
    </li>
  );
}

export default function TrackerPage() {
  const qc = useQueryClient();
  const toast = useToast();
  const { data, isLoading } = useQuery({ queryKey: ["applications"], queryFn: () => api.get<{ items: Application[] }>("/applications") });
  const [over, setOver] = useState<AppStatus | null>(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState({ company: "", title: "", url: "" });
  const apps = data?.items ?? [];

  const setApps = (fn: (a: Application[]) => Application[]) =>
    qc.setQueryData<{ items: Application[] }>(["applications"], (d) => ({ ...(d ?? { items: [] }), items: fn(d?.items ?? []) }));

  async function move(id: string, status: AppStatus) {
    const prev = apps;
    setApps((a) => a.map((x) => (x.id === id ? { ...x, status } : x)));
    try {
      await api.patch(`/applications/${id}`, { status });
      if (status === "offer") toast({ text: "An offer! Congratulations." });
    } catch {
      setApps(() => prev);
      toast({ text: "Couldn't move that card.", tone: "error" });
    }
  }

  async function remove(id: string) {
    setApps((a) => a.filter((x) => x.id !== id));
    await api.del(`/applications/${id}`).catch(() => qc.invalidateQueries({ queryKey: ["applications"] }));
  }

  async function notes(id: string, n: string) {
    setApps((a) => a.map((x) => (x.id === id ? { ...x, notes: n } : x)));
    await api.patch(`/applications/${id}`, { notes: n });
  }

  async function addManual(e: React.FormEvent) {
    e.preventDefault();
    const created = await api.post<Application>("/applications", { ...draft, status: "applied" });
    setApps((a) => [created, ...a]);
    setDraft({ company: "", title: "", url: "" });
    setAdding(false);
  }

  return (
    <AppShell wide>
      <PageHead title="Tracker" sub="Drag cards between columns, or use the menu on each card. Your board exports to Excel any time.">
        <Button variant="outline" size="sm" onClick={() => setAdding((a) => !a)}>
          <Plus className="size-4" /> Add a role from elsewhere
        </Button>
        <ButtonLink href="/api/applications/export?format=xlsx" variant="primary" size="sm">
          <Download className="size-4" /> Export to Excel
        </ButtonLink>
        <ButtonLink href="/api/applications/export?format=csv" variant="ghost" size="sm">
          CSV
        </ButtonLink>
      </PageHead>

      {adding && (
        <form onSubmit={addManual} className="mb-8 grid gap-3 rounded-md border border-rule bg-panel p-4 md:grid-cols-[1fr_1fr_1.4fr_auto]">
          <Input required placeholder="Company" value={draft.company} onChange={(e) => setDraft({ ...draft, company: e.target.value })} />
          <Input required placeholder="Role" value={draft.title} onChange={(e) => setDraft({ ...draft, title: e.target.value })} />
          <Input placeholder="Link (optional)" type="url" value={draft.url} onChange={(e) => setDraft({ ...draft, url: e.target.value })} />
          <Button type="submit" variant="primary">
            Add as applied
          </Button>
        </form>
      )}

      {isLoading ? (
        <Skeleton rows={4} />
      ) : apps.length === 0 ? (
        <Empty title="Nothing tracked yet">
          Save roles from your{" "}
          <Link href="/feed" className="text-ink underline">
            scorecard
          </Link>{" "}
          and they’ll land in the first column. Applied somewhere else? Add it with the button above.
        </Empty>
      ) : (
        <div className="-mx-4 overflow-x-auto px-4 pb-4 md:mx-0 md:px-0">
          <div className="grid min-w-[1080px] grid-cols-6 gap-3">
            {COLUMNS.map((c) => {
              const items = apps.filter((a) => a.status === c.status || (c.status === "rejected" && a.status === "withdrawn"));
              return (
                <section
                  key={c.status}
                  aria-label={c.label}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setOver(c.status);
                  }}
                  onDragLeave={() => setOver(null)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setOver(null);
                    const id = e.dataTransfer.getData("text/plain");
                    if (id) move(id, c.status);
                  }}
                  className={clsx(
                    "flex min-h-[60vh] flex-col rounded-md border border-transparent bg-panel-2/60 p-2 transition-colors",
                    over === c.status && "border-amber bg-amber/10",
                  )}
                >
                  <header className="flex items-end justify-between px-1.5 pb-3 pt-1">
                    <h2 className={clsx("label", c.tone)}>{c.label}</h2>
                    <span className="score text-[2rem] font-extrabold text-ink">{items.length}</span>
                  </header>
                  <ul className="grid gap-2">
                    {items.map((a) => (
                      <Card key={a.id} app={a} onMove={(s) => move(a.id, s)} onDelete={() => remove(a.id)} onNotes={(n) => notes(a.id, n)} />
                    ))}
                  </ul>
                </section>
              );
            })}
          </div>
        </div>
      )}
    </AppShell>
  );
}
