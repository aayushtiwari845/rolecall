"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Star, Trash2 } from "lucide-react";
import { useState } from "react";
import { AppShell, PageHead } from "@/components/app-shell";
import { DEFAULT_PREFS, PrefsForm } from "@/components/prefs-form";
import { ResumeUpload } from "@/components/resume-upload";
import { useToast } from "@/components/toast";
import { Button, Field, Input, Toggle } from "@/components/ui";
import { api } from "@/lib/api";
import { useMe, useSignOut } from "@/lib/hooks";
import type { Alert, Preferences, Resume } from "@/lib/types";

function Section({ id, title, sub, children }: { id: string; title: string; sub?: string; children: React.ReactNode }) {
  return (
    <section id={id} className="grid scroll-mt-24 gap-6 border-t border-rule py-10 lg:grid-cols-[17rem_1fr] lg:gap-12">
      <div>
        <h2 className="score text-[2rem] font-extrabold uppercase">{title}</h2>
        {sub && <p className="mt-2 text-sm leading-relaxed text-ink-2">{sub}</p>}
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

function Resumes() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["resumes"], queryFn: () => api.get<{ items: Resume[] }>("/resumes") });
  const [adding, setAdding] = useState(false);
  const items = data?.items ?? [];
  const refresh = () => qc.invalidateQueries({ queryKey: ["resumes"] });
  return (
    <div className="grid gap-6">
      {items.length > 0 && (
        <ul className="ruled border-y border-rule">
          {items.map((r) => (
            <li key={r.id} className="grid gap-2 py-4 sm:grid-cols-[1fr_auto] sm:items-start">
              <div className="min-w-0">
                <p className="flex items-center gap-2 font-semibold">
                  {r.label}
                  {r.is_default && <span className="label rounded bg-amber px-1.5 py-0.5 text-[0.6rem] text-amber-ink">Default</span>}
                </p>
                <p className="mt-1 text-sm text-ink-2">{r.headline}</p>
                <p className="mt-2 text-xs text-ink-3">{r.skills.slice(0, 16).join(" · ")}</p>
              </div>
              <div className="flex gap-1">
                {!r.is_default && (
                  <Button size="sm" variant="ghost" onClick={async () => { await api.patch(`/resumes/${r.id}`, { is_default: true }); refresh(); }}>
                    <Star className="size-4" /> Make default
                  </Button>
                )}
                <Button size="sm" variant="ghost" aria-label={`Delete ${r.label}`} onClick={async () => { await api.del(`/resumes/${r.id}`); refresh(); }}>
                  <Trash2 className="size-4" />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {adding || items.length === 0 ? (
        <ResumeUpload
          defaultLabel={items.length ? "ML resume" : "My resume"}
          onDone={() => {
            setAdding(false);
            refresh();
          }}
        />
      ) : (
        items.length < 5 && (
          <Button variant="outline" className="justify-self-start" onClick={() => setAdding(true)}>
            Add another resume
          </Button>
        )
      )}
    </div>
  );
}

function Prefs() {
  const { data } = useQuery({ queryKey: ["prefs"], queryFn: () => api.get<Preferences>("/preferences") });
  if (!data) return <PrefsEditor initial={DEFAULT_PREFS} disabled />;
  return <PrefsEditor key="loaded" initial={data} />;
}

function PrefsEditor({ initial, disabled }: { initial: Preferences; disabled?: boolean }) {
  const toast = useToast();
  const qc = useQueryClient();
  const [p, setP] = useState<Preferences>(initial);
  async function save() {
    await api.put("/preferences", p);
    qc.invalidateQueries({ queryKey: ["prefs"] });
    toast({ text: "Preferences saved. Your scorecard is updated." });
  }
  return (
    <div className="grid gap-8">
      <PrefsForm value={p} onChange={setP} />
      <Field label="Hide these companies" hint="Comma-separated">
        <Input
          value={p.excluded_companies.join(", ")}
          onChange={(e) => setP({ ...p, excluded_companies: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
          placeholder="e.g. Acme, Globex"
        />
      </Field>
      <Button variant="primary" className="justify-self-start" onClick={save} disabled={disabled}>
        Save preferences
      </Button>
    </div>
  );
}

function Digest() {
  const { data } = useQuery({ queryKey: ["prefs"], queryFn: () => api.get<Preferences>("/preferences") });
  if (!data) return null;
  return <DigestEditor data={data} />;
}

function DigestEditor({ data }: { data: Preferences }) {
  const toast = useToast();
  const [on, setOn] = useState(data.digest_enabled);
  const [hour, setHour] = useState(data.digest_hour_ist);
  async function save(next: boolean, h: number) {
    setOn(next);
    setHour(h);
    await api.put("/preferences", { ...data, digest_enabled: next, digest_hour_ist: h });
    toast({ text: next ? `Daily email on, around ${h}:00 IST` : "Daily email off" });
  }
  return (
    <div className="flex flex-wrap items-center gap-3">
      <Toggle on={on} onClick={() => save(!on, hour)}>
        {on ? "Daily email on" : "Daily email off"}
      </Toggle>
      <label className="flex items-center gap-2 text-sm text-ink-2">
        at
        <select value={hour} onChange={(e) => save(on, Number(e.target.value))} className="h-8 rounded border border-rule-strong bg-panel px-2 text-ink">
          {Array.from({ length: 24 }).map((_, h) => (
            <option key={h} value={h}>
              {String(h).padStart(2, "0")}:00
            </option>
          ))}
        </select>
        IST
      </label>
    </div>
  );
}

function Alerts() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["alerts"], queryFn: () => api.get<{ items: Alert[] }>("/alerts") });
  const [name, setName] = useState("");
  const [query, setQuery] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["alerts"] });
  return (
    <div className="grid gap-6">
      {(data?.items ?? []).length > 0 && (
        <ul className="ruled border-y border-rule">
          {data!.items.map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-4 py-3">
              <div>
                <p className="font-medium">{a.name}</p>
                <p className="text-sm text-ink-2">{a.query || "Any role"}</p>
              </div>
              <Button size="sm" variant="ghost" aria-label={`Delete alert ${a.name}`} onClick={async () => { await api.del(`/alerts/${a.id}`); refresh(); }}>
                <Trash2 className="size-4" />
              </Button>
            </li>
          ))}
        </ul>
      )}
      <form
        className="grid gap-3 sm:grid-cols-[1fr_1.5fr_auto]"
        onSubmit={async (e) => {
          e.preventDefault();
          await api.post("/alerts", { name: name || query, query });
          setName("");
          setQuery("");
          refresh();
        }}
      >
        <Input placeholder="Name, e.g. Remote ML" value={name} onChange={(e) => setName(e.target.value)} />
        <Input required placeholder="What to watch for, e.g. machine learning intern remote" value={query} onChange={(e) => setQuery(e.target.value)} />
        <Button type="submit" variant="outline">
          Add alert
        </Button>
      </form>
    </div>
  );
}

