#!/usr/bin/env python3
"""Batch fetch metadata for all guitar lick URLs using yt-dlp."""

import json, subprocess, sys, os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import urllib.request, hashlib, re

URLS_FILE = "/tmp/guitar_licks_urls.json"
OUT_JSON = "/tmp/guitar-licks/data/links.json"
THUMBS_DIR = Path("/tmp/guitar-licks/data/thumbnails")
THUMBS_DIR.mkdir(parents=True, exist_ok=True)

def clean_title(meta, platform):
    """Extract best title from yt-dlp output."""
    desc = meta.get("description", "") or ""
    title = meta.get("title", "") or ""
    uploader = meta.get("uploader", "") or ""

    if platform == "facebook":
        # FB title is ugly. Use first line of description.
        first = desc.split("\n")[0].strip() if desc else ""
        if first and len(first) > 5:
            return first[:120]
        return title[:120] if title else "Facebook video"
    elif platform == "instagram":
        # IG title is generic. Use caption first line.
        first = desc.split("\n")[0].strip() if desc else ""
        if first and len(first) > 5:
            return f"{first[:100]}"
        return f"Video by {uploader}" if uploader else "Instagram reel"
    else:
        return (title or desc or "Link")[:120]

def download_thumb(url, slug):
    """Download thumbnail, return local path relative to data/thumbnails/."""
    if not url:
        return None
    ext = ".jpg"
    fname = f"{slug}{ext}"
    fpath = THUMBS_DIR / fname
    if fpath.exists():
        return f"data/thumbnails/{fname}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            fpath.write_bytes(r.read())
        return f"data/thumbnails/{fname}"
    except Exception as e:
        print(f"  thumb fail {slug}: {e}", file=sys.stderr)
        return None

def fetch_one(entry):
    url = entry["url"]
    platform = entry["platform"]
    slug = hashlib.md5(url.encode()).hexdigest()[:12]

    try:
        result = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-download", "--no-playlist", url],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr[:200])
        meta = json.loads(result.stdout)
        title = clean_title(meta, platform)
        description = (meta.get("description") or "")[:500]
        raw_thumb = meta.get("thumbnail") or (meta.get("thumbnails") or [{}])[-1].get("url")
        thumb_local = download_thumb(raw_thumb, slug)
        return {**entry, "title": title, "description": description,
                "thumbnail": thumb_local, "thumb_raw": raw_thumb,
                "uploader": meta.get("uploader", ""), "duration": meta.get("duration")}
    except Exception as e:
        print(f"  FAIL {url[:60]}: {e}", file=sys.stderr)
        return {**entry, "title": None, "description": None, "thumbnail": None}

def main():
    with open(URLS_FILE) as f:
        entries = json.load(f)

    print(f"Fetching metadata for {len(entries)} URLs with 10 workers...")
    results = [None] * len(entries)
    idx_map = {entry["url"]: i for i, entry in enumerate(entries)}

    with ThreadPoolExecutor(max_workers=10) as pool:
        futures = {pool.submit(fetch_one, e): e["url"] for e in entries}
        done = 0
        for fut in as_completed(futures):
            done += 1
            r = fut.result()
            results[idx_map[r["url"]]] = r
            if done % 20 == 0:
                print(f"  {done}/{len(entries)} done...")

    # Write final JSON
    with open(OUT_JSON, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    ok = sum(1 for r in results if r.get("title"))
    thumbs = sum(1 for r in results if r.get("thumbnail"))
    print(f"\nDone. {ok}/{len(results)} with title, {thumbs}/{len(results)} with thumbnail.")
    print(f"Output: {OUT_JSON}")

if __name__ == "__main__":
    main()
