#!/bin/sh
# Chạy Sentinel-2 Monitor trên Linux/macOS. Kho ảnh: $KHO_ANH (mặc định ~/KHO_ANH/TD)
cd "$(dirname "$0")"
PORT=${PORT:-8765}
URL="http://localhost:$PORT/"
( sleep 1; (xdg-open "$URL" || open "$URL") >/dev/null 2>&1 ) &
exec python3 server.py --port "$PORT" ${KHO_ANH:+--kho "$KHO_ANH"}
