/* ═══════════════════════════ making a video ═══════════════════════════ */
const STEPS = [
  ["research",  "Researching the topic",   "Picking the angle and checking facts"],
  ["script",    "Writing the script",      "Hook, story and a strong ending"],
  ["images",    "Finding visuals",         "Photos and artwork for every scene"],
  ["narration", "Recording the voiceover", "Natural AI voice with synced captions"],
  ["video",     "Rendering the video",     "The slow part, usually 2–10 minutes"],
];
let status = {}, es = null, heroMode = "form", runSteps = [], videoType = "normal", lastRunError = "", lastRequest = null;

function setHero(mode) {
  heroMode = mode;
  $("#hero-form").hidden = mode !== "form";
  $("#hero-run").hidden = mode === "form";
  $("#run-progress").hidden = mode !== "running";
  $("#run-done").hidden = mode !== "done";
  $("#run-error").hidden = mode !== "error";
  $("#stop-btn").hidden = mode !== "running";
}

function renderRun(d) {
  const stages = d.stages || {};
  let doneCount = 0, current = null, total = 0;
  $("#steps-list").innerHTML = STEPS.map(([k, title, sub]) => {
    let s = stages[k] || "pending";
    if (runSteps.length && !runSteps.includes(k)) s = "skipped"; else total++;
    if (s === "done") doneCount++;
    if (s === "running") current = title;
    const ic = { done: "✓", error: "!", skipped: "–" }[s] || "";
    const label = { done: "done", running: "working…", error: "failed", skipped: "reused" }[s] || "";
    return `<div class="step" data-s="${s}"><span class="ic">${ic}</span><div><b>${title}</b><small>${sub}</small></div><em>${label}</em></div>`;
  }).join("");
  total = total || 5;
  $("#prog-fill").style.width = Math.min(100, (doneCount + (current ? .5 : 0)) / total * 100) + "%";
  $("#prog-step").textContent = current ? `Step ${Math.min(total, doneCount + 1)} of ${total}: ${current.toLowerCase()}` : d.running ? "Getting ready…" : "";
  $("#prog-time").textContent = d.started_at ? clock(Date.now() / 1000 - d.started_at) + " so far" : "";
}

function applyStatus(d) {
  const was = status.running;
  status = d;
  const state = d.running ? "running" : d.error ? "error" : d.has_video ? "done" : "idle";
  $("#status-pill").className = "status-pill " + state;
  $("#status-text").textContent = d.uploading ? "Uploading…" : d.running ? "Making video…" : d.error ? "Last run failed" : "Ready";
  if (d.running) {
    if (heroMode !== "running") {
      setHero("running");
      // page opened mid-run: show the topic once research has picked it
      if ((d.stages || {}).research === "done") showTopic();
    }
    renderRun(d);
    if (!es) startSSE();
  }
  if (was && !d.running) onFinished(d);
}
async function pollStatus() {
  try { applyStatus(await api("/api/status")); } catch (e) { }
  setTimeout(pollStatus, status.running || status.uploading ? 1500 : 5000);
}
const pollOnce = () => api("/api/status").then(applyStatus).catch(() => {});

async function onFinished(d) {
  renderRun(d);
  loadLibrary();
  const msg = d.error || lastRunError;
  if (msg) {
    const failed = STEPS.find(([k]) => (d.stages || {})[k] === "error");
    const quota = /429|quota|RESOURCE_EXHAUSTED|All .*failed/i.test(msg);
    $("#run-title").textContent = "That didn't work";
    $("#run-topic").textContent = "";
    $("#run-error").innerHTML = `<div class="err-box"><b>Stopped at: ${failed ? failed[1].toLowerCase() : "a step"}</b>${esc(msg.slice(0, 400))}
      <div style="margin-top:8px;color:#d9a8ae">${quota ? "The free AI ran out of quota. Wait a minute and try again, or add a free key in Settings for more quota."
        : "Try again. If it keeps happening, the technical log below has the details."}</div></div>
      <div style="display:flex;gap:8px;margin-top:14px;flex-wrap:wrap"><button class="btn btn-white" onclick="retry()">Try again</button><button class="btn btn-ghost" onclick="setHero('form')">Change topic</button><a class="btn btn-ghost" href="#settings">Settings</a></div>`;
    setHero("error");
    $("#log-details").open = true;
    return;
  }
  if (!d.has_video || (lastRequest && !lastRequest[2].includes("video"))) {
    setHero("form");
    if (d.stop_requested) toast("Stopped");
    return;
  }
  const out = await api("/api/output").catch(() => ({}));
  $("#run-title").textContent = "Your video is ready";
  $("#run-topic").textContent = "";
  $("#run-done").innerHTML = `<div class="done-box">
      <div class="thumb-frame">${d.has_thumb ? `<img src="/thumbnail/${Date.now()}" alt="">` : ""}</div>
      <div><div style="font-size:20px;line-height:1.25">${esc(out.title || "")}</div>
        <p class="hint" style="margin:8px 0 16px">${out.sources && out.sources.length ? `Fact-checked against ${out.sources.length} sources. ` : ""}Next: watch it, polish the title and thumbnail, then publish.</p>
        <div style="display:flex;gap:8px;flex-wrap:wrap"><a class="btn btn-white btn-lg" href="#review">Review &amp; publish →</a><button class="btn btn-ghost btn-lg" onclick="setHero('form')">Make another</button></div></div>
    </div>`;
  setHero("done");
  $("#tabs a[data-view=review]").classList.add("notify");
  toast("Your video is ready", "ok");
}

