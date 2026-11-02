# ruff: noqa: E501  (SQL statements and Vietnamese labels read better unwrapped)
"""Export the data behind the dashboard snapshot as JSON files.

    OSINT_DATABASE_URL=... python scripts/export_dashboard_snapshot.py --out /some/dir

Writes groups, evidence, sources, languages, daily, regions, quality and meta. Regions are tagged
here from each report's headline and opening text (osint.regions); a group carries the union over
its reports. ``meta.exported_iso`` is the reference time for the dashboard's "last N hours" filters,
because a snapshot has no live clock to count back from.
"""

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import psycopg

from osint.config import database_url
from osint.regions import DISPLAY_ORDER, region_name, tag, tag_report

LANGUAGE_NAMES = {
    "en": "Tiếng Anh", "vi": "Tiếng Việt", "ru": "Tiếng Nga", "uk": "Tiếng Ukraina", "zh": "Tiếng Trung",
    "ko": "Tiếng Hàn", "ja": "Tiếng Nhật", "ar": "Tiếng Ả Rập", "fa": "Tiếng Ba Tư", "hi": "Tiếng Hindi",
    "tr": "Tiếng Thổ Nhĩ Kỳ", "fr": "Tiếng Pháp", "de": "Tiếng Đức", "es": "Tiếng Tây Ban Nha",
    "it": "Tiếng Ý", "pl": "Tiếng Ba Lan", "pt": "Tiếng Bồ Đào Nha", "ro": "Tiếng Rumani", "th": "Tiếng Thái",
}  # fmt: skip
REASONS = {
    "url": "cùng URL", "content_hash": "cùng nội dung", "simhash": "gần giống văn bản",
    "semantic": "cùng sự kiện (ngữ nghĩa)",
}  # fmt: skip
EFFECTIVE = "least(coalesce(r.published_at, r.collected_at), r.collected_at)"
# Measured on 2026-11-02 (see docs/ARCHITECTURE.md, section 5); not recomputed by this script.
QUALITY = [
    ("AUROC ngoài mẫu", 0.979, "103 tin ngẫu nhiên, 16 ngôn ngữ, gán nhãn trước khi xem điểm"),
    ("AUROC ngoài mẫu, tiếng Anh", 0.962, "47 tin"),
    ("AUROC ngoài mẫu, ngôn ngữ khác", 0.993, "56 tin; bộ lọc chỉ học bằng nhãn tiếng Anh"),
    ("Độ phủ tin quân sự ngoài mẫu", 0.90, "27 trên 30 tin quân sự được giữ lại"),
    ("Độ chính xác ngoài mẫu", 0.87, "tin được giữ lại thật sự là tin quân sự"),
    ("AUROC kiểm tra chéo theo nguồn", 0.988, "605 tin gán nhãn tay, sau khi huấn luyện lại"),
]


def clean(text: str | None, limit: int | None = None) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit].rstrip() + "…" if limit and len(text) > limit else text


def host(url: str | None) -> str | None:
    return (urlsplit(url or "").hostname or "").removeprefix("www.") or None


