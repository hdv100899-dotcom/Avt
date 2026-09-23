#!/bin/sh
# Chạy Sentinel-2 Monitor trên Linux/macOS
cd "$(dirname "$0")"
PORT=8765
URL="http://localhost:$PORT/index.html"
( sleep 1; (xdg-open "$URL" || open "$URL") >/dev/null 2>&1 ) &
exec python3 -m http.server "$PORT" --bind 127.0.0.1
