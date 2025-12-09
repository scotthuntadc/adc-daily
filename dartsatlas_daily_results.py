#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import dataclasses
import datetime as dt
import os
import random
import re
import sys
import time
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# -----------------------------
# Config
# -----------------------------
REGION_SEASONS: Dict[str, str] = {
    "Scotland": "https://www.dartsatlas.com/seasons/movlNEqWF4Ig/tournaments/results",
    "Wales": "https://www.dartsatlas.com/seasons/RpnPZRQjBwWr/tournaments/results",
    "Ireland": "https://www.dartsatlas.com/seasons/AoCs0GsorhFs/tournaments/results",
    "Northern Ireland": "https://www.dartsatlas.com/seasons/XEUlGJA38dDe/tournaments/results",
    "North East": "https://www.dartsatlas.com/seasons/e8Vpqo0xF9Fz/tournaments/results",
    "Yorkshire & Humber": "https://www.dartsatlas.com/seasons/DrRD8Q8UgvqG/tournaments/results",
    "North West": "https://www.dartsatlas.com/seasons/MSNax9BDyKst/tournaments/results",
    "Midlands": "https://www.dartsatlas.com/seasons/tcdTYkcNqDxZ/tournaments/results",
    "South West": "https://www.dartsatlas.com/seasons/7DDC55Km0RrP/tournaments/results",
    "South East & London": "https://www.dartsatlas.com/seasons/qcyFJeFpqqiw/tournaments/results",
    "East of England": "https://www.dartsatlas.com/seasons/JgjYUPF3pyg0/tournaments/results",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "DNT": "1",
    "Referer": "https://www.dartsatlas.com/",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}

# Tunables
DA_SLEEP = float(os.environ.get("DA_SLEEP", "0.8"))       # polite delay
DA_MAX_EVENTS = int(os.environ.get("DA_MAX_EVENTS", "0")) # 0 = no cap
DA_FORCE_MIRROR = os.environ.get("DA_FORCE_MIRROR", "0").lower() in {"1", "true", "yes"}

LONDON_TZ = dt.timezone(dt.timedelta(hours=1))
HEAVY_DIVIDER = "\n━━━━━━━━━━━━\n\n"

POINTS = {
    "Bronze": {"W": 8, "RU": 4, "SF": 2, "QF": 0},
    "Silver": {"W": 16, "RU": 8, "SF": 4, "QF": 2},
    "Gold":   {"W": 32, "RU": 16, "SF": 8, "QF": 4},
}

# -----------------------------
# Data model
# -----------------------------
@dataclasses.dataclass
class EventResult:
    region: str
    event_name: str
    event_url: str
    date: dt.date
    entrants: int
    tier: str
    winner: str
    runner_up: str
    semi_finalists: List[str]
    quarter_finalists: List[str]
    points_winner: int
    points_runner_up: int
    points_semis: int
    points_quarters: int

# -----------------------------
# HTTP helpers
# -----------------------------
def _proxied_url(url: str) -> str:
    u = url.replace("https://", "").replace("http://", "")
    return f"https://r.jina.ai/http://{u}"

def build_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s

def get_soup(url: str, session: Optional[requests.Session] = None) -> BeautifulSoup:
    s = session or build_session()
    uas = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    ]

    if not DA_FORCE_MIRROR:
        for i in range(2):
            try:
                hdrs = dict(HEADERS)
                hdrs["User-Agent"] = random.choice(uas)
                r = s.get(url, headers=hdrs, timeout=18)
                if r.status_code in (403, 429, 503):
                    raise requests.HTTPError(f"{r.status_code} from origin", response=r)
                r.raise_for_status()
                return BeautifulSoup(r.text, "html.parser")
            except requests.RequestException:
                time.sleep(0.6 + i * 0.6)

    hdrs = dict(HEADERS)
    hdrs["User-Agent"] = random.choice(uas)
    r = s.get(_proxied_url(url), headers=hdrs, timeout=22)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

