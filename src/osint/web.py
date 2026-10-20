"""Minimal dashboard: newest items first, plus per-source health."""

from collections.abc import Iterator
from datetime import UTC, datetime

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from osint.db import make_engine, make_session_factory
from osint.models import EventGroup, Evidence, RawItem, Source

PAGE = """<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OSINT Dashboard</title>
<style>
:root { --bg:#fff; --fg:#1a1a1a; --muted:#666; --line:#e3e3e3; --link:#0b57d0; --warn:#b3261e; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#121212; --fg:#e8e8e8; --muted:#9a9a9a; --line:#2c2c2c;
          --link:#8ab4f8; --warn:#f2b8b5; }
}
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.45 system-ui, sans-serif; }
main { max-width:960px; margin:0 auto; padding:16px; }
h1 { font-size:20px; margin:0 0 4px; }
.meta { color:var(--muted); font-size:13px; }
ul { list-style:none; padding:0; margin:12px 0; }
li { padding:10px 0; border-top:1px solid var(--line); }
a { color:var(--link); text-decoration:none; }
a:hover { text-decoration:underline; }
.row { display:flex; gap:8px; flex-wrap:wrap; color:var(--muted); font-size:13px; }
input { width:100%; box-sizing:border-box; padding:8px; margin:8px 0; background:var(--bg);
        color:var(--fg); border:1px solid var(--line); border-radius:6px; font:inherit; }
.bad { color:var(--warn); }
button { background:none; border:1px solid var(--line); color:var(--link); border-radius:10px;
         padding:0 8px; font:inherit; font-size:12px; cursor:pointer; }
.evidence { margin:6px 0 0 16px; }
.evidence li { border:0; padding:2px 0; color:var(--muted); font-size:13px; }
</style>
</head>
<body>
<main>
<h1>OSINT Dashboard</h1>
<div class="meta" id="status">Đang tải…</div>
<input id="q" type="search" placeholder="Lọc theo tiêu đề">
<ul id="items"></ul>
</main>
<script>
const items = document.getElementById("items");
const q = document.getElementById("q");
function el(tag, text, cls) {
  const e = document.createElement(tag);
  if (text) e.textContent = text;
  if (cls) e.className = cls;
  return e;
}
function ago(iso) {
  if (!iso) return "?";
  const s = Math.max(0, (Date.now() - new Date(iso)) / 1000);
  if (s < 90) return Math.round(s) + " giây";
  if (s < 5400) return Math.round(s / 60) + " phút";
  if (s < 129600) return Math.round(s / 3600) + " giờ";
  return Math.round(s / 86400) + " ngày";
}
function link(text, url) {
  const a = el("a", text || url || "(không tiêu đề)");
  if (url) { a.href = url; a.target = "_blank"; a.rel = "noopener noreferrer"; }
  return a;
}
function gap(s) {
  if (s < 90) return "+" + s + " giây";
  if (s < 5400) return "+" + Math.round(s / 60) + " phút";
  return "+" + Math.round(s / 3600) + " giờ";
}
async function toggle(g, li, btn) {
  const open = li.querySelector(".evidence");
  if (open) { open.remove(); return; }
  const res = await fetch("/api/groups/" + g.id);
  const data = await res.json();
  const ul = el("ul", null, "evidence");
  for (const e of data.evidence) {
    const item = el("li");
    const tag = e.is_origin ? "nguồn gốc" : gap(e.behind_origin_s);
    item.append(el("span", e.source + " · " + tag + " · "), link(e.title, e.url));
    ul.append(item);
  }
  li.append(ul);
}
async function load() {
  const res = await fetch("/api/groups?limit=100&q=" + encodeURIComponent(q.value));
  const data = await res.json();
  items.replaceChildren();
  for (const g of data) {
    const li = el("li");
    const row = el("div", null, "row");
    row.append(el("span", g.source), el("span", g.language || "?"),
      el("span", "đăng " + ago(g.published_at) + " trước"),
      el("span", "thu thập " + ago(g.first_seen_at) + " trước"));
    if (g.items > 1) {
      const btn = el("button", g.items + " bản đăng · " + g.sources + " nguồn");
      btn.addEventListener("click", () => toggle(g, li, btn));
      row.append(btn);
    }
    li.append(link(g.title, g.url), row);
    items.append(li);
  }
  document.getElementById("status").textContent =
    data.length + " sự kiện mới nhất · cập nhật " + new Date().toLocaleTimeString();
}
q.addEventListener("input", load);
load();
setInterval(load, 30000);
</script>
</body>
</html>
"""


