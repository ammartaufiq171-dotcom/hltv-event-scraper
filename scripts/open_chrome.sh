#!/usr/bin/env bash
# Launch a visible Chrome with remote debugging so the scraper can attach.
#   ./scripts/open_chrome.sh [port] [url]
# Cloudflare needs a real browser: headless gets challenged, a visible one
# usually passes on its own. Keep this window open while scraping.
set -euo pipefail

PORT="${1:-9222}"
URL="${2:-https://www.hltv.org}"
PROFILE="${HLTV_PROFILE:-$HOME/.hltv-scrape-profile}"

case "$(uname -s)" in
  Darwin) CHROME="${CHROME_PATH:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}" ;;
  Linux)  CHROME="${CHROME_PATH:-$(command -v google-chrome || command -v chromium || command -v chromium-browser || true)}" ;;
  *)      CHROME="${CHROME_PATH:-/c/Program Files/Google/Chrome/Application/chrome.exe}" ;;
esac

if [ -z "${CHROME}" ] || [ ! -x "${CHROME}" ]; then
  echo "Chrome not found. Set CHROME_PATH to your chrome binary." >&2
  exit 1
fi

# Native Chrome does not understand MSYS paths like /c/Users/... — convert.
PROFILE_ARG="${PROFILE}"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    command -v cygpath >/dev/null 2>&1 && PROFILE_ARG="$(cygpath -w "${PROFILE}")"
    ;;
esac

mkdir -p "${PROFILE}"

LOG="${TMPDIR:-/tmp}/hltv-chrome.log"
"${CHROME}" \
  --user-data-dir="${PROFILE_ARG}" \
  --remote-debugging-port="${PORT}" \
  --remote-allow-origins='*' \
  --no-first-run --no-default-browser-check \
  --window-size=1440,960 \
  --new-window "${URL}" >"${LOG}" 2>&1 &

# Wait for the debugging endpoint instead of assuming it came up.
for _ in $(seq 1 20); do
  if curl -s --max-time 2 "http://127.0.0.1:${PORT}/json/version" >/dev/null 2>&1; then
    echo "Chrome ready on port ${PORT} (profile: ${PROFILE_ARG})"
    echo "If a Cloudflare checkbox appears, click it once, then run the scraper."
    exit 0
  fi
  sleep 1
done

echo "Chrome did not expose port ${PORT}. Log: ${LOG}" >&2
tail -n 5 "${LOG}" >&2 || true
exit 1