# -----------------------------
# Parse helpers
# -----------------------------
def parse_tournament_date(soup: BeautifulSoup) -> Optional[dt.date]:
    """
    Extract the tournament date from a DartsAtlas tournament page.

    Priority:
    1) `<span class="calendar-event-icon"><span>YYYY</span><span>Mon</span><span>DD</span></span>`
    2) Text patterns like 'Sun 07 Dec 2025', '07 Dec 2025', '2025-12-07', etc.
    """

    # ---------- 1) Calendar icon (your example) ----------
    icon = soup.find("span", class_="calendar-event-icon") or soup.find("div", class_="calendar-event-icon")
    if icon:
        # Expect something like: 2025 | Dec | 07
        parts = [
            span.get_text(strip=True)
            for span in icon.find_all("span")
            if span.get_text(strip=True)
        ]

        # Common layouts we’ve seen:
        # [YYYY, Mon, DD]
        # [DD, Mon, YYYY]
        # [Mon, DD, YYYY]
        if len(parts) >= 3:
            month_map = {
                "Jan": 1, "January": 1,
                "Feb": 2, "February": 2,
                "Mar": 3, "March": 3,
                "Apr": 4, "April": 4,
                "May": 5,
                "Jun": 6, "June": 6,
                "Jul": 7, "July": 7,
                "Aug": 8, "August": 8,
                "Sep": 9, "Sept": 9, "September": 9,
                "Oct": 10, "October": 10,
                "Nov": 11, "November": 11,
                "Dec": 12, "December": 12,
            }

            def try_build(y_str, m_str, d_str) -> Optional[dt.date]:
                try:
                    y = int(y_str)
                    m = month_map.get(m_str.strip(), None)
                    d = int(d_str)
                    if m is None:
                        return None
                    return dt.date(y, m, d)
                except Exception:
                    return None

            # Try [YYYY, Mon, DD]
            cand = try_build(parts[0], parts[1], parts[2])
            if cand:
                return cand

            # Try [DD, Mon, YYYY]
            cand = try_build(parts[2], parts[1], parts[0])
            if cand:
                return cand

            # Try [Mon, DD, YYYY]
            cand = try_build(parts[2], parts[0], parts[1])
            if cand:
                return cand

    # ---------- 2) Fallback: text search ----------
    text = soup.get_text("\n", strip=True)
    text = re.sub(r"\s+", " ", text)

    # Month maps
    months_short = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    month_map = {m: i for i, m in enumerate(months_short, start=1)}
    long_to_short = {
        "January": "Jan", "February": "Feb", "March": "Mar", "April": "Apr",
        "May": "May", "June": "Jun", "July": "Jul", "August": "Aug",
        "September": "Sep", "October": "Oct", "November": "Nov", "December": "Dec",
    }

    # Patterns: "Sun 07 Dec 2025", "07 Dec 2025", "Dec 07 2025", "2025-12-07"
    patterns = [
        r"\b\w{3},?\s+(?P<d>\d{1,2})\s+(?P<mon>[A-Za-z]+)\s+(?P<y>20\d{2})\b",
        r"\b(?P<d>\d{1,2})\s+(?P<mon>[A-Za-z]+)\s+(?P<y>20\d{2})\b",
        r"\b(?P<mon>[A-Za-z]+)\s+(?P<d>\d{1,2}),?\s+(?P<y>20\d{2})\b",
        r"\b(?P<y>20\d{2})[-/](?P<m>\d{1,2})[-/](?P<d>\d{1,2})\b",
    ]

    for pat in patterns:
        m = re.search(pat, text)
        if not m:
            continue
        gd = m.groupdict()
        try:
            if "m" in gd:
                # direct numeric month
                y = int(gd["y"])
                mo = int(gd["m"])
                d = int(gd["d"])
                return dt.date(y, mo, d)

            # month by name
            mon = gd["mon"].title()
            mon = long_to_short.get(mon, mon)
            mo = month_map.get(mon)
            if not mo:
                continue

            y = int(gd["y"])
            d = int(gd["d"])
            return dt.date(y, mo, d)
        except Exception:
            continue

    # Couldn’t parse a date
    return None



