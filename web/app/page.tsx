"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { ThemeToggle } from "@/components/app-shell";
import { DemoFeed } from "@/components/landing/demo";
import { EvalProof } from "@/components/landing/proof";
import { Commentary, Scoreboard } from "@/components/landing/scoreboard";
import { ButtonLink, Wordmark } from "@/components/ui";
import { api } from "@/lib/api";
import { useMe } from "@/lib/hooks";

const FEATURES = [
  {
    name: "Scorecard",
    text: "Your personal feed. Every role scored against your resume with the skills it matched, the level it targets and the red flags, like a posting that quietly asks for three years.",
  },
  {
    name: "Search",
    text: "Type what you want in plain words. Meaning-based and keyword search run together, then a reranker reads the top results again, so “ML infra intern in Bengaluru” finds model-serving roles too.",
  },
  {
    name: "Tracker",
    text: "Saved, applied, OA, interview, offer. Move roles along with a click and export the whole board to Excel whenever you want your spreadsheet back.",
  },
  {
    name: "Assistant",
    text: "Ask for “five remote ML new-grad roles from this week and save the best two”. It searches the live index, compares, saves and remembers your preferences between chats.",
  },
  {
    name: "Resumes",
    text: "Keep a SWE resume and an ML resume side by side and switch the scorecard between them. Files are read once and thrown away; your contact details are never stored.",
  },
  {
    name: "Digest",
    text: "One email a day at the hour you choose: new roles that fit, plus anything your saved searches caught.",
  },
];

function Companies() {
  const { data } = useQuery({
    queryKey: ["facets"],
    queryFn: () => api.get<{ companies: { value: string; count: number }[] }>("/facets"),
    staleTime: 10 * 60_000,
  });
  const list = data?.companies.slice(0, 120) ?? [];
  if (!list.length) return null;
  return (
    <p className="text-[0.9375rem] leading-8 text-ink-2">
      {list.map((c, i) => (
        <span key={c.value}>
          <span className="text-ink">{c.value}</span>
          <span className="text-ink-3"> {c.count}</span>
          {i < list.length - 1 && <span className="mx-2 text-rule-strong">/</span>}
        </span>
      ))}
    </p>
  );
}

