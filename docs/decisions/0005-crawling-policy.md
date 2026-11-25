# 5. Crawling policy: public APIs and career pages, politely

## Context
Job data is the product. Some sites forbid automated access in their terms (LinkedIn,
Naukri, Internshala); others publish public job-board APIs meant for exactly this.

## Decision
- Use documented public job-board APIs (Greenhouse, Lever, Ashby, Workable,
  SmartRecruiters, Recruitee), the JSON endpoint Workday career sites use, public
  aggregator APIs (Remotive, Arbeitnow, RemoteOK, HN via Algolia), and company career
  pages through schema.org JSON-LD.
- Never log in, bypass bot protection or scrape sites whose terms prohibit it.
- Check `robots.txt` for page crawling; pace requests per host (0.25 s for big API
  CDNs, 1 s otherwise); bounded global concurrency; exponential backoff that honours
  `Retry-After`; auto-disable boards that keep returning 404.
- Every role links to the original posting; aggregator roles show their source.

## Consequences
- Coverage favours companies with modern ATSs, which matches the target employers
  (product companies, startups, quant firms, big tech with Workday).
- Discovery is automated (`rolecall discover`), so adding companies is a one-line edit to
  `seeds/candidates.txt`.