def clean_event_name(name: str) -> str:
    return re.sub(r"^\s*Vault\s*14\.0\s*@\s*", "", name, flags=re.IGNORECASE).strip()

def clean_person_name(s: str) -> str:
    x = re.sub(r"(?:^|\s)(Final|Semi[- ]Final|Quarter[- ]Final|Quarterfinal|Semifinal)(?:\s|$)", " ", s, flags=re.IGNORECASE)
    x = re.sub(r"\bAvg\b", "", x, flags=re.IGNORECASE)
    x = re.sub(r"\s+\d+(?:\.\d+)?$", "", x)
    m = re.match(r"^\s*(.+?)\s+\1\s*$", x, flags=re.IGNORECASE)
    if m:
        x = m.group(1)
    x = re.sub(r"\s+", " ", x).strip(" -")
    return x

def determine_tier(entrants: int) -> str:
    if entrants <= 8:
        return "Bronze"
    if entrants <= 16:
        return "Silver"
    return "Gold"

def is_name_candidate(text: str) -> bool:
    if not text:
        return False
    t = re.sub(r"\s+", " ", text).strip()
    t = re.sub(r"\([^)]*\)", "", t)
    if len(t) < 3 or len(t) > 40:
        return False
    if not re.search(r"[A-Za-z]", t) or " " not in t:
        return False
    bad = {
        "group","played","pld","w","l","legs","leg","pts","points","gd",
        "avg","average","bye","walkover","tbc","reserve"
    }
    if re.fullmatch(r"[0-9:\-–./]+", t):
        return False
    if any(tok in t.lower() for tok in bad):
        return False
    return True

def get_event_title(tour_root: str, session: requests.Session) -> str:
    try:
        home = get_soup(tour_root, session)
        t_el = home.find("h2") or home.find("h1")
        if t_el:
            txt = t_el.get_text(strip=True)
            if txt:
                return clean_event_name(txt)
        og = home.find("meta", attrs={"property": "og:title"})
        if og and og.get("content"):
            return clean_event_name(og["content"])
        if home.title:
            txt = home.title.get_text(strip=True)
            if txt:
                return clean_event_name(txt)
    except Exception:
        pass
    try:
        res = get_soup(f"{tour_root}/results", session)
        t_el = res.find("h2") or res.find("h1")
        if t_el:
            txt = t_el.get_text(strip=True)
            if txt:
                return clean_event_name(txt)
        og = res.find("meta", attrs={"property": "og:title"})
        if og and og.get("content"):
            return clean_event_name(og["content"])
        if res.title:
            txt = res.title.get_text(strip=True)
            if txt:
                return clean_event_name(txt)
    except Exception:
        pass
    return tour_root

def extract_group_names(soup: BeautifulSoup) -> List[str]:
    names: set[str] = set()
    for a in soup.find_all("a"):
        href = (a.get("href") or "")
        if "/players/" in href or "/player_stats/" in href:
            nm = clean_person_name(a.get_text(strip=True))
            if is_name_candidate(nm):
                names.add(nm)
    for td in soup.select("table td"):
        t = clean_person_name(td.get_text(" ", strip=True))
        if is_name_candidate(t):
            names.add(t)
    for li in soup.find_all("li"):
        t = clean_person_name(li.get_text(" ", strip=True))
        if is_name_candidate(t):
            names.add(t)
    seen: set[str] = set()
    out: List[str] = []
    for nm in names:
        k = nm.lower()
        if k not in seen:
            seen.add(k)
            out.append(nm)
    return out

