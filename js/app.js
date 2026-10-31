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
  let features = load();
  let selectedId = null;
  let activeTab = "overview";
  let addMode = false;
  let editingId = null;
  let pendingUploads = [];
  const filter = { q: "", group: "", type: "", ctrl: new Set(Object.keys(C)) };

  function load() {
    try {
      const raw = localStorage.getItem(LS_KEY);
      if (raw) { const arr = JSON.parse(raw); if (Array.isArray(arr)) return arr; }
    } catch (e) { console.warn(e); }
    return clone(window.DEFAULT_FEATURES);
  }
  function save() {
    try { localStorage.setItem(LS_KEY, JSON.stringify(features)); return true; }
    catch (e) { toast("⚠️ Không lưu được (bộ nhớ trình duyệt đầy?). Hãy Xuất JSON để sao lưu."); return false; }
  }
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
  const markerLayer = L.layerGroup().addTo(map);
  const labelLayer = L.layerGroup().addTo(map);
  const areaLayer = L.layerGroup().addTo(map);
  L.control.layers(bases, { "Mục tiêu": markerLayer, "Nhãn tên": labelLayer, "Tên khu vực": areaLayer }, { collapsed: true, position: "topleft" }).addTo(map);
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
  function icon(f) {
    const color = (C[f.controller] || C.NONE).color;
    const sq = !["Đảo", "Cồn san hô"].includes(f.type);
    return L.divIcon({ className: "", iconSize: [16, 16], iconAnchor: [8, 8],
      html: `<div class="mk ${sq ? "sq" : ""} ${f.id === selectedId ? "sel" : ""}" style="background:${color}"></div>` });
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
    const vis = visible();
    markerLayer.clearLayers(); labelLayer.clearLayers();
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
          <span class="t">${esc(f.name)}<small>${esc(f.nameEn)} · ${esc(f.type)}</small></span>`;
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
    if (fly) map.flyTo([f.lat, f.lng], Math.max(map.getZoom(), 14), { duration: 1.2 });
    $("#panel").classList.remove("hidden");
    renderPanel();
  }
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
    $("#btnAdd").textContent = on ? "🎯 Bấm lên bản đồ... (Esc hủy)" : "➕ Thêm mục tiêu";
  }
  function initToolbar() {
    $("#btnAdd").onclick = () => setAddMode(!addMode);
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
      localStorage.removeItem(LS_KEY); features = clone(window.DEFAULT_FEATURES); closePanel(); render(); toast("Đã khôi phục dữ liệu gốc.");
    };
    const tick = () => $("#clock").textContent = new Date().toLocaleString("vi-VN");
    tick(); setInterval(tick, 1000);
  }
  let tt;
  function toast(msg) { const t = $("#toast"); t.textContent = msg; t.classList.add("show"); clearTimeout(tt); tt = setTimeout(() => t.classList.remove("show"), 2600); }

  /* ---------------- Khởi động ---------------- */
  initFilters(); initEditor(); initToolbar(); render();
  const hash = location.hash.slice(1); if (hash && byId(hash)) select(hash, true);
})();
