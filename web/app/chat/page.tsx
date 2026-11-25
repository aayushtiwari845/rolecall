"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import clsx from "clsx";
import { ArrowUp, Plus, Trash2 } from "lucide-react";
import { Fragment, useEffect, useRef, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { JobRow } from "@/components/job-row";
import { Spinner } from "@/components/ui";
import { api, streamEvents } from "@/lib/api";
import { useMe } from "@/lib/hooks";
import type { JobItem } from "@/lib/types";

interface ToolStep {
  id: string;
  name: string;
  status: "running" | "done";
  summary?: string;
}

interface Msg {
  id: string;
  role: "user" | "assistant" | "tool";
  content?: string;
  jobs?: JobItem[];
  steps?: ToolStep[];
  name?: string;
  error?: boolean;
}

const TOOL_LABEL: Record<string, string> = {
  search_jobs: "Searching roles",
  recommend_jobs: "Checking your scorecard",
  get_job_details: "Reading a posting",
  compare_jobs: "Comparing roles",
  save_job: "Updating your tracker",
  list_applications: "Looking at your tracker",
  create_alert: "Setting up an alert",
  update_preferences: "Updating preferences",
  remember: "Noting that for later",
  jobs_at_company: "Checking the company’s openings",
};

const STARTERS = [
  "What should I apply to this week?",
  "Find remote ML internships posted in the last 7 days",
  "Compare the top two backend new-grad roles in Bengaluru",
  "Which roles at fintech companies fit my resume?",
];

/** Minimal formatting: paragraphs, bullet lists, **bold**, and [[job:id]] cards. */
function Rich({ text, jobs }: { text: string; jobs: JobItem[] }) {
  const byId = new Map(jobs.map((j) => [j.id, j]));
  const used = new Set<string>();
  const blocks = text.split(/\n{2,}/);
  const inline = (s: string) =>
    s.split(/(\*\*[^*]+\*\*)/g).map((p, i) =>
      p.startsWith("**") ? (
        <strong key={i} className="font-semibold text-ink">
          {p.slice(2, -2)}
        </strong>
      ) : (
        <Fragment key={i}>{p}</Fragment>
      ),
    );
  const out: React.ReactNode[] = [];
  blocks.forEach((b, bi) => {
    const lines = b.split("\n");
    const cards: JobItem[] = [];
    const rest: string[] = [];
    for (const l of lines) {
      const m = l.match(/\[\[job:([0-9a-f-]{36})\]\]/);
      const job = m && byId.get(m[1]);
      if (job && !used.has(job.id)) {
        used.add(job.id);
        cards.push(job);
        const stripped = l.replace(/\[\[job:[0-9a-f-]{36}\]\]/g, "").trim();
        if (stripped && !/^[-*•]?\s*$/.test(stripped)) rest.push(stripped);
      } else rest.push(l.replace(/\[\[job:[0-9a-f-]{36}\]\]/g, ""));
    }
    const isList = rest.every((l) => /^\s*([-*•]|\d+\.)\s/.test(l)) && rest.length > 0;
    if (rest.join("").trim()) {
      out.push(
        isList ? (
          <ul key={`l${bi}`} className="grid list-disc gap-1 pl-5">
            {rest.map((l, i) => (
              <li key={i}>{inline(l.replace(/^\s*([-*•]|\d+\.)\s/, ""))}</li>
            ))}
          </ul>
        ) : (
          <p key={`p${bi}`}>{inline(rest.join(" ").trim())}</p>
        ),
      );
    }
    if (cards.length)
      out.push(
        <div key={`c${bi}`} className="ruled rounded-md border border-rule bg-panel px-4">
          {cards.map((j) => (
            <JobRow key={j.id} job={j} compact />
          ))}
        </div>,
      );
  });
  const unused = jobs.filter((j) => !used.has(j.id));
  if (unused.length && used.size === 0)
    out.push(
      <div key="rest" className="ruled rounded-md border border-rule bg-panel px-4">
        {unused.map((j) => (
          <JobRow key={j.id} job={j} compact />
        ))}
      </div>,
    );
  return <div className="grid gap-3 leading-relaxed">{out}</div>;
}

export default function ChatPage() {
  const qc = useQueryClient();
  const { data: me } = useMe();
  const { data: status } = useQuery({ queryKey: ["chat-status"], queryFn: () => api.get<{ available: boolean }>("/chat/status") });
  const { data: threads } = useQuery({
    queryKey: ["threads"],
    queryFn: () => api.get<{ items: { id: string; title: string; updated_at: string }[] }>("/chat/threads"),
  });
  const [threadId, setThreadId] = useState<string | null>(null);
  const [messages, setMessages] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const seq = useRef(0);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  async function open(id: string) {
    setThreadId(id);
    const t = await api.get<{ messages: Msg[] }>(`/chat/threads/${id}`);
    const grouped: Msg[] = [];
    for (const m of t.messages) {
      if (m.role === "tool") {
        const last = grouped[grouped.length - 1];
        const step = { id: String(m.id), name: m.name ?? "", status: "done" as const };
        if (last?.role === "assistant" && !last.content) last.steps = [...(last.steps ?? []), step];
        else grouped.push({ id: `s${m.id}`, role: "assistant", content: "", steps: [step] });
      } else if (m.role === "assistant") {
        const last = grouped[grouped.length - 1];
        if (last?.role === "assistant" && !last.content) Object.assign(last, { content: m.content, jobs: m.jobs });
        else grouped.push({ ...m, id: String(m.id) });
      } else grouped.push({ ...m, id: String(m.id) });
    }
    setMessages(grouped);
  }

  async function send(text: string) {
    if (!text.trim() || busy) return;
    setBusy(true);
    setInput("");
    let id = threadId;
    if (!id) {
      id = (await api.post<{ id: string }>("/chat/threads")).id;
      setThreadId(id);
    }
    const n = ++seq.current;
    const replyId = `r${n}`;
    setMessages((m) => [...m, { id: `u${n}`, role: "user", content: text }, { id: replyId, role: "assistant", content: "", steps: [] }]);
    const patch = (fn: (m: Msg) => Msg) => setMessages((ms) => ms.map((m) => (m.id === replyId ? fn(m) : m)));
    try {
      for await (const ev of streamEvents(`/chat/threads/${id}/messages`, { content: text })) {
        if (ev.type === "tool") {
          const step = { id: String(ev.id), name: String(ev.name), status: ev.status as "running" | "done", summary: ev.summary as string | undefined };
          patch((m) => {
            const steps = m.steps ?? [];
            const i = steps.findIndex((s) => s.id === step.id);
            return { ...m, steps: i >= 0 ? steps.map((s, k) => (k === i ? step : s)) : [...steps, step] };
          });
        } else if (ev.type === "message") {
          patch((m) => ({ ...m, content: String(ev.content), jobs: (ev.jobs as JobItem[]) ?? [] }));
        } else if (ev.type === "error") {
          patch((m) => ({ ...m, content: String(ev.message), error: true }));
        }
      }
    } finally {
      setBusy(false);
      qc.invalidateQueries({ queryKey: ["threads"] });
      qc.invalidateQueries({ queryKey: ["applications"] });
    }
  }

  async function remove(id: string) {
    await api.del(`/chat/threads/${id}`);
    if (id === threadId) {
      setThreadId(null);
      setMessages([]);
    }
    qc.invalidateQueries({ queryKey: ["threads"] });
  }

  return (
    <AppShell>
      <div className="grid gap-8 lg:grid-cols-[15rem_1fr]">
        <aside className="hidden lg:block">
          <button
            onClick={() => {
              setThreadId(null);
              setMessages([]);
            }}
            className="mb-4 flex w-full items-center gap-2 rounded-md border border-rule-strong px-3 py-2 text-sm hover:bg-panel-2"
          >
            <Plus className="size-4" /> New chat
          </button>
          <ul className="grid gap-0.5">
            {(threads?.items ?? []).map((t) => (
              <li key={t.id} className="group flex items-center">
                <button
                  onClick={() => open(t.id)}
                  className={clsx(
                    "min-w-0 flex-1 truncate rounded-md px-3 py-2 text-left text-sm",
                    t.id === threadId ? "bg-panel-2 font-medium text-ink" : "text-ink-2 hover:bg-panel-2 hover:text-ink",
                  )}
                >
                  {t.title}
                </button>
                <button
                  onClick={() => remove(t.id)}
                  aria-label="Delete chat"
                  className="grid size-8 place-items-center rounded text-ink-3 opacity-0 hover:text-red group-hover:opacity-100 focus:opacity-100"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <section className="flex min-h-[calc(100dvh-10rem)] min-w-0 flex-col">
          {messages.length === 0 ? (
            <div className="flex flex-1 flex-col justify-center pb-10">
              <h1 className="score text-[3rem] font-extrabold uppercase leading-[0.9] md:text-[4.5rem]">Ask the assistant.</h1>
              <p className="mt-4 max-w-[56ch] text-ink-2">
                It searches the live index for you, compares roles against your resume, saves them to your tracker and sets up alerts. It
                remembers what you tell it about your search.
              </p>
              {status && !status.available ? (
                <div className="mt-6 max-w-[56ch] rounded-md border border-amber bg-panel px-4 py-3 text-sm text-ink">
                  <p>The assistant is offline right now. Your scorecard, search and tracker all work as usual.</p>
                  {me?.is_admin && (
                    <p className="mt-2 text-ink-2">Admin: add a free LLM key (GROQ_API_KEY or GEMINI_API_KEY) to the API’s environment and restart it.</p>
                  )}
                </div>
              ) : (
                <ul className="ruled mt-8 max-w-2xl border-y border-rule">
                  {STARTERS.map((s) => (
                    <li key={s}>
                      <button
                        onClick={() => send(s)}
                        className="flex w-full items-center justify-between gap-4 py-3 text-left text-[0.9375rem] text-ink transition-colors hover:text-amber-text"
                      >
                        {s}
                        <ArrowUp className="size-4 rotate-45 text-ink-3" />
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ) : (
            <div className="flex-1 space-y-8 pb-8">
              {messages.map((m) =>
                m.role === "user" ? (
                  <div key={m.id} className="flex justify-end">
                    <p className="max-w-[80%] rounded-md bg-ink px-4 py-2.5 text-bg">{m.content}</p>
                  </div>
                ) : (
                  <div key={m.id} className="grid gap-3">
                    {(m.steps ?? []).length > 0 && (
                      <ol className="grid gap-1 border-l border-rule-strong pl-4 text-sm">
                        {m.steps!.map((s) => (
                          <li key={s.id} className="flex items-center gap-2 text-ink-2">
                            {s.status === "running" ? <Spinner className="size-3" /> : <span className="size-1.5 rounded-full bg-green" aria-hidden />}
                            {TOOL_LABEL[s.name] ?? s.name}
                            {s.summary && <span className="text-ink-3">· {s.summary}</span>}
                          </li>
                        ))}
                      </ol>
                    )}
                    {m.content ? (
                      <div className={clsx("max-w-[72ch] text-[0.9375rem]", m.error ? "text-red" : "text-ink")}>
                        <Rich text={m.content} jobs={m.jobs ?? []} />
                      </div>
                    ) : (
                      busy && (
                        <span className="flex items-center gap-2 text-sm text-ink-3">
                          <Spinner className="size-3" /> Thinking…
                        </span>
                      )
                    )}
                  </div>
                ),
              )}
              <div ref={bottom} />
            </div>
          )}

          <form
            onSubmit={(e) => {
              e.preventDefault();
              send(input);
            }}
            className="sticky bottom-20 flex items-end gap-2 rounded-md border border-rule-strong bg-panel p-2 shadow-[0_6px_20px_rgb(0_0_0/0.15)] md:bottom-4"
          >
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send(input);
                }
              }}
              rows={1}
              placeholder="Ask about roles, your tracker, or what to apply to next…"
              aria-label="Message"
              className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-[0.9375rem] outline-none"
            />
            <button
              type="submit"
              disabled={busy || !input.trim()}
              aria-label="Send"
              className="grid size-10 place-items-center rounded-md bg-amber text-amber-ink disabled:opacity-40"
            >
              {busy ? <Spinner /> : <ArrowUp className="size-5" />}
            </button>
          </form>
        </section>
      </div>
    </AppShell>
  );
}