def extract_match_text_names(soup: BeautifulSoup) -> List[str]:
    text = soup.get_text("\n", strip=True)
    norm = re.sub(r"\s+", " ", text)
    pair_pats = [
        re.compile(
            r"([A-Za-z0-9 .\-'\"]+?)\s+(?:avg|Avg)\s+\d+(?:\.\d+)?\s+\d+(?:\.\d+)?\s+([A-Za-z0-9 .\-'\"]+?)\s+(?:avg|Avg)",
            re.I,
        ),
        re.compile(
            r"([A-Za-z0-9 .\-'\"]+?)\s+\d+\s*[-–]\s*\d+\s+([A-Za-z0-9 .\-'\"]+?)",
            re.I,
        ),
    ]
    names: set[str] = set()
    for pat in pair_pats:
        for left, right in pat.findall(norm):
            a = clean_person_name(left)
            b = clean_person_name(right)
            if is_name_candidate(a):
                names.add(a)
            if is_name_candidate(b):
                names.add(b)
    for m in re.finditer(r"([A-Za-z][A-Za-z .'\-]{1,38})\s+(?:avg|Avg)\b", norm):
        nm = clean_person_name(m.group(1))
        if is_name_candidate(nm):
            names.add(nm)
    seen: set[str] = set()
    out: List[str] = []
    for nm in names:
        k = nm.lower()
        if k not in seen:
            seen.add(k)
            out.append(nm)
    return out

def count_entrants(tour_root: str, session: requests.Session) -> int:
    """
    Entrants = number of unique player links on the /groups page.
    Fallback: /players page if /groups is missing or empty.

    Each unique /players/... or /player_stats/... href counts as 1 player.
    We count by href (ID), not by name, so weird names / duplicates in text
    don’t matter.
    """

    def count_player_links(url: str) -> int:
        soup = get_soup(url, session)
        player_ids: set[str] = set()

        for a in soup.find_all("a"):
            href = (a.get("href") or "").strip()
            if not href:
                continue

            # Only care about links that clearly go to a player page
            if "/players/" in href or "/player_stats/" in href:
                # Normalise: strip domain, querystring, fragment
                # so the same player/link isn’t counted twice.
                if href.startswith("http"):
                    # keep just the path part
                    try:
                        # crude but fine here
                        href = href.split("://", 1)[1]
                        href = href[href.find("/"):]  # remove host
                    except Exception:
                        pass

                href = href.split("?", 1)[0]
                href = href.split("#", 1)[0]
                player_ids.add(href)

        return len(player_ids)

    # 1) Prefer /groups – this should list every player in their group
    try:
        n = count_player_links(f"{tour_root}/groups")
        if n > 0:
            return n
    except Exception:
        pass

    # 2) Fallback to /players if /groups is missing/empty
    try:
        n = count_player_links(f"{tour_root}/players")
        if n > 0:
            return n
    except Exception:
        pass

    # 3) Last resort: 0 – caller will use estimate_entrants_from_bracket(...)
    return 0



def parse_bracket(results_url: str, session: requests.Session) -> Tuple[str, str, List[str], List[str]]:
    """
    Parse Final, Semi-Finals, Quarter-Finals from the results page.

    This version is emoji/Unicode friendly:
    - Uses (.+?) for name groups instead of [A-Za-z0-9 ...]
    - Still anchors around 'Avg' or score patterns to stay sane.
    """
    soup = get_soup(results_url, session)
    text = soup.get_text("\n", strip=True)
    norm = re.sub(r"\s+", " ", text)

    def section_block(terms: List[str]) -> str:
        for t in terms:
            m = re.search(rf"{re.escape(t)}\b", norm, flags=re.IGNORECASE)
            if m:
                return norm[m.start():]
        return norm

    # Name patterns:
    # 1) "Name Avg 4 2 Name Avg"
    # 2) "Name 4-2 Name"
    pair_pats = [
        re.compile(
            r"(.+?)\s+(?:avg|Avg)\s+(\d+)\s+(\d+)\s+(.+?)\s+(?:avg|Avg)",
            re.IGNORECASE | re.UNICODE,
        ),
        re.compile(
            r"(.+?)\s+(\d+)\s*[-–]\s*(\d+)\s+(.+?)\b",
            re.UNICODE,
        ),
    ]

    def extract_pairs(terms: List[str], expected: int) -> List[Tuple[str, str, int, int]]:
        blk = section_block(terms)
        for pat in pair_pats:
            pairs = pat.findall(blk)
            if pairs:
                out: List[Tuple[str, str, int, int]] = []
                for left, s1, s2, right in pairs[:expected]:
                    a = clean_person_name(left)
                    b = clean_person_name(right)
                    try:
                        x = int(s1)
                        y = int(s2)
                    except ValueError:
                        continue
                    out.append((a, b, x, y))
                if out:
                    return out
        return []

    # Final, Semis, Quarters
    final_pairs   = extract_pairs(["Final"], 1)
    semi_pairs    = extract_pairs(["Semi-Final", "Semifinal", "Semi final"], 2)
    quarter_pairs = extract_pairs(["Quarter-Final", "Quarterfinal", "Quarter final"], 4)

    if not final_pairs:
        raise ValueError("Could not parse Final match.")

    left, right, s1, s2 = final_pairs[0]
    winner    = left if s1 > s2 else right
    runner_up = right if s1 > s2 else left

    semi_finalists = [
        (a if x < y else b) for (a, b, x, y) in semi_pairs
    ]
    quarter_finalists = [
        (a if x < y else b) for (a, b, x, y) in quarter_pairs
    ]

    return winner, runner_up, semi_finalists, quarter_finalists


