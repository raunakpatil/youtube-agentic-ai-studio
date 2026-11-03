/* ═══════════════════════════ library ═══════════════════════════ */
async function loadLibrary() {
  try { library = await api("/api/library"); } catch (e) { return; }
  const t = library.totals;
  $("#lib-stats").innerHTML = [[t.videos, "videos made"], [t.uploaded, "published"], [t.shorts, "shorts"], [t.minutes, "minutes of video"]]
    .map(([v, l]) => `<div class="stat"><b>${v}</b><span>${l}</span></div>`).join("");
  drawBars($("#lib-bars"), library.activity.map(a => a.count), library.activity.map(a => `${a.day}: ${a.count}`));
  const card = (m, shorts) => `
    <article class="card ${shorts ? "s4" : "s6"} lib-card">
      <div class="thumb-frame ${shorts ? "tall" : ""}">${m.files.thumb ? `<img loading="lazy" src="/library/${m.id}/thumbnail.jpg" alt="">` : `<div class="empty">no thumbnail</div>`}
        <span class="badge tag ${m.yt_url ? "green" : ""}">${m.yt_url ? "published" : "not published"}</span></div>
      <h4>${esc(m.title.replace(/\s*#shorts\b/ig, ""))}</h4>
      <div class="lib-meta"><span>${ago(m.created_at)}</span>${m.duration ? `<span>· ${clock(m.duration)}</span>` : ""}</div>
      <div class="lib-actions">
        <button class="btn btn-white btn-sm" onclick="openProject('${m.id}')">Open</button>
        ${m.yt_url ? `<a class="btn btn-ghost btn-sm" href="${esc(m.yt_url)}" target="_blank" rel="noopener">${shorts ? "↗" : "YouTube ↗"}</a>` : `<a class="btn btn-ghost btn-sm" href="/library/${m.id}/video.mp4?download=1">${shorts ? "↓" : "Download"}</a>`}
        <button class="btn btn-red btn-sm" style="margin-left:auto" title="Delete" onclick="deleteProject('${m.id}', this)">${shorts ? "✕" : "Delete"}</button>
      </div>
    </article>`;
  const longs = library.items.filter(m => m.video_type !== "shorts");
  const shorts = library.items.filter(m => m.video_type === "shorts");
  const section = (title, sub, items, isShort) => `
    <div class="lib-head"><h3>${title}</h3><span>${items.length}</span><p>${sub}</p></div>` +
    (items.length ? items.map(m => card(m, isShort)).join("")
      : `<article class="card s24 flat"><div class="empty" style="min-height:90px">None yet. Pick “${isShort ? "Short · 60 s" : "Long video"}” on Home to make one.</div></article>`);
  $("#lib-grid").innerHTML = library.items.length
    ? section("Long videos", "16:9 · 6–8 min · 1280×720 thumbnails", longs, false) +
      section("Shorts", "9:16 · ~60 s · vertical thumbnails", shorts, true)
    : `<article class="card s24 flat"><div class="empty">No videos yet. Every video you make is saved here automatically.<a class="btn btn-white" href="#home">Make your first video</a></div></article>`;
  renderLatest();
  loadChannel();
}
async function openProject(id) {
  const r = await api(`/api/library/${id}/load`, {});
  if (!r.ok) return toast(r.error, "err");
  location.hash === "#review" ? loadReview() : (location.hash = "#review");
}
async function deleteProject(id, btn) {
  if (btn.dataset.confirm !== "1") { btn.dataset.confirm = "1"; btn.textContent = "Click again to delete"; setTimeout(() => { btn.dataset.confirm = ""; btn.textContent = "Delete"; }, 3500); return; }
  const r = await api(`/api/library/${id}`, undefined, "DELETE");
  r.ok ? (toast("Deleted"), loadLibrary()) : toast(r.error, "err");
}
