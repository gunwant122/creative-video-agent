// Creative Video Agent UI: no build step, plain DOM.
const $ = (s) => document.querySelector(s);
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null) n.setAttribute(k, v);
  }
  for (const c of kids.flat()) if (c != null) n.append(c.nodeType ? c : document.createTextNode(String(c)));
  return n;
};

let project = null;
let busy = false;
let activityBox = null;

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  if (!r.ok) throw new Error((await r.text()) || r.statusText);
  return r.json();
}

// ---------- projects ----------
async function loadProjects(select) {
  const list = await api("/api/projects");
  const sel = $("#project");
  sel.replaceChildren(el("option", { value: "" }, list.length ? "Choose a project" : "No projects yet"),
    ...list.map((p) => el("option", { value: p.name }, `${p.name} (${p.clips} clips, ${p.renders} renders)`)));
  const want = select || localStorageGet("cva.project");
  if (want && list.some((p) => p.name === want)) { sel.value = want; await openProject(want); }
  else { $("#main").hidden = true; $("#empty").hidden = false; }
}
function localStorageGet(k) { try { return localStorage.getItem(k); } catch { return null; } }
function localStorageSet(k, v) { try { localStorage.setItem(k, v); } catch {} }

async function openProject(name) {
  project = name;
  localStorageSet("cva.project", name);
  $("#main").hidden = false; $("#empty").hidden = true;
  $("#log").replaceChildren();
  pendingCost.clear();
  try {
    const h = await api(`/api/projects/${name}/history`);
    for (const m of h.messages) addMsg(m.role, m.text);
    renderTodos(h.todos);
    for (const i of h.interrupts) addInterrupt(i);
  } catch (e) { addMsg("error", String(e)); }
  const b = await api(`/api/projects/${name}/brief`);
  $("#brief").value = b.text;
  await refresh();
}

$("#project").addEventListener("change", (e) => e.target.value && openProject(e.target.value));
$("#newProject").addEventListener("click", async () => {
  const name = prompt("Project name (letters, numbers, - and _):");
  if (!name) return;
  try { await api("/api/projects", { method: "POST", body: JSON.stringify({ name }) }); await loadProjects(name); showTab("sources"); }
  catch (e) { alert(e.message); }
});

// ---------- chat ----------
function addMsg(role, text) {
  const n = el("div", { class: `msg ${role}` }, text);
  $("#log").append(n);
  n.scrollIntoView({ block: "end" });
  if (role !== "activity") activityBox = null;
  return n;
}

function activity(ev) {
  if (!activityBox) {
    activityBox = el("details", { class: "act" }, el("summary", {}, "Working…"));
    $("#log").append(activityBox);
  }
  const who = el("span", { class: "who" }, ev.agent);
  let line;
  if (ev.type === "tool_call") line = el("div", {}, who, ` → ${ev.name} ${ev.args}`);
  else if (ev.type === "tool_result") line = el("div", {}, who, ` ← ${ev.name}: ${ev.text.slice(0, 300)}`);
  else line = el("div", {}, who, `: ${ev.text}`);
  activityBox.append(line);
  activityBox.querySelector("summary").textContent = `${ev.agent}: ${ev.type === "tool_call" ? ev.name : "working"}…`;
  activityBox.scrollIntoView({ block: "end" });
}

async function stream(path, body) {
  setBusy(true);
  try {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, i); buf = buf.slice(i + 2);
        if (chunk.startsWith("data: ")) handle(JSON.parse(chunk.slice(6)));
      }
    }
  } catch (e) { addMsg("error", String(e)); }
  finally { setBusy(false); if (activityBox) activityBox.querySelector("summary").textContent = "Activity"; refresh(); }
}

function handle(ev) {
  switch (ev.type) {
    case "message": addMsg("assistant", ev.text); break;
    case "activity": case "tool_call": case "tool_result": activity(ev);
      if (ev.type === "tool_result" && /render|deliver/.test(ev.text)) refresh(); break;
    case "todos": renderTodos(ev.todos); break;
    case "interrupt": addInterrupt(ev.value, ev.id); break;
    case "waiting": $("#status").textContent = `Answer ${ev.remaining} more card(s) to continue`; break;
    case "error": addMsg("error", ev.text); break;
    case "done": $("#status").textContent = ev.waiting ? "Waiting for you" : "Idle"; break;
  }
}

function setBusy(b) {
  busy = b;
  $("#send").disabled = b;
  $("#status").textContent = b ? "Agent working…" : $("#status").textContent;
}