def estimate_entrants_from_bracket(semis: List[str], quarters: List[str]) -> int:
    if quarters:
        return 8
    if semis:
        return 4
    return 2

def canonical_tournament_url(url: str) -> str:
    """
    Normalise any /tournaments/... URL to the bare root:
    https://www.dartsatlas.com/tournaments/ABC123
    """
    m = re.search(r"(https?://www\.dartsatlas\.com/tournaments/[^/?#]+)", url)
    if m:
        return m.group(1)
    if "/tournaments/" in url:
        base = "https://www.dartsatlas.com"
        path = url.split("/tournaments/", 1)[1].split("/", 1)[0]
        return f"{base}/tournaments/{path}"
    return url

def is_real_tournament_url(url: str) -> bool:
    """
    Accept URLs like .../tournaments/9W0nmNWXYiQu
    Reject things ending with /schedule, /results, /players, etc.
    """
    return bool(re.search(r"/tournaments/([A-Za-z0-9]+)$", url))

# -----------------------------
# Season → tournaments
# -----------------------------
def extract_event_links_for_season(season_results_url: str, session: requests.Session) -> List[str]:
    """
    Collect all tournament links across /results, /results?page=2, /results?page=3, ...
    Stops when a page yields no new tournaments, or after 10 pages.
    """
    out: List[str] = []
    seen: set[str] = set()

    def fetch_raw(url: str) -> Tuple[str, BeautifulSoup]:
        # same robust fetch we had before (origin → mirror)
        for i in range(2):
            try:
                r = session.get(url, headers=HEADERS, timeout=18)
                if r.status_code in (403, 429, 503):
                    raise requests.HTTPError(f"{r.status_code} origin", response=r)
                r.raise_for_status()
                return r.text, BeautifulSoup(r.text, "html.parser")
            except requests.RequestException:
                time.sleep(0.6 + i)
        r = session.get(_proxied_url(url), headers=HEADERS, timeout=22)
        r.raise_for_status()
        return r.text, BeautifulSoup(r.text, "html.parser")

    page = 1
    while True:
        if page == 1:
            url = season_results_url
        else:
            url = f"{season_results_url}?page={page}"

        try:
            raw, soup = fetch_raw(url)
        except Exception as exc:
            print(f"[WARN] season fetch failed {url} -> {exc}", file=sys.stderr)
            break

        before = len(out)

        # 1) "Full Details »" links (main way DartsAtlas exposes tournaments)
        for a in soup.find_all("a"):
            if a.get_text(strip=True) == "Full Details »" and a.get("href"):
                href = a["href"].strip()
                full = urljoin("https://www.dartsatlas.com", href)
                full = canonical_tournament_url(full)
                if "/tournaments/" in full and full not in seen:
                    seen.add(full)
                    out.append(full)

        # 2) Any /tournaments/ link on the page (backup)
        for a in soup.find_all("a"):
            href = (a.get("href") or "").strip()
            if "/tournaments/" in href:
                full = urljoin("https://www.dartsatlas.com", href)
                full = canonical_tournament_url(full)
                if "/tournaments/" in full and full not in seen:
                    seen.add(full)
                    out.append(full)

        # 3) Regex fallback (if the HTML is weird)
        for m in re.finditer(r"https?://www\.dartsatlas\.com(/tournaments/[A-Za-z0-9]+)", raw):
            full = "https://www.dartsatlas.com" + m.group(1)
            full = canonical_tournament_url(full)
            if full not in seen:
                seen.add(full)
                out.append(full)

        for m in re.finditer(r"href=[\"']([^\"']*/tournaments/[A-Za-z0-9]+)[\"']", raw):
            full = urljoin("https://www.dartsatlas.com", m.group(1))
            full = canonical_tournament_url(full)
            if full not in seen:
                seen.add(full)
                out.append(full)

        added = len(out) - before
        print(f"[INFO] {season_results_url} page {page}: +{added} tournaments (total {len(out)})")

        # If this page found nothing new, we're done
        if added == 0:
            break

        page += 1
        if page > 10:
            print(f"[INFO] Reached page limit (10) for {season_results_url}")
            break

    return out


    # Full Details links
    for a in soup.find_all("a"):
        if a.get_text(strip=True) == "Full Details »" and a.get("href"):
            href = a["href"].strip()
            full = urljoin("https://www.dartsatlas.com", href)
            full = canonical_tournament_url(full)
            if "/tournaments/" in full and full not in seen:
                seen.add(full)
                out.append(full)

    # Any /tournaments/ links
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if "/tournaments/" in href:
            full = urljoin("https://www.dartsatlas.com", href)
            full = canonical_tournament_url(full)
            if "/tournaments/" in full and full not in seen:
                seen.add(full)
                out.append(full)

    if out:
        return out

    # Regex fallback
    for m in re.finditer(r"https?://www\.dartsatlas\.com(/tournaments/[A-Za-z0-9]+)", raw):
        full = "https://www.dartsatlas.com" + m.group(1)
        full = canonical_tournament_url(full)
        if full not in seen:
            seen.add(full)
            out.append(full)

    for m in re.finditer(r"href=[\"']([^\"']*/tournaments/[A-Za-z0-9]+)[\"']", raw):
        full = urljoin("https://www.dartsatlas.com", m.group(1))
        full = canonical_tournament_url(full)
        if full not in seen:
            seen.add(full)
            out.append(full)

    return out

