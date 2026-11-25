"use client";

import { CITIES, FAMILIES, FAMILY_LABEL, LEVEL_LABEL, LEVELS } from "@/lib/format";
import type { Family, Level, Preferences } from "@/lib/types";
import { Field, Input, Toggle, ToggleSet } from "./ui";

export function PrefsForm({ value, onChange }: { value: Preferences; onChange: (p: Preferences) => void }) {
  const set = <K extends keyof Preferences>(k: K, v: Preferences[K]) => onChange({ ...value, [k]: v });
  return (
    <div className="grid gap-8">
      <Field label="Level" hint="Roles that never state a level are shown too">
        <ToggleSet<Level> options={LEVELS} value={value.seniorities as Level[]} onChange={(v) => set("seniorities", v)} labels={LEVEL_LABEL} />
      </Field>
      <Field label="Kinds of roles" hint="General software roles are always included">
        <ToggleSet<Family>
          options={FAMILIES.filter((f) => f !== "swe")}
          value={value.role_families as Family[]}
          onChange={(v) => set("role_families", v)}
          labels={FAMILY_LABEL}
        />
      </Field>
      <Field label="Cities">
        <ToggleSet<string> options={CITIES} value={value.cities} onChange={(v) => set("cities", v)} />
      </Field>
      <Field label="Remote">
        <div className="flex flex-wrap gap-1.5">
          <Toggle on={value.remote_india} onClick={() => set("remote_india", !value.remote_india)}>
            Remote in India
          </Toggle>
          <Toggle on={value.remote_global} onClick={() => set("remote_global", !value.remote_global)}>
            Remote, open worldwide
          </Toggle>
          <Toggle on={value.onsite_global} onClick={() => set("onsite_global", !value.onsite_global)}>
            Anywhere, I’ll relocate
          </Toggle>
        </div>
      </Field>
      <Field label="Type">
        <ToggleSet<string>
          options={["intern", "full_time", "contract"]}
          value={value.employment_types}
          onChange={(v) => set("employment_types", v)}
          labels={{ intern: "Internship", full_time: "Full-time", contract: "Contract" }}
        />
      </Field>
      <Field label="Minimum pay" hint="Yearly, in lakh rupees. Roles that don’t say are kept.">
        <Input
          type="number"
          inputMode="decimal"
          min={0}
          step={0.5}
          className="max-w-40"
          placeholder="Any"
          value={value.min_salary_inr ? value.min_salary_inr / 1e5 : ""}
          onChange={(e) => set("min_salary_inr", e.target.value ? Number(e.target.value) * 1e5 : null)}
        />
      </Field>
    </div>
  );
}

export const DEFAULT_PREFS: Preferences = {
  role_families: [],
  seniorities: ["intern", "new_grad"],
  employment_types: [],
  cities: ["Bengaluru", "Mumbai"],
  remote_india: true,
  remote_global: true,
  onsite_global: false,
  min_salary_inr: null,
  excluded_companies: [],
  digest_enabled: false,
  digest_hour_ist: 9,
};
