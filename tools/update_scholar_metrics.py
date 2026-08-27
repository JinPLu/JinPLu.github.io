#!/usr/bin/env python3
"""Update static Google Scholar citation badges in the homepage HTML."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SERPAPI_URL = "https://serpapi.com/search.json"
DEFAULT_USER_ID = "wnc_GPkAAAAJ"
API_KEY_ENV = "SERPAPI_API_KEY"


@dataclass(frozen=True)
class ScholarMetrics:
    citations: int
    h_index: int
    i10_index: int
    papers: dict[str, int]


def fetch_scholar_payload(user_id: str, api_key: str, retries: int = 2) -> dict:
    query = urlencode(
        {
            "engine": "google_scholar_author",
            "author_id": user_id,
            "hl": "en",
            "num": 100,
            "api_key": api_key,
        }
    )
    request = Request(f"{SERPAPI_URL}?{query}")
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=40) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            detail = error.read().decode("utf-8", "replace").strip()[:300]
            last_error = RuntimeError(f"HTTP {error.code}: {detail}")
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            last_error = error
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(f"Could not fetch Scholar metrics from SerpApi: {last_error}")


def parse_metrics(payload: dict, user_id: str) -> ScholarMetrics:
    if payload.get("error"):
        raise RuntimeError(f"SerpApi reported an error: {payload['error']}")

    status = payload.get("search_metadata", {}).get("status")
    if status != "Success":
        raise RuntimeError(f"SerpApi search did not succeed: status={status!r}")

    profile: dict[str, int] = {}
    for row in payload.get("cited_by", {}).get("table", []):
        for name, values in row.items():
            total = values.get("all")
            if total is not None:
                profile[name] = int(total)

    missing = sorted({"citations", "h_index", "i10_index"} - profile.keys())
    if missing:
        raise RuntimeError(f"SerpApi response is missing profile metrics: {missing}")

    papers: dict[str, int] = {}
    for article in payload.get("articles", []):
        author_id, _, paper_id = article.get("citation_id", "").partition(":")
        if author_id != user_id or not paper_id:
            continue
        papers[paper_id] = int((article.get("cited_by") or {}).get("value") or 0)

    if not papers:
        raise RuntimeError(f"SerpApi response listed no articles for author {user_id}")

    return ScholarMetrics(
        citations=profile["citations"],
        h_index=profile["h_index"],
        i10_index=profile["i10_index"],
        papers=papers,
    )


def citation_badge_url(count: int) -> str:
    return (
        f"https://img.shields.io/badge/citations-{count}-blue?"
        "logo=google-scholar&amp;logoColor=white&amp;style=flat-square"
    )


def update_profile_badge(homepage_html: str, metrics: ScholarMetrics) -> tuple[str, int]:
    pattern = re.compile(
        r'(<p class="citation-overview">.*?'
        r'<img src=")https://img\.shields\.io/badge/citations-\d+-blue\?'
        r'logo=google-scholar&amp;logoColor=white&amp;style=flat-square'
        r'(" alt="Google Scholar citations: )\d+(">\s*</a>\s*'
        r'<span class="citation-stats">h-index )\d+( · i10-index )\d+(</span>)',
        flags=re.S,
    )

    def replace(match: re.Match[str]) -> str:
        return (
            f"{match.group(1)}{citation_badge_url(metrics.citations)}"
            f"{match.group(2)}{metrics.citations}{match.group(3)}"
            f"{metrics.h_index}{match.group(4)}{metrics.i10_index}{match.group(5)}"
        )

    return pattern.subn(replace, homepage_html, count=1)


def update_paper_badges(
    homepage_html: str, metrics: ScholarMetrics, user_id: str
) -> tuple[str, int, list[str]]:
    id_pattern = re.compile(rf"citation_for_view={re.escape(user_id)}:([A-Za-z0-9_-]+)")
    homepage_ids = set(id_pattern.findall(homepage_html))
    missing = sorted(paper_id for paper_id in homepage_ids if paper_id not in metrics.papers)

    updated = homepage_html
    changed = 0
    for paper_id in sorted(homepage_ids):
        if paper_id not in metrics.papers:
            continue
        count = metrics.papers[paper_id]
        pattern = re.compile(
            rf'(citation_for_view={re.escape(user_id)}:{re.escape(paper_id)}'
            rf'[^"]*" target="_blank" rel="noopener">\s*'
            rf'<img src=")https://img\.shields\.io/badge/citations-\d+-blue\?'
            rf'logo=google-scholar&amp;logoColor=white&amp;style=flat-square'
            rf'(" alt="Google Scholar citations: )\d+(">)',
            flags=re.S,
        )
        updated, replacements = pattern.subn(
            rf"\g<1>{citation_badge_url(count)}\g<2>{count}\g<3>",
            updated,
            count=1,
        )
        changed += replacements

    return updated, changed, missing


def update_homepage(homepage_html: str, metrics: ScholarMetrics, user_id: str) -> tuple[str, list[str]]:
    updated, profile_replacements = update_profile_badge(homepage_html, metrics)
    updated, paper_replacements, missing = update_paper_badges(updated, metrics, user_id)

    if profile_replacements != 1:
        raise RuntimeError(
            f"Expected to update 1 profile citation badge, updated {profile_replacements}."
        )

    # A homepage id absent from the profile means Scholar re-issued that entry: the badge
    # would freeze and its link would 404, so this has to be fixed rather than skipped.
    if missing:
        raise RuntimeError(
            "Homepage badges reference Scholar entries that the profile no longer lists: "
            + ", ".join(missing)
        )

    return updated, [f"profile={profile_replacements}", f"paper_badges={paper_replacements}"]


def default_homepage_path() -> Path:
    if Path("index.html").is_file():
        return Path("index.html")
    return Path("homepage/index.html")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Fetch Google Scholar metrics through the SerpApi Google Scholar Author API "
            "and update the homepage citation badges."
        )
    )
    parser.add_argument("--user", default=DEFAULT_USER_ID, help="Google Scholar user id.")
    parser.add_argument(
        "--homepage",
        help=(
            "Path to homepage HTML. Defaults to index.html when run inside "
            "homepage/, otherwise homepage/index.html."
        ),
    )
    parser.add_argument(
        "--metrics-json",
        help="Saved SerpApi response for offline or reproducible updates.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Parse and report metrics without writing the homepage.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    homepage_path = Path(args.homepage) if args.homepage else default_homepage_path()

    if args.metrics_json:
        payload = json.loads(Path(args.metrics_json).read_text(encoding="utf-8"))
    else:
        api_key = os.environ.get(API_KEY_ENV, "").strip()
        if not api_key:
            raise RuntimeError(
                f"{API_KEY_ENV} is not set. Export the SerpApi key, or pass --metrics-json "
                "to update from a saved response."
            )
        payload = fetch_scholar_payload(args.user, api_key)

    metrics = parse_metrics(payload, args.user)
    homepage_html = homepage_path.read_text(encoding="utf-8")
    updated, notes = update_homepage(homepage_html, metrics, args.user)

    print(
        "Scholar metrics: "
        f"citations={metrics.citations}, h-index={metrics.h_index}, "
        f"i10-index={metrics.i10_index}, papers={len(metrics.papers)}"
    )
    print("Homepage updates: " + ", ".join(notes))

    if args.check:
        if updated != homepage_html:
            print("Homepage is not up to date.")
            return 1
        print("Homepage is up to date.")
        return 0

    if updated != homepage_html:
        homepage_path.write_text(updated, encoding="utf-8")
        print(f"Updated {homepage_path}")
    else:
        print(f"No changes needed for {homepage_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