# -----------------------------
# Collect
# -----------------------------
# -----------------------------
# Collect
# -----------------------------
def collect_for_region(
    region: str,
    season_url: str,
    target_date: dt.date,
    session: requests.Session
) -> List[EventResult]:

    rows: List[EventResult] = []
    count = 0

    # 1️⃣ Get all tournament links for this region/season
    links = extract_event_links_for_season(season_url, session)

    for link in links:

        # 2️⃣ Ignore routing pages
        if "/tournaments/schedule" in link or "/tournaments/results" in link:
            print(f"[SKIP] {region}: routing page {link}")
            continue

        # 3️⃣ Must be a real tournament URL
        if not is_real_tournament_url(link):
            continue

        # 4️⃣ Optional limit for debugging
        if DA_MAX_EVENTS and count >= DA_MAX_EVENTS:
            break
        count += 1

        tour_root = link

        try:
            # -----------------------------------------
            # 5️⃣ Extract date (home page → results page)
            # -----------------------------------------
            event_date: Optional[dt.date] = None

            try:
                home = get_soup(tour_root, session)
                event_date = parse_tournament_date(home)
            except Exception:
                pass

            if event_date is None:
                try:
                    home2 = get_soup(f"{tour_root}/results", session)
                    event_date = parse_tournament_date(home2)
                except Exception:
                    pass

            # Skip tournaments not matching target date
            if event_date is None:
                print(f"[SKIP] {region}: no parsable date for {tour_root}")
                continue

            if event_date != target_date:
                continue

            # -----------------------------------------
            # 6️⃣ Tournament title
            # -----------------------------------------
            event_name = get_event_title(tour_root, session)

            # -----------------------------------------
            # 7️⃣ Parse knockout bracket
            # -----------------------------------------
            winner, runner_up, semis, quarters = parse_bracket(
                f"{tour_root}/results", session
            )

            # -----------------------------------------
            # 8️⃣ Entrants (from /groups)
            # -----------------------------------------
            try:
                entrants = count_entrants(tour_root, session)
                if entrants == 0:
                    entrants = estimate_entrants_from_bracket(semis, quarters)
            except Exception:
                entrants = estimate_entrants_from_bracket(semis, quarters)

            # -----------------------------------------
            # 9️⃣ Tier + points allocation
            # -----------------------------------------
            tier = determine_tier(entrants)
            pts = POINTS[tier]

            # -----------------------------------------
            # 🔟 Store event row
            # -----------------------------------------
            rows.append(
                EventResult(
                    region=region,
                    event_name=event_name,
                    event_url=tour_root,
                    date=event_date,
                    entrants=entrants,
                    tier=tier,
                    winner=winner,
                    runner_up=runner_up,
                    semi_finalists=semis,
                    quarter_finalists=quarters,
                    points_winner=pts["W"],
                    points_runner_up=pts["RU"],
                    points_semis=pts["SF"],
                    points_quarters=pts["QF"],
                )
            )

        except Exception as exc:
            print(f"[WARN] {region}: failed to parse {tour_root} -> {exc}", file=sys.stderr)

        # Code-of-conduct delay (disabled when DA_SLEEP=0)
        time.sleep(DA_SLEEP)

    return rows

