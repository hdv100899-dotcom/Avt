#!/usr/bin/env python3
"""
Xây hồ sơ cho các thực thể từ Wikipedia (tiếng Anh + tiếng Việt) và Wikidata.

Với mỗi thực thể trong js/data.js:
  1. MỘT truy vấn SPARQL Wikidata lấy mọi mục có tọa độ trong khung Biển Đông và có bài Wikipedia EN/VI
     (kèm diện tích P2046, độ cao P2044, ảnh P18, nhãn Việt/Anh/Trung).
  2. Ghép thực thể theo tên trùng + KIỂM TRA CHÉO tọa độ (<= MAX_KM km) → tránh nhầm địa danh trùng tên.
  3. Lấy đoạn mở đầu (tóm tắt) bài Wikipedia tiếng Anh và tiếng Việt theo lô (20 bài/lần).
Kết quả: data/profiles.json  (nội dung Wikipedia theo giấy phép CC BY-SA 4.0 – luôn kèm liên kết nguồn).

Chạy: python3 scripts/build_profiles.py
"""
import json
import math
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "profiles.json")
UA = "BienDongMonitor/1.0 (https://github.com/hdv100899-dotcom/Avt; personal research tool)"
MAX_KM = 60
PAUSE = 1.2
EXTRACT_CHARS = 1800


def api(host, params, tries=5):
    params = dict(params, format="json", formatversion="2", maxlag="5")
    url = f"https://{host}/w/api.php?" + urllib.parse.urlencode(params)
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
            with urllib.request.urlopen(req, timeout=40) as r:
                data = json.loads(r.read().decode("utf-8"))
            if "error" in data and data["error"].get("code") == "maxlag":
                raise RuntimeError("maxlag")
            time.sleep(PAUSE)
            return data
        except Exception as e:  # noqa: BLE001
            wait = 5 * (i + 1)
            print(f"  ! {host}: {e} – thử lại sau {wait}s", file=sys.stderr)
            time.sleep(wait)
    return {}


def load_features():
    js = ("global.window={};require(%r);process.stdout.write(JSON.stringify(window.DEFAULT_FEATURES))"
          % os.path.join(ROOT, "js", "data.js"))
    return json.loads(subprocess.check_output(["node", "-e", js]))


