#!/bin/bash
# Guitar Licks CDN URL refresh. Runs via LaunchAgent every 8 hours.
# Reads iscreamnofear token from gh credential store at runtime (never writes it to disk).
# Pushes updated data/links.json only; no workflow-scope operations.

REPO_DIR="$HOME/Documents/guitar-licks"
LOG="$HOME/Library/Logs/guitar-licks-refresh.log"
YTDLP="/opt/homebrew/bin/yt-dlp"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "=== Refresh started ==="
cd "$REPO_DIR" || { log "ERROR: repo dir not found at $REPO_DIR"; exit 1; }

# Verify yt-dlp is available
if [ ! -x "$YTDLP" ]; then
  YTDLP=$(which yt-dlp 2>/dev/null)
  [ -z "$YTDLP" ] && { log "ERROR: yt-dlp not found"; exit 1; }
fi

# Pull latest (uses OfirBlochWalkMe read access, which is fine for public repo)
git pull --quiet origin main 2>&1 | tee -a "$LOG"

# Run refresh (uses local yt-dlp, reads/writes data/links.json in-place)
log "Running refresh_video_urls.py..."
python3 "$REPO_DIR/refresh_video_urls.py" 2>&1 | tee -a "$LOG"

# Push only if something changed
git add data/links.json
if git diff --cached --quiet; then
  log "No URLs changed. Nothing to push."
  exit 0
fi

git config user.name "guitar-licks-refresh"
git config user.email "noreply@github.com"
git commit -m "chore: refresh video CDN URLs [skip ci]" 2>&1 | tee -a "$LOG"

# Use iscreamnofear token from gh credential store (in-memory env var, not written to disk)
ISCREAM_TOKEN=$(gh auth token -u iscreamnofear 2>/dev/null)
if [ -z "$ISCREAM_TOKEN" ]; then
  log "ERROR: Could not retrieve iscreamnofear token from gh credential store"
  git reset HEAD~1
  exit 1
fi

GH_TOKEN="$ISCREAM_TOKEN" git push origin main 2>&1 | tee -a "$LOG"
log "Pushed refreshed links.json to GitHub. Catalog updated."
log "=== Refresh complete ==="
