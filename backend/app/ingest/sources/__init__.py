"""Source adapters. Each exposes ``async fetch(client, key, company_name) -> FetchResult``."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.ingest.http import PoliteClient
from app.ingest.types import FetchResult

from . import aggregators, ashby, greenhouse, hn, jsonld, lever, recruitee, smartrecruiters, workable

Fetcher = Callable[[PoliteClient, str, str | None], Awaitable[FetchResult]]

ADAPTERS: dict[str, Fetcher] = {
    "greenhouse": greenhouse.fetch,
    "lever": lever.fetch,
    "ashby": ashby.fetch,
    "workable": workable.fetch,
    "smartrecruiters": smartrecruiters.fetch,
    "recruitee": recruitee.fetch,
    "hn": hn.fetch,
    "remotive": aggregators.fetch_remotive,
    "arbeitnow": aggregators.fetch_arbeitnow,
    "remoteok": aggregators.fetch_remoteok,
    "jsonld": jsonld.fetch,
}

# ATS boards that a company owns, as opposed to aggregators listing many companies.
ATS_KINDS = {"greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee"}
AGGREGATOR_KINDS = {"hn", "remotive", "arbeitnow", "remoteok"}
