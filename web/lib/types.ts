export type Level = "intern" | "new_grad" | "junior" | "mid" | "senior" | "staff_plus";
export type Family =
  | "swe"
  | "backend"
  | "frontend"
  | "fullstack"
  | "mobile"
  | "ml"
  | "ai_llm"
  | "data_eng"
  | "data_science"
  | "infra"
  | "security"
  | "qa"
  | "embedded"
  | "other";
export type AppStatus = "saved" | "applied" | "oa" | "interview" | "offer" | "rejected" | "withdrawn";

export interface Salary {
  min: number | null;
  max: number | null;
  currency: string | null;
  period: string | null;
}

export interface JobItem {
  id: string;
  title: string;
  company: string;
  url: string;
  location: string | null;
  cities: string[];
  remote_type: "onsite" | "hybrid" | "remote" | null;
  seniority: Level | null;
  role_family: Family | null;
  employment_type: string | null;
  skills: string[];
  posted_at: string | null;
  salary: Salary | null;
  source: string;
  match: number;
  reasons: string[];
  warnings: string[];
  matched_skills: string[];
  missing_skills: string[];
  features: Record<string, number>;
  saved?: boolean;
}

export interface JobDetail {
  id: string;
  title: string;
  company: string;
  url: string;
  apply_url: string;
  location: string | null;
  cities: string[];
  countries: string[];
  remote_type: string | null;
  seniority: Level | null;
  role_family: Family | null;
  employment_type: string | null;
  skills: string[];
  min_yoe: number | null;
  max_yoe: number | null;
  salary: Salary | null;
  summary: string | null;
  description: string;
  department: string | null;
  posted_at: string | null;
  first_seen_at: string | null;
  status: string;
  source: string;
  match?: JobItem;
  saved?: boolean;
}

export interface JobFilters {
  seniorities: string[];
  include_unknown_level: boolean;
  role_families: string[];
  employment_types: string[];
  cities: string[];
  remote_india: boolean;
  remote_global: boolean;
  onsite_anywhere: boolean;
  countries: string[];
  companies: string[];
  exclude_companies: string[];
  company_tags: string[];
  posted_within_days: number | null;
  min_salary_inr: number | null;
  salary_disclosed: boolean;
  skills: string[];
}

export interface Me {
  id: string;
  email: string;
  name: string | null;
  avatar_url: string | null;
  is_admin: boolean;
  onboarded: boolean;
}

export interface Resume {
  id: string;
  label: string;
  is_default: boolean;
  created_at: string;
  skills: string[];
  years_experience: number;
  parsed_by: string;
  headline: string | null;
  summary: string | null;
  target_titles: string[];
  suggested_role_families: Family[];
  suggested_seniorities: Level[];
  graduation_year: number | null;
  is_student: boolean | null;
}

export interface Preferences {
  role_families: string[];
  seniorities: string[];
  employment_types: string[];
  cities: string[];
  remote_india: boolean;
  remote_global: boolean;
  onsite_global: boolean;
  min_salary_inr: number | null;
  excluded_companies: string[];
  digest_enabled: boolean;
  digest_hour_ist: number;
}

export interface Application {
  id: string;
  job_id: string | null;
  company: string;
  title: string;
  url: string | null;
  location: string | null;
  status: AppStatus;
  notes: string;
  sort_order: number;
  applied_at: string | null;
  created_at: string;
  updated_at: string | null;
  job_open: boolean | null;
  seniority: Level | null;
  remote_type: string | null;
}

export interface Stats {
  open_jobs: number;
  new_today: number;
  new_this_week: number;
  india_jobs: number;
  early_career_jobs: number;
  companies: number;
  sources: number;
  last_crawl: string;
  users: number;
  tracked_companies: number;
}

export interface LatestJob {
  id: string;
  title: string;
  company: string;
  location: string | null;
  remote_type: string | null;
  seniority: Level | null;
  first_seen_at: string;
}

export interface Alert {
  id: string;
  name: string;
  query: string;
  filters: Partial<JobFilters>;
  enabled: boolean;
  last_sent_at: string | null;
}
