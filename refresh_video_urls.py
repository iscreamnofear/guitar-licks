#!/usr/bin/env python3
"""
Refresh video CDN URLs in links.json using yt-dlp.

Facebook/Instagram CDN URLs in the 'video_url' field expire after ~4-7 days.
This script re-fetches fresh URLs for all entries and updates links.json in place.
Designed to run in GitHub Actions on a schedule (no Telegram session needed).

Usage:
    python3 refresh_video_urls.py              # refresh all expired + missing
    python3 refresh_video_urls.py --all        # force-refresh every entry
"""
from __future__ import annotations

import json, subprocess, sys, time, re, hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_DIR = Path(__file__).parent
DATA_JSON = REPO_DIR / "data" / "links.json"
THUMBS_DIR = REPO_DIR / "data" / "thumbnails"
WORKERS = 8
TIMEOUT = 30


def oe_expiry(url: str) -> int:
    """Return unix timestamp when the CDN URL expires (0 if no oe= found)."""
    m = re.search(r"oe=([0-9a-fA-F]+)", url or "")
    return int(m.group(1), 16) if m else 0


def needs_refresh(entry: dict, force: bool = False) -> bool:
    if force:
        return True
    vurl = entry.get("video_url") or ""
    if not vurl:
        return True
    exp = oe_expiry(vurl)
    # Refresh if expired or expiring within 12 hours
    return exp == 0 or (exp - int(time.time())) < 43200


def fetch_video_url(entry: dict) -> dict:
    url = entry["url"]
    platform = entry.get("platform", "other")
    if platform not in ("facebook", "instagram", "youtube"):
        return {**entry}  # nothing to refresh for 'other'

    try:
        r = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-download", "--no-playlist", url],
            capture_output=True, text=True, timeout=TIMEOUT
        )
        if r.returncode != 0:
            print(f"  SKIP {url[:60]}: {r.stderr[:120]}", file=sys.stderr)
            return {**entry}

        meta = json.loads(r.stdout)
        formats = meta.get("formats", [])

        # Prefer combined MP4 (video + audio)
        combined = sorted(
            [f for f in formats
             if f.get("ext") == "mp4"
             and f.get("acodec") not in (None, "none")
             and f.get("vcodec") not in (None, "none")
             and f.get("url")],
            key=lambda f: f.get("height") or 0, reverse=True
        )
        if combined:
            return {**entry, "video_url": combined[0]["url"], "video_is_hls": False}

        # Fall back to best video track (DASH)
        video_tracks = sorted(
            [f for f in formats if f.get("vcodec") not in (None, "none") and f.get("url")],
            key=lambda f: f.get("height") or 0, reverse=True
        )
        if video_tracks:
            return {**entry, "video_url": video_tracks[0]["url"], "video_is_hls": False}

        return {**entry}

    except subprocess.TimeoutExpired:
        print(f"  TIMEOUT {url[:60]}", file=sys.stderr)
        return {**entry}
    except Exception as e:
        print(f"  ERROR {url[:60]}: {e}", file=sys.stderr)
        return {**entry}


def main():
    force = "--all" in sys.argv
    data = json.loads(DATA_JSON.read_text())
    now = int(time.time())

    to_refresh = [e for e in data if needs_refresh(e, force=force)]
    skip = len(data) - len(to_refresh)
    print(f"Total entries: {len(data)} | Skipping (fresh): {skip} | Refreshing: {len(to_refresh)}")

    if not to_refresh:
        print("All URLs are fresh. Nothing to do.")
        return

    url_map = {e["url"]: e for e in data}
    idx_map = {e["url"]: i for i, e in enumerate(data)}

    ok = fail = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(fetch_video_url, e): e["url"] for e in to_refresh}
        for fut in as_completed(futures):
            result = fut.result()
            url = result["url"]
            i = idx_map[url]
            if result.get("video_url") and result["video_url"] != data[i].get("video_url"):
                data[i] = result
                ok += 1
                print(f"  OK  {url[:70]}")
            else:
                fail += 1

    DATA_JSON.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"\nRefreshed {ok} URLs, {fail} failed/unchanged. links.json updated.")


if __name__ == "__main__":
    main()
