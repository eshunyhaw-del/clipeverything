#!/usr/bin/env python3
"""clipeverything-scout - find YouTube videos that are legally reusable (Creative Commons
Attribution) and worth clipping.

  search [TOPIC ...]    search YouTube's Creative Commons filter, then VERIFY each hit's license
  check URL [URL ...]   report the license of specific videos

With no TOPIC, it searches the channel's niches (science, psychology, religion, philosophy,
language, tech). Output is JSON on stdout; progress goes to stderr.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "clipeverything" / "scripts"))
import clip as C  # noqa: E402

CC_FILTER = "EgIwAQ%253D%253D"  # YouTube's "Creative Commons" search filter
NICHES = {
    "science": "science explained",
    "psychology": "psychology lecture",
    "religion": "religion history talk",
    "philosophy": "philosophy lecture",
    "language": "linguistics language learning",
    "tech": "software engineering talk",
}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def already_clipped():
    ids = set()
    for p in C.WORK_ROOT.glob("*/meta.json"):
        try:
            ids.add(json.loads(p.read_text(encoding="utf-8")).get("id"))
        except Exception:
            pass
    ids.discard(None)
    return ids


def flat_search(query, n):
    url = ("https://www.youtube.com/results?search_query=" + urllib.parse.quote_plus(query)
           + "&sp=" + CC_FILTER)
    r = C.subprocess.run(
        C.ytdlp_base() + ["--flat-playlist", "--playlist-end", str(n), "--dump-json", url],
        capture_output=True, text=True, encoding="utf-8")
    out = []
    for line in r.stdout.splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            pass
    return out


def full_info(url):
    r = C.subprocess.run(C.ytdlp_base() + ["--dump-single-json", "--skip-download", url],
                         capture_output=True, text=True, encoding="utf-8")
    try:
        return json.loads(r.stdout)
    except Exception:
        return None


def is_cc(info):
    return bool(info) and "creative commons" in (info.get("license") or "").lower()


def summarize(info, topic=None):
    return {
        "id": info.get("id"), "url": info.get("webpage_url"), "title": info.get("title"),
        "channel": info.get("uploader") or info.get("channel"),
        "minutes": round((info.get("duration") or 0) / 60, 1),
        "views": info.get("view_count"), "uploaded": info.get("upload_date"),
        "license": info.get("license"), "topic": topic,
        "has_chapters": bool(info.get("chapters")),
        "is_live": bool(info.get("is_live")),
    }


def score(v):
    s = math.log10((v["views"] or 1) + 10)
    m = v["minutes"]
    if 10 <= m <= 70:
        s += 1.5          # long enough to hold several clip-worthy moments, short enough to process quickly
    elif 5 <= m < 10 or 70 < m <= 120:
        s += 0.5
    if v["has_chapters"]:
        s += 0.5          # chapters make picking easier
    return round(s, 2)


def cmd_search(a):
    topics = a.topics or list(NICHES)
    queries = [(t, NICHES.get(t.lower(), t)) for t in topics]
    seen_ids = already_clipped()
    cands, skipped = {}, set()
    for topic, q in queries:
        log(f"searching: {q}")
        for e in flat_search(q, a.per_topic):
            vid = e.get("id")
            if vid in seen_ids:
                skipped.add(vid)
            if not vid or vid in seen_ids or vid in cands:
                continue
            dur = e.get("duration") or 0
            if dur and not (a.min_minutes * 60 <= dur <= a.max_minutes * 60):
                continue
            cands[vid] = (topic, e.get("url") or f"https://www.youtube.com/watch?v={vid}")
    log(f"verifying license of {len(cands)} candidates...")

    def check(item):
        vid, (topic, url) = item
        info = full_info(url)
        if is_cc(info) and not info.get("is_live"):
            return summarize(info, topic)
        return None

    with ThreadPoolExecutor(max_workers=4) as ex:
        good = [v for v in ex.map(check, cands.items()) if v]
    for v in good:
        v["score"] = score(v)
    good.sort(key=lambda v: v["score"], reverse=True)
    print(json.dumps({"ok": True, "verified_cc_by": len(good), "checked": len(cands),
                      "skipped_already_clipped": len(skipped),
                      "results": good[: a.limit]}, ensure_ascii=False, indent=1))


def cmd_check(a):
    out = []
    for u in a.urls:
        info = full_info(u)
        if not info:
            out.append({"url": u, "error": "could not read this link"})
            continue
        v = summarize(info)
        v["reusable_cc_by"] = is_cc(info)
        out.append(v)
    print(json.dumps({"ok": True, "results": out}, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("search")
    s.add_argument("topics", nargs="*", help="e.g. 'stoicism' 'black holes'; default: all niches")
    s.add_argument("--per-topic", type=int, default=12)
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--min-minutes", type=float, default=5)
    s.add_argument("--max-minutes", type=float, default=120)
    s.set_defaults(fn=cmd_search)
    c = sub.add_parser("check")
    c.add_argument("urls", nargs="+")
    c.set_defaults(fn=cmd_check)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
