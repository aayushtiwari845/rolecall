"use client";

import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AppShell } from "@/components/app-shell";
import { DEFAULT_PREFS, PrefsForm } from "@/components/prefs-form";
import { ResumeUpload } from "@/components/resume-upload";
import { Button } from "@/components/ui";
import { api } from "@/lib/api";
import { FAMILY_LABEL, LEVEL_LABEL } from "@/lib/format";
import type { Preferences, Resume } from "@/lib/types";

export default function Onboarding() {
  const [step, setStep] = useState<1 | 2>(1);
  const [resume, setResume] = useState<Resume | null>(null);
  const [prefs, setPrefs] = useState<Preferences>(DEFAULT_PREFS);
  const [saving, setSaving] = useState(false);
  const router = useRouter();
  const qc = useQueryClient();

  useEffect(() => {
    api.get<Preferences>("/preferences").then((p) => {
      if (p.seniorities.length || p.cities.length) setPrefs(p);
    }).catch(() => undefined);
  }, []);

  function acceptResume(r: Resume) {
    setResume(r);
    setPrefs((p) => ({
      ...p,
      seniorities: r.suggested_seniorities?.length ? r.suggested_seniorities : p.seniorities,
      role_families: r.suggested_role_families?.filter((f) => f !== "swe") ?? p.role_families,
    }));
  }

  async function finish() {
    setSaving(true);
    try {
      await api.put("/preferences", prefs);
      await api.post("/onboarding/complete");
      await qc.invalidateQueries({ queryKey: ["me"] });
      router.replace("/feed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <AppShell>
      <div className="mx-auto max-w-3xl">
        <ol className="mb-10 flex items-center gap-4 text-sm" aria-label="Progress">
          {["Your resume", "What you want"].map((s, i) => {
            const n = (i + 1) as 1 | 2;
            const done = step > n;
            return (
              <li key={s} className="flex items-center gap-2" aria-current={step === n ? "step" : undefined}>
                <span
                  className={`score grid size-8 place-items-center rounded-full border text-lg font-bold ${
                    step === n ? "border-amber bg-amber text-amber-ink" : done ? "border-green text-green" : "border-rule-strong text-ink-3"
                  }`}
                >
                  {done ? <Check className="size-4" /> : n}
                </span>
                <span className={step === n ? "font-semibold text-ink" : "text-ink-3"}>{s}</span>
                {i === 0 && <span className="ml-2 h-px w-10 bg-rule-strong" aria-hidden />}
              </li>
            );
          })}
        </ol>

        {step === 1 && (
          <section>
            <h1 className="score text-[3rem] font-extrabold uppercase leading-[0.9] md:text-[4rem]">Start with your resume.</h1>
            <p className="mt-4 max-w-[56ch] text-ink-2">
              It’s how Rolecall knows your skills and level. Have more than one, like a SWE and an ML version? Add the main one now and the
              rest in Settings; you can switch your scorecard between them.
            </p>
            <div className="mt-8">
              {!resume ? (
                <ResumeUpload onDone={acceptResume} />
              ) : (
                <div className="rounded-md border border-rule bg-panel p-6">
                  <p className="label text-green">Read it</p>
                  <p className="mt-2 text-lg font-semibold">{resume.headline}</p>
                  {resume.summary && <p className="mt-2 text-ink-2">{resume.summary}</p>}
                  <dl className="ruled mt-5 border-y border-rule text-sm">
                    <div className="grid grid-cols-[9rem_1fr] gap-4 py-3">
                      <dt className="text-ink-3">Skills found</dt>
                      <dd className="text-ink">{resume.skills.join(", ") || "None found"}</dd>
                    </div>
                    <div className="grid grid-cols-[9rem_1fr] gap-4 py-3">
                      <dt className="text-ink-3">Experience</dt>
                      <dd className="text-ink">
                        {resume.is_student ? `Student, graduating ${resume.graduation_year}` : `${resume.years_experience} years full-time`}
                      </dd>
                    </div>
                    <div className="grid grid-cols-[9rem_1fr] gap-4 py-3">
                      <dt className="text-ink-3">Looks like</dt>
                      <dd className="text-ink">
                        {resume.suggested_seniorities.map((l) => LEVEL_LABEL[l]).join(" or ")} ·{" "}
                        {resume.suggested_role_families.slice(0, 3).map((f) => FAMILY_LABEL[f]).join(", ")}
                      </dd>
                    </div>
                  </dl>
                  <p className="mt-3 text-xs text-ink-3">You can fix any of this in Settings later.</p>
                </div>
              )}
            </div>
            <div className="mt-8 flex items-center gap-3">
              <Button variant="primary" size="lg" onClick={() => setStep(2)} disabled={!resume}>
                Next <ArrowRight className="size-5" />
              </Button>
              {!resume && (
                <Button variant="ghost" onClick={() => setStep(2)}>
                  Skip for now
                </Button>
              )}
            </div>
          </section>
        )}

        {step === 2 && (
          <section>
            <h1 className="score text-[3rem] font-extrabold uppercase leading-[0.9] md:text-[4rem]">What are you after?</h1>
            <p className="mt-4 max-w-[56ch] text-ink-2">
              {resume ? "We filled this in from your resume. " : ""}Change anything; these decide which roles reach your scorecard.
            </p>
            <div className="mt-8">
              <PrefsForm value={prefs} onChange={setPrefs} />
            </div>
            <div className="mt-10 flex items-center gap-3">
              <Button variant="primary" size="lg" onClick={finish} disabled={saving}>
                Show my scorecard <ArrowRight className="size-5" />
              </Button>
              <Button variant="ghost" onClick={() => setStep(1)}>
                Back
              </Button>
            </div>
          </section>
        )}
      </div>
    </AppShell>
  );
}
