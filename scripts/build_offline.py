#!/usr/bin/env python3
"""
Đóng gói toàn bộ ứng dụng thành MỘT file HTML chạy ngoại tuyến (không cần web / Internet):
  - nhúng Leaflet, CSS, JS, dữ liệu thực thể, tin tức (bản chụp data/news.json);
  - nhúng ảnh vệ tinh Sentinel-2 cloudless (EOX, 10 m) cho toàn khu vực Biển Đông (zoom thấp)
    và ảnh chi tiết quanh từng thực thể (tới zoom 14).

Chạy:  python3 scripts/build_offline.py            → dist/bien-dong-offline.html
Tùy chọn: --detail-zoom 14  --ring 2  --year 2024  --out dist/xxx.html

Ảnh: "Sentinel-2 cloudless – https://s2maps.eu by EOX IT Services GmbH
(Contains modified Copernicus Sentinel data)" – giấy phép CC BY-NC-SA 4.0 (chỉ dùng phi thương mại).
"""
import argparse
import base64
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".tilecache")
VENDOR = os.path.join(ROOT, ".vendor")
UA = "Mozilla/5.0 (BienDongMonitor offline builder)"
TILE_URL = "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-{year}_3857/default/g/{z}/{y}/{x}.jpg"
LEAFLET = "https://unpkg.com/leaflet@1.9.4/dist/"
REGION = (1.5, 104.0, 22.5, 122.0)  # lat_min, lng_min, lat_max, lng_max


def tile_xy(lat, lng, z):
    n = 2 ** z
    lat = max(min(lat, 85.0), -85.0)
    x = int((lng + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def km_to_tiles(km, lat, z):
    tile_km = 40075.0 * math.cos(math.radians(lat)) / (2 ** z)
    return max(0, math.ceil(km / tile_km))


def load_features():
    js = ("global.window={};require(%r);process.stdout.write(JSON.stringify(window.DEFAULT_FEATURES))"
          % os.path.join(ROOT, "js", "data.js"))
    return json.loads(subprocess.check_output(["node", "-e", js]))


def tile_set(features, detail_zoom, ring):
    tiles = set()
    lat0, lng0, lat1, lng1 = REGION
    for z in range(2, 9):  # toàn khu vực
        x0, y0 = tile_xy(lat1, lng0, z)
        x1, y1 = tile_xy(lat0, lng1, z)
        tiles |= {(z, x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
    for f in features:
        lat, lng = f["lat"], f["lng"]
        r_km = float(f.get("radiusKm") or 0)
        levels = [10, 12, detail_zoom] if detail_zoom > 12 else [10, detail_zoom]
        for z in levels:
            r = ring if z == detail_zoom else 1
            if r_km and z < detail_zoom:  # cụm / bãi lớn: phủ toàn bán kính ở zoom trung bình
                r = max(r, km_to_tiles(r_km, lat, z))
                r = min(r, 6)
            cx, cy = tile_xy(lat, lng, z)
            tiles |= {(z, cx + dx, cy + dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1)}
    return tiles


def get(url, path, tries=4):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        return open(path, "rb").read()
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=30) as r:
                data = r.read()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
            return data
        except Exception as e:  # noqa: BLE001
            if i == tries - 1:
                print(f"  ! bỏ qua {url}: {e}", file=sys.stderr)
            time.sleep(1.5 * (i + 1))
    return None


def fetch_tiles(tiles, year):
    out = {}

    def job(t):
        z, x, y = t
        data = get(TILE_URL.format(year=year, z=z, x=x, y=y), os.path.join(CACHE, str(year), str(z), str(x), f"{y}.jpg"))
        return t, data

    done = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for (z, x, y), data in ex.map(job, sorted(tiles)):
            done += 1
            if data:
                out[f"{z}/{x}/{y}"] = base64.b64encode(data).decode()
            if done % 200 == 0:
                print(f"  ảnh {done}/{len(tiles)}")
    return out


def data_uri(path_or_url, cache_name, mime):
    data = get(path_or_url, os.path.join(VENDOR, cache_name)) if path_or_url.startswith("http") else open(path_or_url, "rb").read()
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def safe_script(js):
    return js.replace("</script", "<\\/script")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--detail-zoom", type=int, default=14)
    ap.add_argument("--ring", type=int, default=2, help="số ô quanh tâm ở zoom chi tiết (2 → lưới 5x5)")
    ap.add_argument("--year", default="2024")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", "bien-dong-offline.html"))
    a = ap.parse_args()

    features = load_features()
    tiles = tile_set(features, a.detail_zoom, a.ring)
    print(f"{len(features)} thực thể → {len(tiles)} ô ảnh vệ tinh cần nhúng")
    tile_b64 = fetch_tiles(tiles, a.year)
    print(f"Đã có {len(tile_b64)} ô ảnh")

    leaflet_js = get(LEAFLET + "leaflet.js", os.path.join(VENDOR, "leaflet.js")).decode()
    leaflet_css = get(LEAFLET + "leaflet.css", os.path.join(VENDOR, "leaflet.css")).decode()
    for img in ("layers.png", "layers-2x.png", "marker-icon.png"):
        leaflet_css = leaflet_css.replace(f"url(images/{img})", f"url({data_uri(LEAFLET + 'images/' + img, img, 'image/png')})")

    read = lambda p: open(os.path.join(ROOT, p), encoding="utf-8").read()
    html = read("index.html")
    news_path = os.path.join(ROOT, "data", "news.json")
    news = json.load(open(news_path, encoding="utf-8")) if os.path.exists(news_path) else {"articles": []}
    payload = ("window.OFFLINE_TILES=" + json.dumps(tile_b64, separators=(",", ":")) + ";\n"
               "window.EMBEDDED_NEWS=" + json.dumps(news, ensure_ascii=False, separators=(",", ":")) + ";\n"
               "window.OFFLINE_BUILT=" + json.dumps(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())) + ";")

    def sub(pattern, repl):
        nonlocal html
        new = re.sub(pattern, lambda m: repl, html, count=1)
        if new == html:
            sys.exit(f"Không tìm thấy mẫu cần thay: {pattern}")
        html = new

    sub(r'<link rel="stylesheet" href="https://unpkg.com/leaflet@[^"]+" />', f"<style>{leaflet_css}</style>")
    sub(r'<link rel="stylesheet" href="css/style.css" />', f"<style>{read('css/style.css')}</style>")
    sub(r'<link rel="apple-touch-icon" href="icon.png" />',
        f'<link rel="apple-touch-icon" href="{data_uri(os.path.join(ROOT, "icon.png"), "", "image/png")}" />')
    sub(r'<script src="https://unpkg.com/leaflet@[^"]+"></script>', f"<script>{safe_script(leaflet_js)}</script>")
    sub(r'<script src="js/data.js"></script>',
        f"<script>{safe_script(read('js/data.js'))}</script>\n  <script>{safe_script(payload)}</script>")
    sub(r'<script src="js/app.js"></script>', f"<script>{safe_script(read('js/app.js'))}</script>")
    html = html.replace("<title>Hệ thống giám sát Biển Đông</title>", "<title>Giám sát Biển Đông (ngoại tuyến)</title>")

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"Đã tạo {a.out} ({os.path.getsize(a.out) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
