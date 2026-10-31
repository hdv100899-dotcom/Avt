/* Hệ thống giám sát Biển Đông – logic giao diện */
(function () {
  "use strict";
  const LS_KEY = "bd_monitor_features_v1";
  const C = window.CONTROLLERS;
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const clone = (o) => JSON.parse(JSON.stringify(o));
  const nowISO = () => new Date().toISOString();
  const fmtTime = (t) => { const d = new Date(t); return isNaN(d) ? esc(t) : d.toLocaleString("vi-VN"); };

  /* ---------------- Dữ liệu ---------------- */
  let features = [];
  let selectedId = null;
  let activeTab = "overview";
  let addMode = false;
  let editingId = null;
  let pendingUploads = [];
  const filter = { q: "", group: "", type: "", ctrl: new Set(Object.keys(C)) };

  const REV_KEY = LS_KEY + "_rev", DEL_KEY = LS_KEY + "_deleted";
  const lsGet = (k, def) => { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : def; } catch (e) { return def; } };
  function load() {
    const arr = lsGet(LS_KEY, null);
    if (!Array.isArray(arr)) return clone(window.DEFAULT_FEATURES);
    // Dữ liệu gốc có bản mới hơn → bổ sung thực thể mới, cập nhật thực thể gốc chưa từng sửa
    if ((lsGet(REV_KEY, 1) || 1) < (window.DEFAULT_DATA_REV || 1)) {
      const deleted = new Set(lsGet(DEL_KEY, []));
      let added = 0;
      window.DEFAULT_FEATURES.forEach((d) => {
        const i = arr.findIndex((x) => x.id === d.id);
        if (i < 0) { if (!deleted.has(d.id)) { arr.push(clone(d)); added++; } }
        else if (!(arr[i].history || []).length) arr[i] = clone(d);
      });
      try { localStorage.setItem(LS_KEY, JSON.stringify(arr)); localStorage.setItem(REV_KEY, JSON.stringify(window.DEFAULT_DATA_REV)); } catch (e) { /* bỏ qua */ }
      if (added) setTimeout(() => toast(`Đã bổ sung ${added} thực thể mới từ dữ liệu gốc.`), 800);
    }
    return arr;
  }
  function save() {
    try { localStorage.setItem(LS_KEY, JSON.stringify(features)); localStorage.setItem(REV_KEY, JSON.stringify(window.DEFAULT_DATA_REV || 1)); return true; }
    catch (e) { toast("⚠️ Không lưu được (bộ nhớ trình duyệt đầy?). Hãy Xuất JSON để sao lưu."); return false; }
  }
  features = load();
  const byId = (id) => features.find((f) => f.id === id);
  const newId = () => "u" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

  /* ---------------- Tọa độ ---------------- */
  function parseCoord(v) {
    v = String(v).trim().toUpperCase().replace(",", ".");
    if (/^-?\d+(\.\d+)?$/.test(v)) return parseFloat(v);
    const m = v.match(/(-?\d+(?:\.\d+)?)\s*[°D\s]\s*(?:(\d+(?:\.\d+)?)\s*['′M]?\s*)?(?:(\d+(?:\.\d+)?)\s*["″S]?\s*)?([NSEWBĐT])?/);
    if (!m) return NaN;
    let x = +m[1] + (+m[2] || 0) / 60 + (+m[3] || 0) / 3600;
    if (m[4] && "SWT".includes(m[4])) x = -x;
    return x;
  }
  function toDMS(x, pos, neg) {
    const h = x >= 0 ? pos : neg; x = Math.abs(x);
    const dd = Math.floor(x), mf = (x - dd) * 60, mm = Math.floor(mf), ss = ((mf - mm) * 60).toFixed(1);
    return `${dd}°${String(mm).padStart(2, "0")}′${String(ss).padStart(4, "0")}″${h}`;
  }
  const dmsLat = (x) => toDMS(x, "N", "S");
  const dmsLng = (x) => toDMS(x, "E", "W");
  function distKm(a, b, c, d) {
    const R = 6371, r = Math.PI / 180;
    const dLat = (c - a) * r, dLng = (d - b) * r;
    const h = Math.sin(dLat / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin(dLng / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }
  const REFS = [
    { n: "Cam Ranh", lat: 11.92, lng: 109.16 },
    { n: "Đà Nẵng", lat: 16.07, lng: 108.22 },
    { n: "Đảo Lý Sơn", lat: 15.38, lng: 109.12 },
    { n: "Đảo Trường Sa", lat: 8.6433, lng: 111.9183 }
  ];

  /* ---------------- Bản đồ ---------------- */
  const esriImg = () => L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { maxZoom: 19, attribution: "Ảnh vệ tinh © Esri, Maxar, Earthstar Geographics" });
  const bases = {
    "🛰️ Ảnh vệ tinh (Esri)": esriImg(),
    "🌊 Hải dương (Esri Ocean)": L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}",
      { maxZoom: 13, attribution: "© Esri, GEBCO, NOAA" }),
    "🗺️ Bản đồ đường (OSM)": L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
      { maxZoom: 19, attribution: "© OpenStreetMap" })
  };
  const map = L.map("map", { zoomControl: true, worldCopyJump: true, layers: [bases["🛰️ Ảnh vệ tinh (Esri)"]] })
    .setView([12.5, 113], 6);
  const zoneLayer = L.layerGroup().addTo(map);
  const markerLayer = L.layerGroup().addTo(map);
  const labelLayer = L.layerGroup().addTo(map);
  const areaLayer = L.layerGroup().addTo(map);
  L.control.layers(bases, { "Mục tiêu": markerLayer, "Phạm vi cụm / bãi": zoneLayer, "Nhãn tên": labelLayer, "Tên khu vực": areaLayer }, { collapsed: true, position: "topleft" }).addTo(map);
  L.control.scale({ metric: true, imperial: false }).addTo(map);

  [["QĐ HOÀNG SA", 16.45, 111.9], ["QĐ TRƯỜNG SA", 10.4, 113.2], ["BIỂN ĐÔNG", 13.5, 114.5]].forEach(([t, la, ln]) =>
    L.marker([la, ln], { interactive: false, icon: L.divIcon({ className: "area-label", html: t, iconSize: null }) }).addTo(areaLayer));

  const legend = L.control({ position: "bottomleft" });
  legend.onAdd = () => {
    const div = L.DomUtil.create("div", "legend");
    div.innerHTML = "<b>Bên kiểm soát</b><br>" + Object.entries(C).map(([k, v]) =>
      `<span class="dot" style="background:${v.color}"></span> ${v.name}`).join("<br>") +
      "<br><span class='muted'>● đảo/cồn &nbsp; ◆ đá/bãi/công trình</span>";
    return div;
  };
  legend.addTo(map);

  map.on("mousemove", (e) => { $("#mouseCoord").textContent = `${e.latlng.lat.toFixed(5)}, ${e.latlng.lng.toFixed(5)}  (${dmsLat(e.latlng.lat)} ${dmsLng(e.latlng.lng)})`; });
  map.on("zoomend", updateLabels);
  map.on("click", (e) => {
    if (!addMode) return;
    setAddMode(false);
    openEditor(null, e.latlng);
  });

  const markers = {};
  const isCluster = (f) => f.type === "Cụm / Nhóm đảo";
  function icon(f) {
    const color = (C[f.controller] || C.NONE).color;
    const sq = !["Đảo", "Cồn san hô", "Cụm / Nhóm đảo"].includes(f.type);
    if (isCluster(f)) return L.divIcon({ className: "", iconSize: [22, 22], iconAnchor: [11, 11],
      html: `<div class="mk ring ${f.id === selectedId ? "sel" : ""} ${isHot(f.id) ? "hot" : ""}" style="border-color:${color}"></div>` });
    return L.divIcon({ className: "", iconSize: [16, 16], iconAnchor: [8, 8],
      html: `<div class="mk ${sq ? "sq" : ""} ${f.id === selectedId ? "sel" : ""} ${isHot(f.id) ? "hot" : ""}" style="background:${color}"></div>` });
  }

  /* ---------------- Lọc & danh sách ---------------- */
  function visible() {
    const q = filter.q.toLowerCase();
    return features.filter((f) =>
      (!filter.group || f.group === filter.group) &&
      (!filter.type || f.type === filter.type) &&
      filter.ctrl.has(f.controller in C ? f.controller : "NONE") &&
      (!q || [f.name, f.nameEn, f.nameCn, f.notes].join(" ").toLowerCase().includes(q)));
  }

  function render() {
    matchNews();
    const vis = visible();
    markerLayer.clearLayers(); labelLayer.clearLayers(); zoneLayer.clearLayers();
    for (const k in markers) delete markers[k];
    vis.forEach((f) => {
      const m = L.marker([f.lat, f.lng], { icon: icon(f), title: f.name, riseOnHover: true })
        .on("click", () => select(f.id))
        .on("dragend", (e) => {
          const ll = e.target.getLatLng();
          applyChange(f.id, { lat: +ll.lat.toFixed(5), lng: +ll.lng.toFixed(5) }, "Dời vị trí bằng kéo thả trên bản đồ");
        });
      m.addTo(markerLayer);
      markers[f.id] = m;
      const r = parseFloat(f.radiusKm);
      if (r > 0) L.circle([f.lat, f.lng], { radius: r * 1000, color: isCluster(f) ? "#ffffff" : (C[f.controller] || C.NONE).color,
        weight: 1.5, dashArray: "6 6", fillOpacity: 0.04, interactive: false }).addTo(zoneLayer);
      L.tooltip({ permanent: true, direction: "right", offset: [8, 0], className: "lbl" })
        .setLatLng([f.lat, f.lng]).setContent(esc(f.name)).addTo(labelLayer);
    });
    updateLabels();
    renderList(vis);
    renderStats(vis);
  }
  function updateLabels() {
    const show = map.getZoom() >= 8;
    if (show && !map.hasLayer(labelLayer)) labelLayer.addTo(map);
    if (!show && map.hasLayer(labelLayer)) map.removeLayer(labelLayer);
  }

  function renderList(vis) {
    const ul = $("#list"); ul.innerHTML = "";
    window.GROUPS.concat([...new Set(vis.map((f) => f.group))].filter((g) => !window.GROUPS.includes(g))).forEach((g) => {
      const items = vis.filter((f) => f.group === g).sort((a, b) => a.name.localeCompare(b.name, "vi"));
      if (!items.length) return;
      const h = document.createElement("li"); h.className = "grp"; h.textContent = `${g} (${items.length})`; ul.appendChild(h);
      items.forEach((f) => {
        const li = document.createElement("li");
        if (f.id === selectedId) li.className = "sel";
        li.innerHTML = `<span class="dot" style="background:${(C[f.controller] || C.NONE).color}"></span>
          <span class="t">${esc(f.name)}<small>${esc(f.nameEn)} · ${esc(f.type)}</small></span>
          ${(newsByFeature[f.id] || []).length ? `<span class="nb" title="Số tin liên quan">📰 ${newsByFeature[f.id].length}</span>` : ""}`;
        li.onclick = () => select(f.id, true);
        ul.appendChild(li);
      });
    });
    if (!vis.length) ul.innerHTML = "<li class='muted'>Không có mục tiêu phù hợp.</li>";
  }
  function renderStats(vis) {
    const cnt = {}; vis.forEach((f) => (cnt[f.controller] = (cnt[f.controller] || 0) + 1));
    $("#stats").innerHTML = `Hiển thị <b>${vis.length}</b>/${features.length} mục tiêu · ` +
      Object.entries(cnt).map(([k, n]) => `<span title="${esc((C[k] || C.NONE).name)}"><span class="dot" style="background:${(C[k] || C.NONE).color}"></span> ${n}</span>`).join(" ");
  }

  function initFilters() {
    window.GROUPS.forEach((g) => $("#fGroup").add(new Option(g, g)));
    window.FEATURE_TYPES.forEach((t) => $("#fType").add(new Option(t, t)));
    $("#fCtrl").innerHTML = Object.entries(C).map(([k, v]) =>
      `<span class="chip" data-k="${k}"><span class="dot" style="background:${v.color}"></span>${v.name.replace(" (chiếm đóng)", "")}</span>`).join("");
    $$("#fCtrl .chip").forEach((el) => el.onclick = () => {
      const k = el.dataset.k;
      filter.ctrl.has(k) ? filter.ctrl.delete(k) : filter.ctrl.add(k);
      el.classList.toggle("off", !filter.ctrl.has(k)); render();
    });
    $("#search").oninput = (e) => { filter.q = e.target.value; render(); };
    $("#fGroup").onchange = (e) => { filter.group = e.target.value; render(); };
    $("#fType").onchange = (e) => { filter.type = e.target.value; render(); };
  }

  /* ---------------- Chọn & bảng thông tin ---------------- */
  let miniMap = null;
  function select(id, fly) {
    const f = byId(id); if (!f) return;
    const prev = selectedId; selectedId = id;
    [prev, id].forEach((k) => { const ff = byId(k); if (ff && markers[k]) markers[k].setIcon(icon(ff)); });
    $$("#list li").forEach((li) => li.classList.remove("sel"));
    renderList(visible());
    if (isNarrow()) $("#sidebar").classList.remove("open");
    if (fly) {
      map.flyTo([f.lat, f.lng], Math.max(map.getZoom(), 14), { duration: 1.2 });
      // Trên iPad dọc, bảng thông tin che nửa dưới: đẩy mục tiêu lên phần bản đồ còn thấy
      // bảng thông tin che một phần bản đồ: đẩy mục tiêu ra phần bản đồ còn thấy
      map.once("moveend", () => isNarrow() ? map.panBy([0, $("#panel").offsetHeight / 2 || 0]) : map.panBy([($("#panel").offsetWidth + 20) / 2 || 0, 0]));
    }
    $("#newsPanel").classList.add("hidden");
    $("#panel").classList.remove("hidden");
    renderPanel();
  }
  const isNarrow = () => window.matchMedia("(max-width: 900px)").matches;
  function closePanel() {
    const prev = selectedId; selectedId = null;
    const ff = byId(prev); if (ff && markers[prev]) { markers[prev].setIcon(icon(ff)); markers[prev].dragging.disable(); }
    $("#panel").classList.add("hidden"); renderList(visible());
  }

  const row = (k, v) => `<tr><td>${k}</td><td>${v ? esc(v) : "<span class='muted'>—</span>"}</td></tr>`;
  function renderPanel() {
    const f = byId(selectedId); if (!f) return closePanel();
    const ctl = C[f.controller] || C.NONE;
    $("#pName").textContent = f.name;
    $("#pSub").innerHTML = `${esc(f.nameEn)}${f.nameCn ? " · " + esc(f.nameCn) : ""}<br>
      <span class="badge"><span class="dot" style="background:${ctl.color}"></span>${esc(ctl.name)}</span>
      <span class="badge">${esc(f.type)}</span> <span class="badge">${esc(f.group)}</span>`;
    $$(".tabs button").forEach((b) => b.classList.toggle("active", b.dataset.tab === activeTab));
    const nCount = (newsByFeature[f.id] || []).length;
    $('.tabs button[data-tab="news"]').textContent = nCount ? `Tin tức (${nCount})` : "Tin tức";
    if (miniMap) { miniMap.remove(); miniMap = null; }
    const n = f.natural || {}, m = f.military || {};
    const body = $("#pBody");
    switch (activeTab) {
      case "overview":
        body.innerHTML = `<table class="kv">
          ${row("Tọa độ", `${dmsLat(f.lat)}  ${dmsLng(f.lng)}`)}
          ${row("Thập phân", `${f.lat.toFixed(5)}, ${f.lng.toFixed(5)}`)}
          ${row("Diện tích", n.area)}${row("Tình trạng quân sự", m.status)}${row("Đồn trú", m.garrison)}
          ${row("Đường băng", m.runway)}${row("Ghi chú", f.notes)}
          ${row("Cập nhật lần cuối", fmtTime(f.updatedAt))}</table>
          <div id="miniMap"></div>
          <div class="muted">Ảnh vệ tinh Esri World Imagery – thời điểm chụp tùy khu vực.</div>`;
        mountMini(f, 15);
        break;
      case "natural":
        body.innerHTML = `<table class="kv">${row("Diện tích", n.area)}${row("Địa hình", n.landform)}${row("Thảm thực vật", n.vegetation)}
          ${row("Nước ngọt", n.freshwater)}${row("Mô tả", n.description)}</table>`;
        break;
      case "military":
        body.innerHTML = `<table class="kv">${row("Tình trạng", m.status)}${row("Lực lượng đồn trú", m.garrison)}${row("Đường băng", m.runway)}
          ${row("Cảng / âu tàu", m.port)}${row("Radar / cảm biến", m.radar)}${row("Công trình", m.facilities)}${row("Ghi chú", m.notes)}</table>
          <div class="warn">⚠️ Thông tin tổng hợp từ nguồn mở, chỉ mang tính tham khảo – cần kiểm chứng và cập nhật thường xuyên.</div>`;
        break;
      case "position": {
        const dists = REFS.filter((r) => distKm(r.lat, r.lng, f.lat, f.lng) > 1).map((r) => {
          const km = distKm(r.lat, r.lng, f.lat, f.lng);
          return row("Cách " + r.n, `${km.toFixed(0)} km ≈ ${(km / 1.852).toFixed(0)} hải lý`);
        }).join("");
        body.innerHTML = `<table class="kv">${row("Vĩ độ", `${dmsLat(f.lat)} (${f.lat.toFixed(5)})`)}${row("Kinh độ", `${dmsLng(f.lng)} (${f.lng.toFixed(5)})`)}
          ${row("Khu vực", f.group)}${dists}</table>
          <div id="miniMap"></div>
          <button id="btnDrag">📍 Bật kéo thả để dời vị trí</button>
          <button id="btnCopy">📋 Sao chép tọa độ</button>`;
        mountMini(f, 13);
        const mk = markers[f.id];
        const setDragLbl = () => $("#btnDrag").textContent = mk && mk.dragging.enabled() ? "✅ Tắt kéo thả" : "📍 Bật kéo thả để dời vị trí";
        setDragLbl();
        $("#btnDrag").onclick = () => {
          if (!mk) return toast("Mục tiêu đang bị ẩn bởi bộ lọc.");
          mk.dragging.enabled() ? mk.dragging.disable() : (mk.dragging.enable(), toast("Kéo biểu tượng mục tiêu trên bản đồ tới vị trí mới."));
          setDragLbl();
        };
        $("#btnCopy").onclick = () => { navigator.clipboard?.writeText(`${f.lat.toFixed(5)}, ${f.lng.toFixed(5)}`); toast("Đã sao chép tọa độ."); };
        break;
      }
      case "images": {
        const ll = `${f.lat},${f.lng}`;
        const imgs = (f.images || []).map((im, i) => `<figure><img src="${esc(im.url)}" data-i="${i}" alt="" loading="lazy" onerror="this.style.opacity=.2">
          <figcaption>${esc(im.caption || "")}${im.date ? " · " + esc(im.date) : ""}${im.source ? " · " + esc(im.source) : ""}</figcaption></figure>`).join("");
        body.innerHTML = `<b>Ảnh vệ tinh trực tiếp (Esri World Imagery)</b>
          <div id="miniMap" style="height:280px"></div>
          <div class="links">Mở ở nguồn khác:
            <a target="_blank" rel="noopener" href="https://www.google.com/maps/@${ll},2000m/data=!3m1!1e3">Google Maps</a>
            <a target="_blank" rel="noopener" href="https://apps.sentinel-hub.com/eo-browser/?zoom=14&lat=${f.lat}&lng=${f.lng}&themeId=DEFAULT-THEME">Sentinel-2 (EO Browser)</a>
            <a target="_blank" rel="noopener" href="https://zoom.earth/maps/satellite/#view=${ll},13z">Zoom Earth</a>
            <a target="_blank" rel="noopener" href="https://worldview.earthdata.nasa.gov/?v=${f.lng - 0.3},${f.lat - 0.2},${f.lng + 0.3},${f.lat + 0.2}">NASA Worldview</a>
            <a target="_blank" rel="noopener" href="https://amti.csis.org/island-tracker/">AMTI Island Tracker</a>
          </div>
          <b>Thư viện ảnh (${(f.images || []).length})</b>
          <div class="gallery">${imgs || "<span class='muted'>Chưa có ảnh. Bấm ✏️ Sửa để thêm URL hoặc tải ảnh lên.</span>"}</div>`;
        mountMini(f, 16);
        $$(".gallery img").forEach((img) => img.onclick = () => lightbox(img.src));
        break;
      }
      case "news": {
        const arts = newsByFeature[f.id] || [];
        const qEn = f.nameEn ? `"${f.nameEn.replace(/\s*\(.*?\)/g, "")}"` : "";
        body.innerHTML = `<div class="links">Tìm tin mới nhất ngay:
            ${qEn ? `<a target="_blank" rel="noopener" href="https://news.google.com/search?q=${encodeURIComponent(qEn)}&hl=en-US&gl=US&ceid=US:en">Google News (EN)</a>` : ""}
          </div>
          <div class="muted">Tin tự động thu thập${news.updatedAt ? " – cập nhật " + relTime(news.updatedAt) : ""}. Bài được gắn khi nhắc tới tên/từ khóa của mục tiêu.</div>
          <ul class="arts">${arts.map((a) => artHTML(a, f.id)).join("") || "<li class='muted'>Chưa có bài báo nào nhắc tới riêng mục tiêu này trong dữ liệu tin hiện có. Có thể thêm “Từ khóa tin tức” trong ✏️ Sửa.</li>"}</ul>
          ${(() => {
            const re = GROUP_RE[f.group]; if (!re) return "";
            const g = news.articles.filter((a) => re.test(a.title + " " + a.summary) && !arts.includes(a)).slice(0, 15);
            return g.length ? `<details><summary><b>Tin chung về quần đảo ${esc(f.group)} (${g.length})</b></summary><ul class="arts">${g.map((a) => artHTML(a)).join("")}</ul></details>` : "";
          })()}`;
        bindArtTags(body);
        break;
      }
      case "history": {
        const h = (f.history || []).slice().reverse();
        body.innerHTML = `<div class="muted">Cập nhật lần cuối: ${fmtTime(f.updatedAt)}</div><br>
          <ul class="hist">${h.map((x) => `<li><time>${fmtTime(x.time)}</time>${esc(x.note)}${x.fields ? `<div class="muted">Trường: ${esc(x.fields.join(", "))}</div>` : ""}</li>`).join("") ||
          "<li class='muted'>Chưa có lịch sử chỉnh sửa (dữ liệu gốc).</li>"}</ul>`;
        break;
      }
    }
  }
  function mountMini(f, z) {
    const el = $("#miniMap"); if (!el) return;
    miniMap = L.map(el, { zoomControl: true, attributionControl: false, layers: [esriImg()] }).setView([f.lat, f.lng], z);
    L.circleMarker([f.lat, f.lng], { radius: 6, color: "#fff", weight: 2, fillColor: (C[f.controller] || C.NONE).color, fillOpacity: 1 }).addTo(miniMap);
    setTimeout(() => miniMap && miniMap.invalidateSize(), 50);
  }
  function lightbox(src) {
    const d = document.createElement("div"); d.id = "lightbox"; d.innerHTML = `<img src="${esc(src)}">`;
    d.onclick = () => d.remove(); document.body.appendChild(d);
  }

  /* ---------------- Chỉnh sửa ---------------- */
  function applyChange(id, patch, note, fields) {
    const f = byId(id); if (!f) return;
    Object.assign(f, patch);
    f.updatedAt = nowISO();
    (f.history = f.history || []).push({ time: f.updatedAt, note, fields: fields || Object.keys(patch) });
    save(); render(); if (selectedId === id) renderPanel();
    toast("Đã lưu: " + f.name);
  }

  const dlg = $("#editDlg"), form = $("#editForm");
  function initEditor() {
    window.GROUPS.forEach((g) => form.group.add(new Option(g, g)));
    window.FEATURE_TYPES.forEach((t) => form.type.add(new Option(t, t)));
    Object.entries(C).forEach(([k, v]) => form.controller.add(new Option(v.name, k)));
    $("#btnCancel").onclick = () => dlg.close();
    $("#btnDelete").onclick = () => {
      const f = byId(editingId); if (!f) return dlg.close();
      if (!confirm(`Xóa mục tiêu "${f.name}"? (Có thể khôi phục bằng nút Khôi phục gốc nếu là dữ liệu gốc)`)) return;
      try { const del = lsGet(DEL_KEY, []); del.push(editingId); localStorage.setItem(DEL_KEY, JSON.stringify(del)); } catch (e) { /* bỏ qua */ }
      features = features.filter((x) => x.id !== editingId); save(); dlg.close(); closePanel(); render(); toast("Đã xóa.");
    };
    $("#imgUpload").onchange = async (e) => {
      for (const file of e.target.files) pendingUploads.push({ url: await shrink(file), caption: file.name, date: new Date().toISOString().slice(0, 10), source: "Tải lên" });
      toast(`Đã chuẩn bị ${pendingUploads.length} ảnh – bấm Lưu để ghi.`);
    };
    form.onsubmit = (e) => { e.preventDefault(); submitEditor(); };
  }
  function openEditor(id, latlng) {
    editingId = id; pendingUploads = []; $("#imgUpload").value = "";
    const f = id ? byId(id) : { name: "", nameEn: "", nameCn: "", group: "Trường Sa", type: "Đá", controller: "NONE",
      lat: +latlng.lat.toFixed(5), lng: +latlng.lng.toFixed(5), natural: {}, military: {}, images: [], notes: "" };
    $("#editTitle").textContent = id ? "Chỉnh sửa: " + f.name : "Thêm mục tiêu mới";
    $("#btnDelete").style.display = id ? "" : "none";
    $$("[name]", form).forEach((el) => {
      const [a, b] = el.name.split(".");
      if (el.name === "images") el.value = (f.images || []).filter((i) => !String(i.url).startsWith("data:"))
        .map((i) => [i.url, i.caption, i.date, i.source].map((x) => x || "").join(" | ")).join("\n");
      else if (el.name === "changeNote") el.value = "";
      else el.value = b ? ((f[a] || {})[b] ?? "") : (f[a] ?? "");
    });
    dlg.showModal();
  }
  function submitEditor() {
    const lat = parseCoord(form.lat.value), lng = parseCoord(form.lng.value);
    if (!isFinite(lat) || !isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) return alert("Tọa độ không hợp lệ.");
    const old = editingId ? byId(editingId) : null;
    const data = { natural: {}, military: {} };
    $$("[name]", form).forEach((el) => {
      const [a, b] = el.name.split(".");
      if (["images", "changeNote", "lat", "lng"].includes(el.name)) return;
      if (b) data[a][b] = el.value.trim(); else data[a] = el.value.trim();
    });
    data.lat = +lat.toFixed(5); data.lng = +lng.toFixed(5);
    const urlImgs = form.images.value.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
      const [url, caption, date, source] = l.split("|").map((s) => (s || "").trim()); return { url, caption, date, source };
    });
    const dataImgs = old ? (old.images || []).filter((i) => String(i.url).startsWith("data:")) : [];
    data.images = urlImgs.concat(dataImgs, pendingUploads);
    const note = form.changeNote.value.trim();
    if (old) {
      const norm = (v) => {
        if (v && typeof v === "object" && !Array.isArray(v)) {
          const o = {}; Object.keys(v).sort().forEach((k) => { if (v[k] !== "" && v[k] != null) o[k] = v[k]; }); return JSON.stringify(o);
        }
        return JSON.stringify(v ?? "");
      };
      const changed = Object.keys(data).filter((k) => norm(data[k]) !== norm(old[k] ?? (Array.isArray(data[k]) ? [] : typeof data[k] === "object" ? {} : "")));
      if (!changed.length && !note) { dlg.close(); return; }
      dlg.close();
      applyChange(old.id, data, note || "Chỉnh sửa thông tin", changed);
    } else {
      const f = Object.assign({ id: newId(), updatedAt: nowISO(), history: [{ time: nowISO(), note: note || "Tạo mới mục tiêu" }] }, data);
      features.push(f); save(); dlg.close(); render(); select(f.id); toast("Đã thêm: " + f.name);
    }
  }
  function shrink(file, max = 1280) {
    return new Promise((res) => {
      const img = new Image(), r = new FileReader();
      r.onload = () => { img.src = r.result; };
      img.onload = () => {
        const s = Math.min(1, max / Math.max(img.width, img.height));
        const c = document.createElement("canvas"); c.width = img.width * s; c.height = img.height * s;
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height); res(c.toDataURL("image/jpeg", 0.8));
      };
      r.readAsDataURL(file);
    });
  }

  /* ---------------- Thanh công cụ ---------------- */
  function setAddMode(on) {
    addMode = on;
    $("#map").classList.toggle("picking", on);
    $("#btnAdd").classList.toggle("active-mode", on);
    $("#btnAdd").innerHTML = on ? "🎯<span class='txt'> Chạm lên bản đồ để đặt vị trí</span>" : "➕<span class='txt'> Thêm mục tiêu</span>";
    if (on) toast("Chạm vào vị trí trên bản đồ để đặt mục tiêu mới (chạm lại ➕ để hủy).");
  }
  function initToolbar() {
    $("#btnAdd").onclick = () => { setAddMode(!addMode); if (addMode && isNarrow()) $("#sidebar").classList.remove("open"); };
    $("#btnMenu").onclick = () => $("#sidebar").classList.toggle("open");
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") { setAddMode(false); } });
    $("#btnClose").onclick = closePanel;
    $("#btnEdit").onclick = () => selectedId && openEditor(selectedId);
    $$(".tabs button").forEach((b) => b.onclick = () => { activeTab = b.dataset.tab; renderPanel(); });
    $("#btnExport").onclick = () => {
      const blob = new Blob([JSON.stringify({ app: "bien-dong-monitor", exportedAt: nowISO(), features }, null, 2)], { type: "application/json" });
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob);
      a.download = `bien-dong-${new Date().toISOString().slice(0, 10)}.json`; a.click(); URL.revokeObjectURL(a.href);
    };
    $("#fileImport").onchange = async (e) => {
      const file = e.target.files[0]; if (!file) return;
      try {
        const j = JSON.parse(await file.text());
        const arr = Array.isArray(j) ? j : j.features;
        if (!Array.isArray(arr) || !arr.every((f) => f.id && f.name && isFinite(f.lat) && isFinite(f.lng))) throw new Error("Sai định dạng");
        const merge = confirm(`File có ${arr.length} mục tiêu.\nOK = GỘP (cập nhật theo id, thêm mới)\nCancel = THAY THẾ toàn bộ`);
        if (merge) arr.forEach((f) => { const i = features.findIndex((x) => x.id === f.id); i >= 0 ? (features[i] = f) : features.push(f); });
        else features = arr;
        save(); closePanel(); render(); toast("Đã nhập dữ liệu.");
      } catch (err) { alert("Không đọc được file: " + err.message); }
      e.target.value = "";
    };
    $("#btnReset").onclick = () => {
      if (!confirm("Xóa toàn bộ chỉnh sửa và khôi phục dữ liệu gốc? (Nên Xuất JSON sao lưu trước)")) return;
      [LS_KEY, REV_KEY, DEL_KEY].forEach((k) => localStorage.removeItem(k)); features = clone(window.DEFAULT_FEATURES); closePanel(); render(); toast("Đã khôi phục dữ liệu gốc.");
    };
    const tick = () => $("#clock").textContent = new Date().toLocaleString("vi-VN");
    tick(); setInterval(tick, 1000);
  }
  let tt;
  function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(tt); tt = setTimeout(() => t.classList.remove("show"), 2600); }

  /* ---------------- Tin tức ---------------- */
  let news = { updatedAt: null, articles: [] };
  let newsByFeature = {};
  let newsLoaded = false;
  const HOT_HOURS = 72;
  const PREFIX_RE = /^(Đảo|Đá|Bãi cạn|Bãi|Cồn san hô|Cồn|Nhà giàn)\s+/i;
  const AMBIGUOUS = new Set(["rizal", "parola", "spratly island", "tree island", "money island", "flat island", "đảo cây", "trường sa", "hoàng sa",
    "north island", "south island", "middle island", "west sand", "paracels", "pag-asa", "taiping", "panata"]);
  const GROUP_RE = { "Trường Sa": /Trường Sa|Spratly|南沙/i, "Hoàng Sa": /Hoàng Sa|Paracel|西沙/i };
  const nfc = (s) => String(s || "").normalize("NFC");
  const escRe = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const shortName = (n) => { const s = n.replace(/\s*\(.*?\)/g, "").trim(); const t = s.replace(PREFIX_RE, ""); return t.split(/\s+/).length >= 2 ? t : s; };
  const hoursAgo = (t) => (Date.now() - new Date(t).getTime()) / 3600e3;
  function relTime(t) {
    const h = hoursAgo(t);
    if (!isFinite(h)) return "";
    if (h < 1) return Math.max(1, Math.round(h * 60)) + " phút trước";
    if (h < 24) return Math.round(h) + " giờ trước";
    if (h < 24 * 30) return Math.round(h / 24) + " ngày trước";
    return new Date(t).toLocaleDateString("vi-VN");
  }
  // Tạo bộ so khớp tên cho từng mục tiêu (tên Việt/Anh/Trung + từ khóa bổ sung)
  function matchersOf(f) {
    const res = [];
    const add = (t, strict) => {
      t = nfc(t).trim();
      if (!t || AMBIGUOUS.has(t.toLowerCase())) return;
      if (/[\u4e00-\u9fff]/.test(t)) { res.push({ cjk: t }); return; }
      if (t.length < 4) return;
      res.push({ re: new RegExp(`(^|[^\\p{L}\\p{N}])${escRe(t)}(?![\\p{L}\\p{N}])`, strict ? "u" : "iu") });
    };
    [f.name, f.nameEn, f.nameCn].forEach((v) => String(v || "").split(/[()\/–]/).forEach((part) => {
      part = part.trim(); if (!part) return;
      const short = part.replace(PREFIX_RE, "");
      add(part, short !== part && short.split(/\s+/).length === 1);
      if (short !== part && short.split(/\s+/).length >= 2) add(short, false);
    }));
    String(f.keywords || "").split(",").forEach((k) => add(k, false));
    return res;
  }
  function matchNews() {
    newsByFeature = {};
    if (!news.articles.length) return;
    const ms = features.map((f) => [f.id, matchersOf(f)]);
    news.articles.forEach((a) => {
      // "quần đảo Hoàng Sa" là cả quần đảo, không phải "đảo Hoàng Sa" → nối liền để không khớp nhầm
      const text = nfc(a.title + " " + (a.summary || "")).replace(/quần đảo/giu, "quầnđảo");
      a._f = [];
      ms.forEach(([id, list]) => {
        if (list.some((m) => (m.cjk ? text.includes(m.cjk) : m.re.test(text)))) { a._f.push(id); (newsByFeature[id] = newsByFeature[id] || []).push(a); }
      });
    });
  }
  const isHot = (id) => (newsByFeature[id] || []).some((a) => hoursAgo(a.published) <= HOT_HOURS);
  function artHTML(a, exceptId) {
    const tags = (a._f || []).filter((id) => id !== exceptId).map((id) => byId(id)).filter(Boolean);
    const isNew = hoursAgo(a.published) <= 24;
    return `<li><a class="ttl" target="_blank" rel="noopener" href="${esc(a.link)}">${esc(a.title)}</a>
      <div class="meta">${isNew ? "<span class='new'>MỚI · </span>" : ""}${esc(a.source)} · ${relTime(a.published)} · EN</div>
      ${a.summary ? `<div class="sum">${esc(a.summary)}</div>` : ""}
      ${tags.length ? `<div class="tags">${tags.map((f) => `<span class="chip" data-fid="${esc(f.id)}"><span class="dot" style="background:${(C[f.controller] || C.NONE).color}"></span>${esc(f.name)}</span>`).join("")}</div>` : ""}</li>`;
  }
  function bindArtTags(root) {
    $$(".tags .chip", root).forEach((el) => el.onclick = () => { activeTab = "news"; select(el.dataset.fid, true); });
  }
  function renderNews() {
    const q = nfc($("#newsSearch").value).toLowerCase(), hrs = +$("#newsTime").value, lang = "en", linked = $("#newsLinked").checked;
    const list = news.articles.filter((a) => (!hrs || hoursAgo(a.published) <= hrs) && (!lang || a.lang === lang) &&
      (!linked || (a._f || []).length) && (!q || nfc(a.title + " " + a.summary + " " + a.source).toLowerCase().includes(q)));
    $("#newsUpdated").textContent = newsLoaded ? (news.updatedAt ? `Thu thập tự động · cập nhật ${relTime(news.updatedAt)} (${fmtTime(news.updatedAt)})` : "Chưa có dữ liệu tin.")
      : "Không tải được data/news.json – hãy mở trang qua GitHub Pages hoặc máy chủ web.";
    $("#newsStats").textContent = `${list.length} bài · ${list.filter((a) => (a._f || []).length).length} bài gắn với mục tiêu cụ thể`;
    $("#newsList").innerHTML = list.slice(0, 300).map((a) => artHTML(a)).join("") || "<li class='muted'>Không có tin phù hợp bộ lọc.</li>";
    bindArtTags($("#newsList"));
    const n24 = news.articles.filter((a) => hoursAgo(a.published) <= 24).length;
    $("#newsBadge").textContent = n24; $("#newsBadge").classList.toggle("hidden", !n24);
    $("#newsBadge").title = `${n24} tin trong 24 giờ qua`;
  }
  async function loadNews(manual) {
    try {
      const r = await fetch("data/news.json?t=" + Date.now(), { cache: "no-store" });
      if (!r.ok) throw new Error(r.status);
      const j = await r.json();
      news = { updatedAt: j.updatedAt, articles: (j.articles || []).filter((a) => a.lang === "en").sort((a, b) => (a.published < b.published ? 1 : -1)) };
      newsLoaded = true;
      if (manual) toast(`Đã tải ${news.articles.length} bài báo.`);
    } catch (e) { newsLoaded = false; if (manual) toast("Không tải được tin tức."); }
    render(); renderNews();
    if (selectedId && activeTab === "news") renderPanel();
  }
  function initNews() {
    $("#btnNews").onclick = () => {
      const p = $("#newsPanel");
      if (!p.classList.contains("hidden")) return p.classList.add("hidden");
      closePanel(); p.classList.remove("hidden"); renderNews();
      if (isNarrow()) $("#sidebar").classList.remove("open");
    };
    $("#btnNewsClose").onclick = () => $("#newsPanel").classList.add("hidden");
    $("#btnNewsRefresh").onclick = () => loadNews(true);
    ["#newsSearch", "#newsTime", "#newsLinked"].forEach((s) => $(s).addEventListener("input", renderNews));
    loadNews();
    setInterval(loadNews, 15 * 60 * 1000); // tự tải lại mỗi 15 phút
  }

  /* ---------------- Khởi động ---------------- */
  initFilters(); initEditor(); initToolbar(); render(); initNews();
  const hash = location.hash.slice(1); if (hash && byId(hash)) select(hash, true);
})();