$("#composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("#input").value.trim();
  if (!text || busy || !project) return;
  $("#input").value = "";
  addMsg("user", text);
  stream(`/api/projects/${project}/chat`, { message: text });
});
$("#input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) $("#composer").requestSubmit();
});

// ---------- interrupts: questions + cost approvals ----------
function addInterrupt(v, id) {
  id = id ?? v.id;
  if (v.type === "questions") return questionCard(v.questions, id);
  if (v.type === "cost_approval") return costCard(v, id);
  addMsg("assistant", JSON.stringify(v));
}
const pendingCost = new Map();   // interrupt id -> card element
function answer(id, value) {
  pendingCost.delete(id); refreshBulk();
  return stream(`/api/projects/${project}/resume`, { value, interrupt_id: id });
}
function refreshBulk() {
  let bar = document.querySelector("#bulk");
  if (pendingCost.size < 2) { bar?.remove(); return; }
  if (!bar) {
    bar = el("div", { id: "bulk", class: "card" });
    $("#log").append(bar);
  }
  bar.replaceChildren(el("h4", {}, `${pendingCost.size} paid requests are waiting`),
    el("div", { class: "opts" },
      el("button", { onclick: () => decideAll(true) }, `Approve all ${pendingCost.size}`),
      el("button", { class: "ghost", onclick: () => decideAll(false) }, "Decline all")));
  bar.scrollIntoView({ block: "end" });
}
async function decideAll(approved) {
  const ids = [...pendingCost.keys()];
  for (const id of ids) {
    pendingCost.get(id)?.querySelectorAll("button").forEach((x) => (x.disabled = true));
    await answer(id, { approved });     // the agent resumes after the last answer
  }
}

function questionCard(questions, id) {
  const answers = {};
  const card = el("div", { class: "card" }, el("h4", {}, "The agent has a few questions"));
  for (const q of questions) {
    answers[q.id] = q.default ?? "";
    const opts = el("div", { class: "opts" });
    const other = el("input", { placeholder: "or type an answer", oninput: (e) => { answers[q.id] = e.target.value; } });
    for (const o of q.options || []) {
      const b = el("button", { type: "button", class: "ghost" + (o === q.default ? " sel" : ""),
        onclick: () => { answers[q.id] = o; opts.querySelectorAll("button").forEach((x) => x.classList.remove("sel")); b.classList.add("sel"); } }, o);
      opts.append(b);
    }
    card.append(el("div", {}, el("div", {}, q.question), opts, other));
  }
  const send = el("button", { onclick: () => { card.querySelectorAll("button,input").forEach((x) => (x.disabled = true));
    answer(id, answers); } }, "Answer");
  card.append(send);
  $("#log").append(card); card.scrollIntoView({ block: "end" });
}

function costCard(v, id) {
  const est = v.estimate || {};
  const cost = est.usd != null ? `about $${est.usd}` : (est.note || "cost unknown");
  const budget = v.budget && v.budget.limit_usd != null ? ` · budget $${v.budget.spent_usd} of $${v.budget.limit_usd} used` : "";
  const card = el("div", { class: "card" },
    el("h4", {}, `Approve paid generation: ${v.service} · ${v.operation}`),
    el("div", {}, `Cost: ${cost}${budget}`),
    el("pre", {}, JSON.stringify(v.details, null, 1)));
  const decide = (approved) => { card.querySelectorAll("button").forEach((x) => (x.disabled = true));
    answer(id, { approved }); };
  card.append(el("div", { class: "opts" }, el("button", { onclick: () => decide(true) }, "Approve and spend"),
    el("button", { class: "ghost", onclick: () => decide(false) }, "Decline")));
  $("#log").append(card); card.scrollIntoView({ block: "end" });
  pendingCost.set(id, card); refreshBulk();
}

// ---------- side panels ----------
function renderTodos(todos) {
  const ol = $("#todos");
  if (!todos || !todos.length) { ol.replaceChildren(el("li", { class: "muted" }, "No plan yet.")); return; }
  ol.replaceChildren(...todos.map((t) => el("li", { class: t.status }, t.content)));
}

