#!/usr/bin/env python3
"""Update static Google Scholar citation badges in the homepage HTML."""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


SCHOLAR_URL = "https://scholar.google.com/citations"
DEFAULT_USER_ID = "wnc_GPkAAAAJ"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


@dataclass(frozen=True)
class ScholarMetrics:
    citations: int
    h_index: int
    i10_index: int
    papers: dict[str, int]


def fetch_scholar_profile(user_id: str, retries: int = 2) -> str:
    url = f"{SCHOLAR_URL}?hl=en&user={user_id}&pagesize=100"
    request = Request(url, headers={"User-Agent": USER_AGENT})
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=25) as response:
                return response.read().decode("utf-8", "replace")
        except (HTTPError, URLError, TimeoutError) as error:
            last_error = error
            if attempt < retries:
                time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(f"Could not fetch Google Scholar profile: {last_error}")


def strip_tags(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def parse_profile_metrics(scholar_html: str, user_id: str) -> ScholarMetrics:
    metric_rows = re.findall(
        r'<td class="gsc_rsb_sc1">.*?>(Citations|h-index|i10-index)</a></td>'
        r'<td class="gsc_rsb_std">(\d+)</td>',
        scholar_html,
        flags=re.S,
    )
    metrics = {name: int(value) for name, value in metric_rows}
    missing = {"Citations", "h-index", "i10-index"} - metrics.keys()
    if missing:
        raise RuntimeError(f"Could not parse Scholar profile metrics: {sorted(missing)}")

    paper_counts: dict[str, int] = {}
    rows = re.findall(r'<tr class="gsc_a_tr">(.*?)</tr>', scholar_html, flags=re.S)
    id_pattern = re.compile(
        rf"citation_for_view={re.escape(user_id)}:([A-Za-z0-9_-]+)"
    )

    for row in rows:
        id_match = id_pattern.search(row)
        if not id_match:
            continue
        count_match = re.search(
            r'<td class="gsc_a_c">(?:<a [^>]*class="gsc_a_ac[^"]*"[^>]*>)?'
            r'(\d*)',
            row,
            flags=re.S,
        )
        if count_match:
            paper_counts[id_match.group(1)] = int(count_match.group(1) or "0")

    return ScholarMetrics(
        citations=metrics["Citations"],
        h_index=metrics["h-index"],
        i10_index=metrics["i10-index"],
        papers=paper_counts,
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

    notes = [f"profile=1", f"paper_badges={paper_replacements}"]
    if missing:
        notes.append("missing_paper_ids=" + ",".join(missing))
    return updated, notes


def default_homepage_path() -> Path:
    if Path("index.html").is_file():
        return Path("index.html")
    return Path("homepage/index.html")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Google Scholar metrics and update homepage citation badges."
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
        "--scholar-html",
        help="Optional saved Scholar HTML file for offline/reproducible updates.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Parse and report metrics without writing the homepage.",
    )
    parser.add_argument(
        "--allow-fetch-failure",
        action="store_true",
        help="Exit successfully without changes if Google Scholar blocks the fetch.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    homepage_path = Path(args.homepage) if args.homepage else default_homepage_path()
    if args.scholar_html:
        scholar_html = Path(args.scholar_html).read_text(encoding="utf-8")
    else:
        try:
            scholar_html = fetch_scholar_profile(args.user)
        except RuntimeError as error:
            if not args.allow_fetch_failure:
                raise
            message = (
                "Google Scholar metrics were not updated because the profile "
                f"fetch failed: {error}"
            )
            if os.environ.get("GITHUB_ACTIONS"):
                print(f"::warning::{message}")
            else:
                print(f"Warning: {message}", file=sys.stderr)
            return 0

    metrics = parse_profile_metrics(scholar_html, args.user)
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
            print("Homepage is not up to date.", file=sys.stderr)
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