function startSSE() {
  if (es) es.close();
  es = new EventSource("/api/stream");
  es.onmessage = ev => {
    const d = JSON.parse(ev.data);
    if (d.kind === "log") log(d.msg);
    else if (d.kind === "stage") pollOnce();
    else if (d.kind === "research") showTopic();
    else if (["done", "error", "stopped"].includes(d.kind)) {
      if (d.kind === "error") lastRunError = d.msg;
      es.close(); es = null; pollOnce();
    }
  };
  es.onerror = () => { es && es.close(); es = null; };
}
async function showTopic() {
  const r = await api("/api/research").catch(() => null);
  if (r && r.title) $("#run-topic").innerHTML = `“${esc(r.title)}”${r.sources.length ? ` <span class="tag green" style="margin-left:6px">${r.sources.length} sources found</span>` : ""}`;
}
function log(msg) {
  const c = $("#console");
  if (c.firstElementChild && c.firstElementChild.classList.contains("l-dim")) c.innerHTML = "";
  let cls = "";
  if (/\[ERROR\]|ERROR|Traceback|❌/.test(msg)) cls = "l-err";
  else if (/⚠|\[WARN\]/.test(msg)) cls = "l-warn";
  else if (/✅|complete|saved|Uploaded|Saved to Library/i.test(msg)) cls = "l-ok";
  const line = document.createElement("div");
  line.innerHTML = `<span class="t">${new Date().toTimeString().slice(0, 8)}</span><span class="${cls}">${esc(msg)}</span>`;
  c.appendChild(line);
  while (c.children.length > 600) c.firstChild.remove();
  c.scrollTop = c.scrollHeight;
}

async function startRun(topic, surprise) {
  const steps = $$("#steps input:checked").map(i => i.value);
  if (!steps.length) return toast("Turn on at least one step under More options", "err");
  if (!surprise && !topic) { $("#topic-input").focus(); return toast("Type a topic first, or let AI pick one"); }
  lastRequest = [topic, surprise, steps];
  runSteps = steps.length === 6 ? [] : steps;
  lastRunError = "";
  $("#console").innerHTML = "";
  $("#log-details").open = false;
  $("#run-title").textContent = "Making your video…";
  $("#run-topic").textContent = surprise ? "AI is choosing a topic…" : `“${topic}”`;
  setHero("running");
  renderRun({ stages: {}, running: true });
  const r = await api("/api/run", {
    steps, topic: surprise ? "" : topic, video_type: videoType,
    focus_angle: surprise ? $("#focus-angle").value : "",
    use_trends: surprise && $("#quick-trends").checked,
  }).catch(e => ({ ok: false, error: e.message }));
  if (!r.ok) { setHero("form"); return toast(r.error, "err"); }
  status.running = true;
  startSSE(); pollOnce();
  window.scrollTo({ top: 0, behavior: "smooth" });
}
function retry() { lastRequest ? startRun(lastRequest[0], lastRequest[1]) : setHero("form"); }
$("#ask-form").onsubmit = e => { e.preventDefault(); startRun($("#topic-input").value.trim(), false); };
$("#surprise-btn").onclick = () => startRun("", true);
$("#stop-btn").onclick = () => api("/api/stop", {}).then(() => { toast("Stopping after the current step…"); $("#run-title").textContent = "Stopping…"; });
$$("#format-seg button").forEach(b => b.onclick = () => {
  videoType = b.dataset.fmt;
  $$("#format-seg button").forEach(x => x.classList.toggle("on", x === b));
});
$$("#steps .chip, #img-sources .chip").forEach(c => {
  const input = $("input", c);
  c.classList.toggle("on", input.checked);
  input.addEventListener("change", () => c.classList.toggle("on", input.checked));
});
$("#quick-voice").onchange = e => api("/api/save-settings", { voice_id: e.target.value }).then(() => toast("Voice saved"));
$("#quick-grounding").onchange = e => api("/api/save-settings", { fact_grounding: e.target.checked });
