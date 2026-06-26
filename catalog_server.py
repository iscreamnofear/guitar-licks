#!/usr/bin/env python3
"""
Guitar Licks local catalog server.
Runs on localhost:8765, extracts fresh video URLs via yt-dlp on demand.
Gives the catalog full HTML5 video playback with speed control.

Start: python3 catalog_server.py
Stop:  Ctrl+C
"""
from __future__ import annotations
import json, subprocess, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path

PORT = 8765
CACHE: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 3 * 3600  # 3 hours


def get_video_info(url: str) -> dict:
    """Extract video + audio URLs via yt-dlp."""
    # Check cache
    cached = CACHE.get(url)
    if cached and time.time() - cached[0] < CACHE_TTL:
        return cached[1]

    try:
        # Try combined format first, then separate video+audio
        r = subprocess.run(
            ["yt-dlp", "--dump-json", "--no-download", "--no-playlist", url],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode != 0:
            return {"error": r.stderr[:300]}

        meta = json.loads(r.stdout)
        formats = meta.get("formats", [])
        title = meta.get("title") or meta.get("description", "")[:80] or "Video"
        duration = meta.get("duration")

        # Find best combined MP4 (has both video and audio)
        combined = [f for f in formats
                    if f.get("ext") == "mp4"
                    and f.get("acodec") not in (None, "none")
                    and f.get("vcodec") not in (None, "none")
                    and f.get("url")]
        if combined:
            best = max(combined, key=lambda f: f.get("height") or 0)
            result = {
                "video_url": best["url"],
                "audio_url": None,
                "combined": True,
                "title": title,
                "duration": duration,
                "height": best.get("height"),
            }
        else:
            # Separate video + audio streams
            video_tracks = sorted(
                [f for f in formats if f.get("vcodec") not in (None, "none") and f.get("url")],
                key=lambda f: f.get("height") or 0, reverse=True
            )
            audio_tracks = sorted(
                [f for f in formats if f.get("acodec") not in (None, "none")
                 and f.get("vcodec") in (None, "none") and f.get("url")],
                key=lambda f: f.get("abr") or f.get("tbr") or 0, reverse=True
            )
            result = {
                "video_url": video_tracks[0]["url"] if video_tracks else None,
                "audio_url": audio_tracks[0]["url"] if audio_tracks else None,
                "combined": False,
                "title": title,
                "duration": duration,
                "height": video_tracks[0].get("height") if video_tracks else None,
            }

        CACHE[url] = (time.time(), result)
        return result

    except subprocess.TimeoutExpired:
        return {"error": "yt-dlp timed out after 30s"}
    except Exception as e:
        return {"error": str(e)}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[{self.address_string()}] {fmt % args}")

    def send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/health":
            self.send_response(200)
            self.send_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"ok": True, "port": PORT}).encode())
            return

        if parsed.path == "/video":
            url = params.get("url", [None])[0]
            if not url:
                self.send_response(400)
                self.send_cors()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "url param required"}).encode())
                return

            result = get_video_info(url)
            self.send_response(200 if "error" not in result else 500)
            self.send_cors()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
            return

        self.send_response(404)
        self.end_headers()


def main():
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Guitar Licks catalog server running at http://localhost:{PORT}")
    print(f"  /health  — status check")
    print(f"  /video?url=URL — extract playable video URL")
    print(f"  Cache TTL: {CACHE_TTL//3600}h")
    print(f"Stop with Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