let currentVersion = null;
async function refresh() {
  if (!project) return;
  const s = await api(`/api/projects/${project}/state`);
  // player
  const vs = s.renders.filter((r) => !r.proxy || !s.renders.some((x) => x.v === r.v && !x.proxy));
  $("#versions").replaceChildren(...vs.map((r) => {
    const label = `v${r.v}${r.proxy ? " proxy" : ""}${r.delivered ? (r.delivered.pass ? " ✓" : " ✗") : " rough"}`;
    return el("button", { class: "ghost" + (currentVersion === r.v ? " on" : ""), onclick: () => play(r, s) }, label);
  }));
  if (vs.length && currentVersion == null) play(vs[vs.length - 1], s);
  // reviews
  $("#glitches").textContent = s.glitches || "None yet.";
  const w = $("#watch");
  if (!s.watch.length) w.textContent = "None yet.";
  else w.replaceChildren(...s.watch.map((r) => el("div", { class: "watchset" },
    el("div", { class: "muted" }, `${r.mode} · ${r.model} · ${r.file}`),
    ...r.events.map((e) => el("div", { class: `ev ${e.severity || ""}` },
      el("button", { class: "ghost ts", type: "button", onclick: () => seek(e.t) }, fmt(e.t)),
      ` ${e.kind ? e.kind + ": " : ""}${e.what || ""}`)),
    ...r.notes.map((n) => el("div", { class: "muted" }, n)))));
  $("#images").replaceChildren(...s.images.slice().reverse().map((p) => el("a", { href: `/files/${project}/${p}`, target: "_blank" },
    el("img", { src: `/files/${project}/${p}`, loading: "lazy", alt: p }), p.split("/").slice(-2).join("/"))));
  $("#notes").textContent = s.notes || "No notes yet.";
  $("#sources").replaceChildren(...s.sources.map((f) => el("li", {}, f)));
  $("#budget").value = s.budget.limit_usd ?? "";
  $("#ledger").replaceChildren(...s.ledger.slice().reverse().map((e) =>
    el("li", {}, `${e.time} · ${e.service} ${e.operation} · ${e.status}${e.estimate_usd != null ? ` · $${e.estimate_usd}` : ""}`)));
  if (s.agent) { renderTodos(s.agent.todos); $("#status").textContent = s.agent.busy ? "Agent working…" : "Idle"; }
}

function play(r, s) {
  currentVersion = r.v;
  const file = r.delivered ? r.delivered.file : r.rough;
  $("#video").src = `/files/${project}/${file}`;
  const qc = s.qc[`v${r.v}`];
  const pre = $("#qc");
  if (qc) {
    pre.replaceChildren(...qc.summary.split("\n").map((l) => el("div", { class: l.startsWith("PASS") ? "pass" : "fail" }, l)),
      el("div", { class: "muted" }, qc.cannot_check));
  } else pre.textContent = r.delivered ? "" : "Rough cut (dialogue only) - not delivered yet.";
  document.querySelectorAll("#versions button").forEach((b) => b.classList.toggle("on", b.textContent.startsWith(`v${r.v}`)));
}

function fmt(t) { const m = Math.floor(t / 60); return `${m}:${(t - m * 60).toFixed(1).padStart(4, "0")}`; }
function seek(t) { showTab("player"); const v = $("#video"); v.currentTime = Math.max(0, t - 1); v.play().catch(() => {}); }
$("#mark").addEventListener("click", () => {
  const t = $("#video").currentTime || 0;
  const box = $("#listen");
  box.value = (box.value ? box.value + "\n" : "") + `at ${fmt(t)} (${t.toFixed(2)} s): `;
  box.focus();
});

$("#sendListen").addEventListener("click", () => {
  const t = $("#listen").value.trim();
  if (!t || busy) return;
  const msg = `Listening notes on v${currentVersion ?? "latest"}: ${t}`;
  $("#listen").value = "";
  addMsg("user", msg);
  stream(`/api/projects/${project}/chat`, { message: msg });
});

$("#saveBrief").addEventListener("click", async () => {
  await api(`/api/projects/${project}/brief`, { method: "PUT", body: JSON.stringify({ text: $("#brief").value }) });
  $("#status").textContent = "Brief saved";
});
$("#saveBudget").addEventListener("click", async () => {
  const v = $("#budget").value;
  await api(`/api/projects/${project}/budget`, { method: "PUT", body: JSON.stringify({ limit_usd: v === "" ? null : Number(v) }) });
  $("#status").textContent = "Budget saved";
});

// uploads
async function upload(files) {
  if (!files.length || !project) return;
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  $("#status").textContent = `Uploading ${files.length} file(s)…`;
  const r = await fetch(`/api/projects/${project}/upload`, { method: "POST", body: fd });
  $("#status").textContent = r.ok ? "Uploaded" : "Upload failed";
  refresh();
}
$("#files").addEventListener("change", (e) => upload(e.target.files));
const drop = $("#drop");
drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); upload(e.dataTransfer.files); });

// tabs
function showTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => (t.hidden = t.id !== `tab-${name}`));
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));

loadProjects();
