import type { Family, Level, Salary } from "./types";

export const LEVEL_LABEL: Record<Level, string> = {
  intern: "Internship",
  new_grad: "New grad",
  junior: "Junior",
  mid: "Mid-level",
  senior: "Senior",
  staff_plus: "Staff+",
};

export const FAMILY_LABEL: Record<Family, string> = {
  swe: "Software",
  backend: "Backend",
  frontend: "Frontend",
  fullstack: "Full-stack",
  mobile: "Mobile",
  ml: "Machine learning",
  ai_llm: "AI / LLM",
  data_eng: "Data engineering",
  data_science: "Data science",
  infra: "Infra / DevOps",
  security: "Security",
  qa: "QA / Test",
  embedded: "Embedded",
  other: "Other",
};

export const LEVELS = Object.keys(LEVEL_LABEL) as Level[];
export const FAMILIES = (Object.keys(FAMILY_LABEL) as Family[]).filter((f) => f !== "other");

export const CITIES = [
  "Bengaluru",
  "Mumbai",
  "Hyderabad",
  "Pune",
  "Gurugram",
  "Delhi",
  "Noida",
  "Chennai",
  "Kolkata",
  "Ahmedabad",
];

export const REMOTE_LABEL: Record<string, string> = { remote: "Remote", hybrid: "Hybrid", onsite: "On-site" };

export function ago(iso: string | null | undefined): string {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  const d = Math.floor(s / 86400);
  if (d < 14) return `${d}d ago`;
  if (d < 60) return `${Math.floor(d / 7)}w ago`;
  return `${Math.floor(d / 30)}mo ago`;
}

export function num(n: number | null | undefined): string {
  return (n ?? 0).toLocaleString("en-IN");
}

function compactINR(v: number): string {
  if (v >= 1e7) return `${(v / 1e7).toFixed(v >= 1e8 ? 0 : 1)} Cr`;
  if (v >= 1e5) return `${(v / 1e5).toFixed(v >= 1e6 ? 0 : 1)} L`;
  if (v >= 1e3) return `${Math.round(v / 1e3)}k`;
  return `${Math.round(v)}`;
}

function compact(v: number): string {
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${Math.round(v / 1e3)}k`;
  return `${Math.round(v)}`;
}

const SYMBOL: Record<string, string> = { INR: "₹", USD: "$", EUR: "€", GBP: "£" };
const PERIOD: Record<string, string> = { year: "/yr", month: "/mo", hour: "/hr" };

export function salary(s: Salary | null | undefined): string | null {
  if (!s || (s.min == null && s.max == null)) return null;
  const cur = s.currency ?? "";
  const sym = SYMBOL[cur] ?? `${cur} `;
  const fmt = cur === "INR" ? compactINR : compact;
  const lo = s.min != null ? fmt(s.min) : null;
  const hi = s.max != null ? fmt(s.max) : null;
  const range = lo && hi && lo !== hi ? `${lo}–${hi}` : (lo ?? hi);
  return `${sym}${range}${PERIOD[s.period ?? "year"] ?? ""}`;
}

export function placeOf(j: { cities: string[]; remote_type: string | null; location: string | null }): string {
  if (j.cities?.length) {
    const more = j.cities.length > 1 ? ` +${j.cities.length - 1}` : "";
    return `${j.cities[0]}${more}${j.remote_type === "hybrid" ? " · hybrid" : j.remote_type === "remote" ? " · remote" : ""}`;
  }
  if (j.remote_type === "remote") return "Remote";
  return (j.location ?? "").split(/[;|]/)[0].trim().slice(0, 40) || "Location n/a";
}

export function sourceLabel(s: string): string {
  return (
    {
      greenhouse: "company board",
      lever: "company board",
      ashby: "company board",
      workable: "company board",
      smartrecruiters: "company board",
      recruitee: "company board",
      workday: "company careers site",
      jsonld: "company careers site",
      hn: "HN Who's Hiring",
      remotive: "Remotive",
      arbeitnow: "Arbeitnow",
      remoteok: "Remote OK",
    }[s] ?? s
  );
}