def dump(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC)
    conn = psycopg.connect(database_url().replace("postgresql+psycopg://", "postgresql://"))

    # Text of every report in each group, for region tagging.
    members: dict[int, list[tuple[str, str, str | None]]] = {}
    for gid, title, content, locator in conn.execute(
        """SELECT e.event_group_id, coalesce(r.title, ''), left(coalesce(r.content, ''), 600), s.locator
           FROM evidence e JOIN raw_item r ON r.id = e.raw_item_id JOIN source s ON s.id = r.source_id"""
    ):
        members.setdefault(gid, []).append((title, content, host(locator)))

    rows = conn.execute(
        f"""SELECT g.id, o.title, o.url, s.name, coalesce(o.language, s.language), {EFFECTIVE}, o.content,
                  t.items, t.outlets, t.rel, s.locator
            FROM event_group g
            JOIN evidence eo ON eo.event_group_id = g.id AND eo.is_origin
            JOIN raw_item o ON o.id = eo.raw_item_id JOIN source s ON s.id = o.source_id
            JOIN raw_item r ON r.id = o.id
            JOIN LATERAL (SELECT count(*) items,
                     count(DISTINCT coalesce(s2.publisher, s2.id::text)) outlets, max(r2.relevance) rel
                  FROM evidence e2 JOIN raw_item r2 ON r2.id = e2.raw_item_id
                  JOIN source s2 ON s2.id = r2.source_id WHERE e2.event_group_id = g.id) t ON true
            ORDER BY 6 DESC, g.id DESC"""
    ).fetchall()
    groups = []
    for gid, title, url, source, lang, eff, content, items, outlets, rel, locator in rows:
        found: set[str] = set()
        for m_title, m_content, _ in members[gid]:
            found.update(tag(m_title, m_content))
        regions = [r for r in DISPLAY_ORDER if r in found] or tag_report(None, None, host(locator))
        groups.append({
            "id": gid, "title": clean(title) or "(không có tiêu đề)", "url": url, "source": source,
            "language": lang, "day": eff.date().isoformat(), "time": eff.strftime("%Y-%m-%d %H:%M"),
            "lede": clean(content, 150), "items": int(items), "outlets": int(outlets),
            "relevance": None if rel is None else round(float(rel), 2), "regions": " ".join(regions),
        })  # fmt: skip
    dump(args.out / "groups.json", groups)

    evidence, first = [], {}
    for eid, (gid, src, title, url, eff, origin, reason, score) in enumerate(
        conn.execute(
            f"""SELECT e.event_group_id, s.name, coalesce(r.title, ''), r.url, {EFFECTIVE}, e.is_origin,
                      e.match_reason, e.match_score
                FROM evidence e JOIN raw_item r ON r.id = e.raw_item_id JOIN source s ON s.id = r.source_id
                WHERE e.event_group_id IN (SELECT event_group_id FROM evidence GROUP BY 1 HAVING count(*) > 1)
                ORDER BY e.event_group_id, {EFFECTIVE}, r.id"""
        ),
        start=1,
    ):
        first.setdefault(gid, eff)
        evidence.append({
            "eid": eid, "group_id": gid, "source": src, "title": clean(title) or "(không có tiêu đề)",
            "url": url, "time": eff.strftime("%Y-%m-%d %H:%M"),
            "behind_min": int((eff - first[gid]).total_seconds() // 60),
            "origin": "gốc" if origin else "đăng lại",
            "reason": "" if origin or not reason else REASONS.get(reason, reason),
            "score": None if score is None else round(float(score), 2),
        })  # fmt: skip
    dump(args.out / "evidence.json", evidence)

    now_str = now
    sources = []
    for (
        sid,
        name,
        kind,
        lang,
        pub,
        status,
        n,
        nrel,
        last,
        interval,
        failures,
        error,
    ) in conn.execute(
        """SELECT s.id, s.name, s.kind, coalesce(s.language, '-'), coalesce(s.publisher, ''), s.status,
                  (SELECT count(*) FROM raw_item r WHERE r.source_id = s.id),
                  (SELECT count(*) FROM raw_item r WHERE r.source_id = s.id AND r.relevance >= 0),
                  s.last_success_at, s.poll_interval_s, s.consecutive_failures,
                  coalesce(s.config->>'last_error', '')
           FROM source s ORDER BY s.id"""
    ):
        sources.append({
            "id": sid, "name": name, "kind": kind, "language": lang, "publisher": pub, "status": status,
            "items": int(n), "relevant_items": int(nrel), "relevant_share": round(nrel / n, 3) if n else None,
            "last_success_hours": None if last is None else round((now_str - last).total_seconds() / 3600, 1),
            "interval_min": round(interval / 60), "failures": int(failures), "error": clean(error, 60),
        })  # fmt: skip
    dump(args.out / "sources.json", sources)

    by_lang: dict[str, dict] = {}
    for s in sources:
        d = by_lang.setdefault(s["language"], {
            "language": s["language"], "name": LANGUAGE_NAMES.get(s["language"], s["language"]),
            "sources": 0, "items": 0, "relevant_items": 0,
        })  # fmt: skip
        d["sources"] += 1
        d["items"] += s["items"]
        d["relevant_items"] += s["relevant_items"]
    dump(args.out / "languages.json", sorted(by_lang.values(), key=lambda d: -d["items"]))

    daily = conn.execute(
        f"""SELECT {EFFECTIVE}::date d, count(*), count(*) FILTER (WHERE r.relevance >= 0)
            FROM raw_item r GROUP BY 1
            HAVING {EFFECTIVE}::date >= (SELECT max({EFFECTIVE})::date - 20 FROM raw_item r) ORDER BY 1"""
    ).fetchall()
    dump(
        args.out / "daily.json",
        [{"day": d.isoformat(), "items": int(i), "relevant_items": int(r)} for d, i, r in daily],
    )

    def is_military(g: dict) -> bool:
        return g["relevance"] is None or g["relevance"] >= 0

    regions = []
    for order, rid in enumerate(DISPLAY_ORDER, start=1):
        tagged = [g for g in groups if rid in g["regions"].split()]
        regions.append({
            "id": rid, "name": region_name(rid), "order": order, "groups": len(tagged),
            "military_groups": sum(is_military(g) for g in tagged),
        })  # fmt: skip
    dump(args.out / "regions.json", regions)
    dump(args.out / "quality.json", [{"metric": m, "value": v, "note": n} for m, v, n in QUALITY])

    total = conn.execute(
        """SELECT (SELECT count(*) FROM raw_item), (SELECT count(*) FROM event_group),
                  (SELECT count(*) FROM source WHERE status = 'active'),
                  (SELECT count(*) FROM (SELECT 1 FROM evidence GROUP BY event_group_id HAVING count(*) > 1) t),
                  (SELECT count(*) FROM raw_item WHERE relevance >= 0)"""
    ).fetchone()
    dump(args.out / "meta.json", [{
        "exported": now.strftime("%Y-%m-%d %H:%M UTC"), "exported_iso": now.strftime("%Y-%m-%dT%H:%M:00Z"),
        "items": total[0], "groups": total[1], "sources": total[2],
        "languages": len([k for k in by_lang if k != "-"]), "multi_report_groups": total[3],
        "relevant_items": total[4], "military_groups": sum(is_military(g) for g in groups),
        "blocked_sources": 27,
    }])  # fmt: skip
    print(
        f"{len(groups)} groups, {len(evidence)} evidence rows, {len(sources)} sources -> {args.out}"
    )


if __name__ == "__main__":
    main()