export default function Landing() {
  const { data: me } = useMe();
  const primaryHref = me ? (me.onboarded ? "/feed" : "/onboarding") : "/login";

  return (
    <div className="min-h-dvh">
      <header className="mx-auto flex h-16 max-w-[1240px] items-center gap-6 px-4 md:px-6">
        <Wordmark />
        <nav className="ml-auto flex items-center gap-1 text-sm">
          <a href="#how" className="hidden px-3 py-2 text-ink-2 hover:text-ink sm:block">
            How it works
          </a>
          <Link href="/evals" className="hidden px-3 py-2 text-ink-2 hover:text-ink sm:block">
            Evals
          </Link>
          <ThemeToggle />
          <ButtonLink href={primaryHref} variant="outline" size="sm" className="ml-2">
            {me ? "Open my scorecard" : "Sign in"}
          </ButtonLink>
        </nav>
      </header>

      <main>
        <section className="mx-auto grid max-w-[1240px] gap-10 px-4 pb-16 pt-4 md:px-6 lg:grid-cols-[2fr_1fr] lg:gap-12">
          <div>
            <Scoreboard />
            <h1 className="score mt-10 max-w-[13ch] text-[3.5rem] font-extrabold uppercase text-ink md:text-[5.5rem]">
              Fresh tech roles, called out for you.
            </h1>
            <p className="mt-6 max-w-[58ch] text-lg leading-relaxed text-ink-2">
              Rolecall reads thousands of postings straight from company job boards every day, works out the level, role, skills and
              location of each, and ranks them against your resume. Internships and new-grad roles across India and remote, each with
              the reason it made your list.
            </p>
            <div className="mt-8 flex flex-wrap items-center gap-3">
              <ButtonLink href={primaryHref} variant="primary" size="lg">
                {me ? "Open my scorecard" : "Get my scorecard"} <ArrowRight className="size-5" />
              </ButtonLink>
              <ButtonLink href="#demo" variant="ghost" size="lg">
                Try it without signing in
              </ButtonLink>
            </div>
            <p className="mt-4 text-sm text-ink-3">Free. Sign in with Google, upload a resume, done in a minute.</p>
          </div>
          <aside className="lg:pt-1">
            <Commentary />
          </aside>
        </section>

        <section id="demo" className="scroll-mt-8 border-t border-rule bg-panel">
          <div className="mx-auto max-w-[1240px] px-4 py-16 md:px-6 md:py-24">
            <div className="grid gap-6 lg:grid-cols-[1fr_2fr] lg:gap-16">
              <div>
                <h2 className="score text-[2.75rem] font-extrabold uppercase leading-[0.9] md:text-[3.75rem]">Every match says why.</h2>
                <p className="mt-5 max-w-[42ch] text-ink-2">
                  The big number is how well a role fits. Underneath: the skills it matched, whether the level is right, where it is,
                  and anything that should give you pause. These are live roles ranked for a sample resume.
                </p>
              </div>
              <DemoFeed />
            </div>
          </div>
        </section>

        <section id="how" className="mx-auto max-w-[1240px] scroll-mt-8 px-4 py-16 md:px-6 md:py-24">
          <h2 className="score max-w-[16ch] text-[2.75rem] font-extrabold uppercase leading-[0.9] md:text-[3.75rem]">
            The whole hunt, one place.
          </h2>
          <dl className="ruled mt-10 border-y border-rule">
            {FEATURES.map((f) => (
              <div key={f.name} className="grid gap-2 py-6 md:grid-cols-[16rem_1fr] md:gap-10">
                <dt className="score text-[2rem] font-bold uppercase text-ink">{f.name}</dt>
                <dd className="max-w-[68ch] text-[1.0625rem] leading-relaxed text-ink-2">{f.text}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="border-t border-rule bg-panel">
          <div className="mx-auto grid max-w-[1240px] gap-10 px-4 py-16 md:px-6 md:py-24 lg:grid-cols-[1fr_2fr] lg:gap-16">
            <div>
              <h2 className="score text-[2.75rem] font-extrabold uppercase leading-[0.9] md:text-[3.75rem]">Measured, not claimed.</h2>
              <p className="mt-5 max-w-[42ch] text-ink-2">
                Ranking quality is tested every night against the live index: known-item search, persona recommendations judged by
                hand-written rules or an LLM judge, and hand-labelled postings.
              </p>
            </div>
            <EvalProof />
          </div>
        </section>

        <section className="mx-auto max-w-[1240px] px-4 py-16 md:px-6 md:py-24">
          <h2 className="score max-w-[18ch] text-[2.75rem] font-extrabold uppercase leading-[0.9] md:text-[3.75rem]">
            Straight from the company’s own board.
          </h2>
          <p className="mt-5 max-w-[60ch] text-ink-2">
            No reposts of reposts. Open roles right now, by company (the number is how many):
          </p>
          <div className="mt-8">
            <Companies />
          </div>
        </section>

        <section className="px-4 pb-16 md:px-6">
          <div className="board mx-auto flex max-w-[1240px] flex-col items-start justify-between gap-8 rounded-md p-8 md:flex-row md:items-end md:p-12">
            <p className="score max-w-[14ch] text-[2.75rem] font-extrabold uppercase leading-[0.9] text-chalk md:text-[4.5rem]">
              Your next interview is in here.
            </p>
            <ButtonLink href={primaryHref} variant="primary" size="lg">
              {me ? "Open my scorecard" : "Get my scorecard"} <ArrowRight className="size-5" />
            </ButtonLink>
          </div>
        </section>
      </main>

      <footer className="border-t border-rule">
        <div className="mx-auto flex max-w-[1240px] flex-wrap items-center justify-between gap-4 px-4 py-8 text-sm text-ink-3 md:px-6">
          <span>Rolecall · built for students hunting their first role</span>
          <span className="flex gap-4">
            <Link href="/evals" className="hover:text-ink">
              Evals
            </Link>
            <Link href="/privacy" className="hover:text-ink">
              Privacy
            </Link>
          </span>
        </div>
      </footer>
    </div>
  );
}