def km(a, b, c, d):
    r = math.pi / 180
    h = math.sin((c - a) * r / 2) ** 2 + math.cos(a * r) * math.cos(c * r) * math.sin((d - b) * r / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def candidates(f):
    names = []
    for part in f.get("nameEn", "").replace(")", "(").split("("):
        part = part.strip()
        if len(part) >= 4 and part not in names:
            names.append(part)
    return names


SPARQL = """
SELECT ?item ?coord ?en ?vi ?zh ?enwiki ?viwiki ?area ?areaUnit ?elev ?image WHERE {
  SERVICE wikibase:box {
    ?item wdt:P625 ?coord .
    bd:serviceParam wikibase:cornerSouthWest "Point(104 1.5)"^^geo:wktLiteral .
    bd:serviceParam wikibase:cornerNorthEast "Point(122 22.5)"^^geo:wktLiteral .
  }
  OPTIONAL { ?item rdfs:label ?en FILTER(lang(?en)="en") }
  OPTIONAL { ?item rdfs:label ?vi FILTER(lang(?vi)="vi") }
  OPTIONAL { ?item rdfs:label ?zh FILTER(lang(?zh)="zh") }
  OPTIONAL { ?enwiki schema:about ?item ; schema:isPartOf <https://en.wikipedia.org/> }
  OPTIONAL { ?viwiki schema:about ?item ; schema:isPartOf <https://vi.wikipedia.org/> }
  OPTIONAL { ?item p:P2046/psv:P2046 [ wikibase:quantityAmount ?area ; wikibase:quantityUnit ?areaUnit ] }
  OPTIONAL { ?item wdt:P2044 ?elev }
  OPTIONAL { ?item wdt:P18 ?image }
  FILTER(BOUND(?enwiki) || BOUND(?viwiki))
}"""
AREA_UNITS = {"Q712226": 1.0, "Q35852": 0.01, "Q25343": 1e-6, "Q81292": 1 / 247.105, "Q232291": 2.58999}


def wikidata_items():
    """MỘT truy vấn SPARQL: mọi mục Wikidata có tọa độ trong khung Biển Đông và có bài Wikipedia EN/VI."""
    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": SPARQL})
    for i in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/sparql-results+json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                rows = json.loads(r.read().decode("utf-8"))["results"]["bindings"]
            break
        except Exception as e:  # noqa: BLE001
            print(f"  ! SPARQL: {e} – chờ 65s", file=sys.stderr)
            time.sleep(65)
    else:
        return {}
    items = {}
    v = lambda row, k: row.get(k, {}).get("value")
    for row in rows:
        qid = v(row, "item").rsplit("/", 1)[-1]
        lon, lat = [float(x) for x in v(row, "coord").replace("Point(", "").rstrip(")").split()]
        it = items.setdefault(qid, {"qid": qid, "coord": [lat, lon], "en": v(row, "en"), "vi": v(row, "vi"), "zh": v(row, "zh"),
                                    "enwiki": None, "viwiki": None, "area_km2": None, "elevation_m": None, "image": None})
        if v(row, "enwiki"):
            it["enwiki"] = urllib.parse.unquote(v(row, "enwiki").rsplit("/wiki/", 1)[-1]).replace("_", " ")
        if v(row, "viwiki"):
            it["viwiki"] = urllib.parse.unquote(v(row, "viwiki").rsplit("/wiki/", 1)[-1]).replace("_", " ")
        if v(row, "area") and it["area_km2"] is None:
            f = AREA_UNITS.get((v(row, "areaUnit") or "").rsplit("/", 1)[-1])
            if f:
                it["area_km2"] = round(float(v(row, "area")) * f, 4)
        if v(row, "elev") and it["elevation_m"] is None:
            try:
                it["elevation_m"] = float(v(row, "elev"))
            except ValueError:
                pass
        if v(row, "image") and not it["image"]:
            it["image"] = urllib.parse.unquote(v(row, "image").rsplit("/", 1)[-1]).replace("_", " ")
    return items


def norm(s):
    import re
    import unicodedata
    s = unicodedata.normalize("NFC", (s or "").lower())
    s = re.sub(r"\(.*?\)", " ", s)
    return re.sub(r"[^\w]+", " ", s).strip()


def best_match(f, items):
    """Ghép thực thể với mục Wikidata: tên trùng (EN/VI/ZH) + khoảng cách <= MAX_KM; ưu tiên gần nhất."""
    names = {norm(n) for n in candidates(f)} | {norm(f["name"]), norm(f.get("nameCn"))}
    for part in f["name"].replace(")", "(").split("("):
        names.add(norm(part))
    names.discard("")
    best = None
    for it in items.values():
        labels = {norm(it["en"]), norm(it["vi"]), norm(it["zh"]), norm(it["enwiki"]), norm(it["viwiki"])}
        if not (names & labels):
            continue
        d = km(f["lat"], f["lng"], *it["coord"])
        if d <= MAX_KM and (best is None or d < best[0]):
            best = (d, it)
    return best[1] if best else None


def extracts(host, titles):
    """Tóm tắt (đoạn mở đầu) theo lô 20 bài/lần."""
    out = {}
    titles = list(titles)
    for i in range(0, len(titles), 20):
        chunk = titles[i:i + 20]
        d = api(host, {"action": "query", "titles": "|".join(chunk), "prop": "extracts|info", "exintro": 1,
                       "explaintext": 1, "exlimit": "max", "inprop": "url", "redirects": 1})
        q = d.get("query", {})
        alias = {n["from"]: n["to"] for n in q.get("normalized", []) + q.get("redirects", [])}
        pages = {p["title"]: p for p in q.get("pages", []) if not p.get("missing")}
        for t in chunk:
            tt = alias.get(alias.get(t, t), alias.get(t, t))
            p = pages.get(tt)
            if not p:
                continue
            text = (p.get("extract") or "").strip()
            if len(text) > EXTRACT_CHARS:
                text = text[:EXTRACT_CHARS].rsplit(". ", 1)[0] + ". …"
            out[t] = {"title": p["title"], "url": p.get("fullurl"), "extract": text}
    return out


def main():
    feats = load_features()
    old = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    items = wikidata_items()
    print(f"Wikidata: {len(items)} mục có tọa độ trong khu vực và có bài Wikipedia")
    if not items:
        sys.exit("Không truy vấn được Wikidata – giữ nguyên data/profiles.json cũ, hãy chạy lại sau.")
    match = {}
    for f in feats:
        it = best_match(f, items)
        if it:
            match[f["id"]] = it
        print(f"  {f['id']} {f['name']:<34} → {(it['enwiki'] or it['viwiki']) if it else '(không tìm thấy)'}")
    en_ex = extracts("en.wikipedia.org", sorted({m["enwiki"] for m in match.values() if m["enwiki"]}))
    vi_ex = extracts("vi.wikipedia.org", sorted({m["viwiki"] for m in match.values() if m["viwiki"]}))

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    profiles = {}
    for f in feats:
        m = match.get(f["id"])
        if not m:
            if f["id"] in old:
                profiles[f["id"]] = old[f["id"]]
            continue
        profiles[f["id"]] = {
            "wikidata": m["qid"],
            "en": en_ex.get(m["enwiki"]) if m["enwiki"] else None,
            "vi": vi_ex.get(m["viwiki"]) if m["viwiki"] else None,
            "zhTitle": m["zh"],
            "coord": [round(m["coord"][0], 5), round(m["coord"][1], 5)],
            "distanceKm": round(km(f["lat"], f["lng"], *m["coord"]), 2),
            "area_km2": m["area_km2"],
            "elevation_m": m["elevation_m"],
            "image": m["image"],
            "fetchedAt": now,
        }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(profiles, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    have_vi = sum(1 for p in profiles.values() if p.get("vi"))
    print(f"Đã ghi {len(profiles)} hồ sơ ({have_vi} có bài tiếng Việt) → {OUT}")


if __name__ == "__main__":
    main()