# -----------------------------
# Output
# -----------------------------
def to_csv(rows: List[EventResult], out_csv: os.PathLike | str) -> None:
    p = os.fspath(out_csv)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "date",
                "region",
                "event_name",
                "entrants",
                "tier",
                "winner",
                "winner_points",
                "runner_up",
                "runner_up_points",
                "semi_finalist_1",
                "semi_points",
                "semi_finalist_2",
                "semi_points",
                "quarter_finalist_1",
                "quarter_points",
                "quarter_finalist_2",
                "quarter_points",
                "quarter_finalist_3",
                "quarter_points",
                "quarter_finalist_4",
                "quarter_points",
                "event_url",
            ]
        )
        for r in rows:
            s1, s2 = (r.semi_finalists + ["", ""])[:2]
            q = (r.quarter_finalists + ["", "", "", ""])[:4]
            w.writerow(
                [
                    r.date.isoformat(),
                    r.region,
                    r.event_name,
                    r.entrants,
                    r.tier,
                    r.winner,
                    r.points_winner,
                    r.runner_up,
                    r.points_runner_up,
                    s1,
                    r.points_semis,
                    s2,
                    r.points_semis,
                    q[0],
                    r.points_quarters,
                    q[1],
                    r.points_quarters,
                    q[2],
                    r.points_quarters,
                    q[3],
                    r.points_quarters,
                    r.event_url,
                ]
            )

def _medal(tier: str) -> str:
    return {"Gold": "🥇", "Silver": "🥈", "Bronze": "🥉"}.get(tier, "")

def render_event_block(r: EventResult) -> str:
    lines: List[str] = []
    lines.append(f"📍 {r.event_name}")
    lines.append(f"👤 {r.entrants} players — {_medal(r.tier)} {r.tier}")
    lines.append("")
    lines.append(f"  🏆 Winner: {r.winner} ({r.points_winner} pts)")
    lines.append(f"  🥈 Runner-up: {r.runner_up} ({r.points_runner_up} pts)")
    if r.semi_finalists:
        lines.append(
            "  🥉 Semi-finalists: "
            + ", ".join(f"{n} ({r.points_semis} pts)" for n in r.semi_finalists)
        )
    if r.quarter_finalists:
        lines.append(
            "  ⤵️ Quarter-finalists: "
            + ", ".join(f"{n} ({r.points_quarters} pts)" for n in r.quarter_finalists)
        )
    lines.append(f"  Full Results 📱 - {r.event_url}")
    return "\n".join(lines)