function Memories() {
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["memories"], queryFn: () => api.get<{ items: { id: number; content: string }[] }>("/chat/memories") });
  const items = data?.items ?? [];
  if (!items.length) return <p className="text-sm text-ink-2">Nothing yet. Tell the assistant about your search and it’ll remember.</p>;
  return (
    <ul className="ruled border-y border-rule">
      {items.map((m) => (
        <li key={m.id} className="flex items-center justify-between gap-4 py-3 text-sm">
          <span>{m.content}</span>
          <Button size="sm" variant="ghost" aria-label="Forget" onClick={async () => { await api.del(`/chat/memories/${m.id}`); qc.invalidateQueries({ queryKey: ["memories"] }); }}>
            Forget
          </Button>
        </li>
      ))}
    </ul>
  );
}

function Account() {
  const { data: me } = useMe();
  const signOut = useSignOut();
  const [confirm, setConfirm] = useState("");
  async function exportData() {
    const data = await api.get("/me/export");
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "rolecall-my-data.json";
    a.click();
  }
  return (
    <div className="grid gap-8">
      <p className="text-sm text-ink-2">
        Signed in as <span className="text-ink">{me?.email}</span>
      </p>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" onClick={exportData}>
          Download my data
        </Button>
        <Button variant="ghost" onClick={signOut}>
          Sign out
        </Button>
      </div>
      <div className="grid gap-3 rounded-md border border-red/40 p-4">
        <p className="font-semibold text-red">Delete account</p>
        <p className="text-sm text-ink-2">Removes your resumes, tracker, alerts, chats and memories permanently. This can’t be undone.</p>
        <div className="flex flex-wrap gap-2">
          <Input className="max-w-60" placeholder='Type "delete" to confirm' value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          <Button
            variant="danger"
            disabled={confirm !== "delete"}
            onClick={async () => {
              await api.del("/me");
              window.location.href = "/";
            }}
          >
            Delete everything
          </Button>
        </div>
      </div>
    </div>
  );
}

export default function SettingsPage() {
  return (
    <AppShell>
      <PageHead title="Settings" />
      <Section id="resumes" title="Resumes" sub="Up to five. Switch your scorecard between them from the scorecard page.">
        <Resumes />
      </Section>
      <Section id="preferences" title="Preferences" sub="These decide which roles reach your scorecard.">
        <Prefs />
      </Section>
      <Section id="email" title="Daily email" sub="New roles that fit, plus anything your alerts caught. Sent only when there’s something new.">
        <Digest />
      </Section>
      <Section id="alerts" title="Alerts" sub="Saved searches. Their new matches go into your daily email.">
        <Alerts />
      </Section>
      <Section id="memory" title="Assistant memory" sub="What the assistant remembers about your search.">
        <Memories />
      </Section>
      <Section id="account" title="Account">
        <Account />
      </Section>
    </AppShell>
  );
}