def create_app() -> FastAPI:
    app = FastAPI(title="OSINT Dashboard")
    factory = make_session_factory(make_engine())

    def get_session() -> Iterator[Session]:
        with factory() as session:
            yield session

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return PAGE

    @app.get("/api/items")
    def items(
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        source_id: int | None = None,
        q: str = "",
        session: Session = Depends(get_session),
    ) -> list[dict]:
        # Newest publication first. A feed that dates an item in the future must not pin it to
        # the top, so the key never exceeds the collection time.
        sort_key = func.least(
            func.coalesce(RawItem.published_at, RawItem.collected_at), RawItem.collected_at
        )
        stmt = (
            select(RawItem, Source.name)
            .join(Source, Source.id == RawItem.source_id)
            .order_by(sort_key.desc(), RawItem.id.desc())
            .limit(limit)
            .offset(offset)
        )
        if source_id is not None:
            stmt = stmt.where(RawItem.source_id == source_id)
        if q:
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            stmt = stmt.where(RawItem.title.ilike(f"%{escaped}%", escape="\\"))
        return [
            {
                "id": item.id,
                "source_id": item.source_id,
                "source": name,
                "title": item.title,
                "url": item.url,
                "language": item.language,
                "published_at": item.published_at,
                "collected_at": item.collected_at,
            }
            for item, name in session.execute(stmt)
        ]

    def sort_key():
        return func.least(
            func.coalesce(RawItem.published_at, RawItem.collected_at), RawItem.collected_at
        )

    @app.get("/api/groups")
    def groups(
        limit: int = Query(50, ge=1, le=500),
        offset: int = Query(0, ge=0),
        q: str = "",
        session: Session = Depends(get_session),
    ) -> list[dict]:
        """Event groups, newest origin first. One row per story, however often it was reposted."""
        totals = (
            select(
                Evidence.event_group_id.label("gid"),
                func.count().label("n_items"),
                func.count(func.distinct(RawItem.source_id)).label("n_sources"),
            )
            .join(RawItem, RawItem.id == Evidence.raw_item_id)
            .group_by(Evidence.event_group_id)
            .subquery()
        )
        stmt = (
            select(EventGroup, RawItem, Source.name, totals.c.n_items, totals.c.n_sources)
            .join(Evidence, (Evidence.event_group_id == EventGroup.id) & Evidence.is_origin)
            .join(RawItem, RawItem.id == Evidence.raw_item_id)
            .join(Source, Source.id == RawItem.source_id)
            .join(totals, totals.c.gid == EventGroup.id)
            .order_by(sort_key().desc(), EventGroup.id.desc())
            .limit(limit)
            .offset(offset)
        )
        if q:
            escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            stmt = stmt.where(EventGroup.title.ilike(f"%{escaped}%", escape="\\"))
        return [
            {
                "id": group.id,
                "title": group.title,
                "url": origin.url,
                "source": source_name,
                "language": origin.language,
                "published_at": origin.published_at,
                "first_seen_at": group.first_seen_at,
                "items": items,
                "sources": sources,
            }
            for group, origin, source_name, items, sources in session.execute(stmt)
        ]

    @app.get("/api/groups/{group_id}")
    def group_evidence(group_id: int, session: Session = Depends(get_session)) -> dict:
        """All evidence in a group, earliest first, with each repost's delay behind the origin."""
        group = session.get(EventGroup, group_id)
        if group is None:
            raise HTTPException(404, "no such group")
        rows = session.execute(
            select(Evidence.is_origin, RawItem, Source.name, sort_key().label("at"))
            .join(RawItem, RawItem.id == Evidence.raw_item_id)
            .join(Source, Source.id == RawItem.source_id)
            .where(Evidence.event_group_id == group_id)
            .order_by(sort_key(), RawItem.id)
        ).all()
        origin_at = rows[0].at if rows else None
        return {
            "id": group.id,
            "title": group.title,
            "evidence": [
                {
                    "item_id": item.id,
                    "is_origin": is_origin,
                    "source": name,
                    "title": item.title,
                    "url": item.url,
                    "published_at": item.published_at,
                    "collected_at": item.collected_at,
                    "behind_origin_s": int((at - origin_at).total_seconds()),
                }
                for is_origin, item, name, at in rows
            ],
        }

    @app.get("/api/sources")
    def sources(session: Session = Depends(get_session)) -> list[dict]:
        counts = dict(
            session.execute(
                select(RawItem.source_id, func.count()).group_by(RawItem.source_id)
            ).all()
        )
        now = datetime.now(UTC)
        return [
            {
                "id": s.id,
                "name": s.name,
                "kind": s.kind,
                "status": s.status,
                "items": counts.get(s.id, 0),
                "poll_interval_s": s.poll_interval_s,
                "consecutive_failures": s.consecutive_failures,
                "last_error": s.config.get("last_error"),
                "last_success_age_s": (
                    int((now - s.last_success_at).total_seconds()) if s.last_success_at else None
                ),
                "last_item_age_s": (
                    int((now - s.last_item_at).total_seconds()) if s.last_item_at else None
                ),
            }
            for s in session.scalars(select(Source).order_by(Source.id))
        ]

    return app