def write_social_text(rows: List[EventResult], outdir: os.PathLike | str, per_region: bool = True) -> None:
    os.makedirs(os.fspath(outdir), exist_ok=True)
    divider = HEAVY_DIVIDER
    if per_region:
        by_region: Dict[str, List[EventResult]] = {}
        for r in rows:
            by_region.setdefault(r.region, []).append(r)
        for region, items in by_region.items():
            items.sort(key=lambda x: x.event_name)
            date = items[0].date if items else dt.date.today()
            fn = os.path.join(
                os.fspath(outdir), f"social_{region.replace(' ', '_')}_{date.isoformat()}.txt"
            )
            with open(fn, "w", encoding="utf-8") as f:
                f.write(f"VAULT {region} — {date:%a %d %b} Results\n\n")
                for idx, r in enumerate(items):
                    f.write(render_event_block(r))
                    if idx < len(items) - 1:
                        f.write(divider)
    else:
        if not rows:
            return
        rows.sort(key=lambda x: (x.region, x.event_name))
        date = rows[0].date
        fn = os.path.join(os.fspath(outdir), f"social_all_{date.isoformat()}.txt")
        with open(fn, "w", encoding="utf-8") as f:
            cur_region: Optional[str] = None
            for i, r in enumerate(rows):
                if r.region != cur_region:
                    cur_region = r.region
                    if i > 0:
                        f.write("\n")
                    f.write(f"VAULT {cur_region} — {r.date:%a %d %b} Results\n\n")
                f.write(render_event_block(r))
                next_same = i + 1 < len(rows) and rows[i + 1].region == cur_region
                f.write(divider if next_same else "\n")

# -----------------------------
# CLI
# -----------------------------
def _truthy(v) -> bool:
    return str(v).lower() in {"y", "yes", "1", "true", "on"}

def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="ADC DartsAtlas daily results scraper (emoji socials)"
    )
    p.add_argument(
        "--date",
        default=None,
        help="Target date YYYY-MM-DD (default: today, Europe/London)",
    )
    p.add_argument("--outdir", default="output", help="Output directory")
    p.add_argument("--regions", default="all", help="Comma-separated list or 'all'")
    p.add_argument(
        "--social-per-region",
        default="yes",
        help="Write one social text file per region",
    )
    p.add_argument("--cards", default="no")
    p.add_argument("--cards-outdir", default="output/cards")
    return p.parse_args(argv)

def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)

    if args.date:
        target_date = dt.date.fromisoformat(args.date)
    else:
        now_uk = dt.datetime.now(dt.timezone.utc).astimezone(LONDON_TZ)
        target_date = now_uk.date()

    if args.regions.lower() == "all":
        regions = list(REGION_SEASONS.items())
    else:
        wanted = {r.strip() for r in args.regions.split(",")}
        regions = [(k, v) for k, v in REGION_SEASONS.items() if k in wanted]
        if not regions:
            print("No matching regions. Available: " + ", ".join(REGION_SEASONS.keys()))
            sys.exit(2)

    session = build_session()
    all_rows: List[EventResult] = []
    for region, season_url in regions:
        all_rows.extend(collect_for_region(region, season_url, target_date, session))

    outdir = os.fspath(args.outdir)
    os.makedirs(outdir, exist_ok=True)

    csv_path = os.path.join(outdir, f"dartsatlas_results_{target_date.isoformat()}.csv")
    to_csv(all_rows, csv_path)
    print(f"Wrote CSV -> {csv_path}")

    per_region = _truthy(getattr(args, "social_per_region", "yes"))
    write_social_text(all_rows, outdir, per_region=per_region)

if __name__ == "__main__":
    main()
