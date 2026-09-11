// The control plane page. Every control is one typed action from /api/actions; the page never
// builds argv, never names an output directory and never picks a model. Plain script, no build.
"use strict";

const token = (location.hash.match(/token=([A-Za-z0-9_-]+)/) || [])[1] || "";
const $ = (sel, root) => (root || document).querySelector(sel);
const el = (tag, attrs, ...children) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") node.className = v;
    else if (k === "text") node.textContent = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) node.setAttribute(k, v);
  }
  for (const c of children) if (c !== null && c !== undefined) node.append(c);
  return node;
};

const state = { actions: [], library: null, platform: null, prompts: {} };

async function api(path, options) {
  const headers = Object.assign({ "X-Plane-Token": token }, (options && options.headers) || {});
  const response = await fetch(path, Object.assign({}, options, { headers }));
  const body = await response.json().catch(() => ({ ok: false, message: "not JSON" }));
  if (!response.ok || body.ok === false) throw Object.assign(new Error(body.message || response.statusText), { body });
  return body;
}

function badge(text, tone) { return el("span", { class: "badge " + (tone || ""), text }); }
// A declaration field that should be a list, tolerated when a hand-written file made it a scalar.
const list = (value, single) => Array.isArray(value) ? value.map(String) : value !== undefined && value !== null ? [String(value)] : single !== undefined && single !== null ? [String(single)] : [];

function confirmRun(action, argsPreview) {
  const dialog = $("#confirm");
  $("#confirm-title").textContent = action.label;
  $("#confirm-text").textContent = `This runs \`pat ${action.route}\` (effect ${action.effect}). ` +
    (action.effect === "changes-game" || action.effect === "query-engine" ? "It talks to the running game. " : "") +
    (action.route.startsWith("agent ") ? "It writes to your T3 Code server with your configured token. " : "") +
    "Continue?";
  $("#confirm-argv").textContent = JSON.stringify(argsPreview, null, 1);
  return new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true });
    dialog.showModal();
  });
}

async function runAction(action, args, statusNode) {
  let confirmed = false;
  if (action.confirm) {
    confirmed = await confirmRun(action, args);
    if (!confirmed) { statusNode.textContent = "not started"; return; }
  }
  statusNode.textContent = "starting…";
  try {
    const body = await api("/api/run", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: action.id, args, confirmed }) });
    statusNode.textContent = `run ${body.run.number} started`;
    await pollRun(body.run.run_id, statusNode);
  } catch (err) {
    statusNode.textContent = "";
    statusNode.append(badge(err.body && err.body.error_code || "error", "bad"), " ", err.message,
      err.body && err.body.hint ? ` (${err.body.hint})` : "");
  }
}

async function pollRun(runId, statusNode) {
  for (let i = 0; i < 3600; i++) {
    await new Promise((r) => setTimeout(r, 1000));
    const { run } = await api("/api/runs/" + runId);
    if (run.status !== "running") {
      statusNode.textContent = "";
      const ok = run.result && run.result.ok === true;
      const inner = ok ? run.result.result : null;
      statusNode.append(badge(ok ? "ok" : (run.result && run.result.error_code) || run.status, ok ? "ok" : "bad"), " ",
        el("details", {}, el("summary", { text: `run ${run.number}: ${run.route} (exit ${run.exit_code})` + (run.output ? `, receipt in ${run.output}` : "") }),
          el("pre", { text: JSON.stringify(run.result || run.stderr_head || run.stdout_head, null, 1) })));
      if (inner && Array.isArray(inner.undecided) && inner.undecided.length) statusNode.append(decisionList(inner.undecided));
      if (inner && inner.thread_url && inner.thread_id) statusNode.append(" ", el("a", { href: inner.thread_url, target: "_blank", rel: "noreferrer noopener", text: "open the thread" }));
      if (inner && Array.isArray(inner.instances)) rememberModels(inner);
      if (ok) refreshAll();
      return run;
    }
    statusNode.textContent = `running… (${i + 1}s)`;
  }
}

function decisionList(undecided) {
  // Collisions the plan listed: each is a decision to record in the composition (or a rename), never skipped.
  const list = el("ol", { class: "decisions" });
  for (const row of undecided) {
    list.append(el("li", {}, el("code", { text: row.collision }), ` (${row.kind}; ${row.modules.join(", ")}): `, el("span", { class: "muted", text: row.how })));
  }
  return el("div", { class: "decision-box" }, badge(`${undecided.length} undecided`, "warn"),
    el("p", { text: "Record an owner for each under decisions in the composition, or rename the target, then plan again. Or dispatch it: the Agent screen's template 'resolve collisions' carries this list." }), list);
}

function rememberModels(result) {
  // The choices the machine offers; the person picks. Nothing is preselected.
  state.models = result;
  for (const form of document.querySelectorAll("form.action")) {
    const instance = form.elements.instance, model = form.elements.model;
    if (!instance || !model) continue;
    // value is the exact id or slug; label is the description. Nothing is parsed back out of a label.
    for (const [node, values] of [[instance, result.instances.map((i) => [i.instance_id, `${i.instance_id} (${i.driver}${i.display_name ? ", " + i.display_name : ""})`])],
                                  [model, result.instances.flatMap((i) => i.models.map((m) => [m.slug, `${m.slug} (${i.instance_id}${m.status ? ", " + m.status : ""})`]))]]) {
      const listId = form.id + "-" + node.name + "-choices";
      let list = document.getElementById(listId);
      if (!list) { list = el("datalist", { id: listId }); form.append(list); node.setAttribute("list", listId); }
      list.replaceChildren(...values.map(([value, label]) => el("option", { value, label })));
    }
    const options = form.elements.options;
    if (options) {
      const rows = [];
      for (const i of result.instances) for (const m of i.models) for (const o of m.options || []) for (const c of o.choices || []) rows.push(`${o.id}=${c.id}`);
      options.placeholder = [...new Set(rows)].join(" ") || options.placeholder;
    }
  }
}

const PROMPT_TEMPLATES = {
  "": "",
  "compose a pack": "Run docs/playbooks/compose-a-pack.md on <composition path>. Plan first, record every undecided collision as a decision with a reason, build, run the preflights the pack needs, and report the six build facts separately.",
  "resolve collisions": "Run pat module plan on <composition path> and resolve every row under undecided: read both modules, decide an owner (or rename a target) with a one-line reason each, record the decisions in the composition, plan again until undecided is empty, then build. Do not skip a collision.",
  "attach a module to a pack": "Run docs/playbooks/attach-to-a-pack.md: base pack <pack path or owner/id@commit>, module <module path>, base <base>, map <map>. The pack is the base member; declare it as a seed first if it is only a mod.ff. Report what was built and what stays untested.",
  "port from prior art": "Run docs/playbooks/find-prior-art.md for <feature>, then docs/playbooks/port-a-feature.md from the sealed donor. Public bytes only, hash everything into the downloads receipt, decline hateful or unlicensed leads. Stop at the offline-verified build and report.",
  "diagnose a crash": "Run docs/playbooks/diagnose-a-crash.md for build <mod.ff sha256> on <map>: the log slice and frame are in <path>. Build the red loop first; end by adding the gate that would have caught it.",
  "load and check on this machine": "Install <mod.ff path> as <folder> with pat game install-mod, then, under this machine's game-control rules and the user's go, load it on <map> and record the post-load checkpoint (fresh engine state, a visual inspection, the playable-spawn check). Report offline verified, installed, launched, loaded, playable separately.",
};

// ----- forms ---------------------------------------------------------------------------------

function pathSelect(param) {
  const select = el("select", { name: param.name });
  select.append(el("option", { value: "", text: "— choose —" }));
  if (state.library) {
    for (const root of state.library.roots) {
      if (!param.roots.includes("library")) continue;
      const rows = param.file === "composition.json" ? root.compositions : param.file === "module.json" ? root.modules : [];
      for (const row of rows) {
        const rel = row.path ? row.path + "/" + param.file : param.file;
        select.append(el("option", { value: JSON.stringify({ root: root.index, path: rel }), text: `${root.root}/${rel}` }));
      }
      if (param.file === "mod.ff") {
        // Every loose package under the root, declared or not; the server lists them by file name.
        for (const rel of root.packages || []) select.append(el("option", { value: JSON.stringify({ root: root.index, path: rel }), text: `${root.root}/${rel}` }));
      }
      if (param.file === "registry.json") {
        select.append(el("option", { value: JSON.stringify({ root: root.index, path: "registry.json" }), text: `${root.root}/registry.json` }));
      }
    }
  }
  if (param.roots.includes("jobs") && state.jobs) {
    for (const run of state.jobs.runs) {
      if (param.file === "composition.json" && run.composition) select.append(el("option", { value: JSON.stringify({ root: "jobs", path: run.composition }), text: `${run.composition} (fetched)` }));
      if (param.file === "receipt.json") select.append(el("option", { value: JSON.stringify({ root: "jobs", path: run.directory + "/receipt.json" }), text: `${run.directory}/receipt.json (${run.command}, ${run.status})` }));
      if (param.file === "mod.ff" && run.mod_ff) select.append(el("option", { value: JSON.stringify({ root: "jobs", path: run.directory + "/" + run.mod_ff }), text: `${run.directory}/${run.mod_ff} (${run.name || run.command})` }));
    }
  }
  return select;
}

function control(param) {
  if (param.kind === "path") return pathSelect(param);
  if (param.kind === "registry_source") {
    const select = pathSelect(Object.assign({}, param, { roots: ["library"], file: "registry.json" }));
    const url = el("input", { type: "url", name: param.name + "_url", placeholder: "or an https:// URL to a registry.json", autocomplete: "off" });
    return el("div", { class: "prompt" }, select, url);
  }
  if (param.kind === "flag") return el("input", { type: "checkbox", name: param.name });
  if (param.kind === "enum") {
    const select = el("select", { name: param.name }, el("option", { value: "", text: "— default —" }));
    for (const c of param.choices) select.append(el("option", { value: c, text: c }));
    return select;
  }
  if (param.kind === "prompt") {
    const area = el("textarea", { name: param.name, placeholder: "Prompt text; a playbook name plus the target is the usual shape" });
    const picker = el("select", { "aria-label": "Prompt template" });
    for (const name of Object.keys(PROMPT_TEMPLATES)) picker.append(el("option", { value: name, text: name || "— template —" }));
    picker.addEventListener("change", () => { if (picker.value) area.value = PROMPT_TEMPLATES[picker.value]; });
    return el("div", { class: "prompt" }, picker, area);
  }
  if (param.kind === "int") return el("input", { type: "number", name: param.name });
  if (param.kind === "options") return el("input", { type: "text", name: param.name, placeholder: "effort=high reasoningEffort=high" });
  return el("input", { type: "text", name: param.name, autocomplete: "off" });
}

function readForm(form, action) {
  const args = {};
  for (const param of action.params) {
    const node = form.elements[param.name];
    if (!node) continue;
    if (param.kind === "flag") { if (node.checked) args[param.name] = true; continue; }
    const raw = node.value;
    if (param.kind === "registry_source") {
      const url = form.elements[param.name + "_url"];
      if (url && url.value.trim()) { args[param.name] = url.value.trim(); continue; }
    }
    if (raw === "" || raw === null) continue;
    if (param.kind === "path") args[param.name] = JSON.parse(raw);
    else if (param.kind === "registry_source") {
      const url = form.elements[param.name + "_url"];
      args[param.name] = url && url.value.trim() ? url.value.trim() : JSON.parse(raw);
    }
    else if (param.kind === "int") args[param.name] = Number(raw);
    else if (param.kind === "options") args[param.name] = raw.split(/\s+/).filter(Boolean);
    else args[param.name] = raw;
  }
  return args;
}

function actionForm(action) {
  const form = el("form", { class: "action" + (action.available_here ? "" : " unavailable"), id: "form-" + action.id });
  form.append(el("h4", {}, action.label, " ", el("code", { text: "pat " + action.route }), " ", badge(action.effect),
    action.available_here ? null : badge(action.requires_windows ? "native Windows only" : action.status, "warn")));
  form.append(el("p", { class: "help", text: action.note || "" }));
  for (const param of action.params) {
    form.append(el("label", { for: action.id + "-" + param.name, text: param.name + (param.required ? " *" : "") }));
    const node = control(param);
    const field = node.tagName === "DIV" ? node.querySelector("textarea, select, input") : node;
    field.id = action.id + "-" + param.name;
    field.title = param.help;
    form.append(node);
  }
  const status = el("span", { class: "muted", "aria-live": "polite" });
  const button = el("button", { type: "submit", class: "primary", text: action.confirm ? "Run (asks first)" : "Run" });
  if (!action.available_here) button.disabled = true;
  form.append(el("menu", {}, button, status));
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    runAction(action, readForm(form, action), status);
  });
  return form;
}

// ----- screens -------------------------------------------------------------------------------

function renderLibrary() {
  const box = $("#library");
  let tableBox = $("#library-tables");
  if (!tableBox) {
    tableBox = el("div", { id: "library-tables" });
    box.append(tableBox, ...state.actions.filter((a) => a.screen === "library").map(actionForm));
  }
  tableBox.replaceChildren();
  if (!state.library) return;
  for (const root of state.library.roots) {
    const box = tableBox;
    box.append(el("h3", {}, root.root, " ", root.truncated ? badge("truncated at the catalog bound", "warn") : null));
    const table = el("table", {}, el("thead", {}, el("tr", {}, ...["id / name", "kind", "category", "bases", "maps", "tags", "payload", "package"].map((h) => el("th", { text: h })))));
    const body = el("tbody");
    for (const m of root.modules.concat(root.compositions)) {
      body.append(el("tr", {},
        el("td", {}, el("strong", { text: m.id || m.name || "?" }), " ", el("span", { class: "muted", text: m.title || "" }), el("br"), el("code", { text: m.path || "." })),
        el("td", { text: m.kind === "composition" ? "composition" : (m.kind || "module") }),
        el("td", { text: m.category || "" }),
        el("td", { text: list(m.bases, m.base).join(", ") }),
        el("td", { text: list(m.maps, m.map).join(", ") }),
        el("td", { text: list(m.tags).join(", ") }),
        el("td", { text: m.payload || (Array.isArray(m.modules) ? `${m.modules.length} members` : "") }),
        el("td", {}, m.error ? badge(m.error, "bad") : m.seed_error ? badge(m.seed_error, "bad")
          : m.payload === "seed" ? badge(m.package_present ? "present" : "not here (private)", m.package_present ? "ok" : "warn") : "")));
    }
    table.append(body);
    box.append(table);
  }
}

function renderScreen(id, actionIds) {
  const box = $("#" + id);
  if (box.childElementCount) return;  // forms are built once; results stay on screen
  for (const aid of actionIds) {
    const action = state.actions.find((a) => a.id === aid);
    if (action) box.append(actionForm(action));
  }
}

function refreshSelects() {
  // New jobs and declarations appear in every path select without touching the rest of the form.
  for (const form of document.querySelectorAll("form.action")) {
    const action = state.actions.find((a) => "form-" + a.id === form.id);
    if (!action) continue;
    for (const param of action.params) {
      if (param.kind !== "path" && param.kind !== "registry_source") continue;
      const current = form.elements[param.name];
      if (!current) continue;
      const fresh = param.kind === "path" ? pathSelect(param) : pathSelect(Object.assign({}, param, { roots: ["library"], file: "registry.json" }));
      fresh.id = current.id;
      fresh.title = current.title;
      fresh.value = current.value;
      current.replaceWith(fresh);
    }
  }
}

async function renderRuns() {
  const box = $("#runs");
  box.replaceChildren();
  const { runs } = await api("/api/runs");
  const table = el("table", {}, el("thead", {}, el("tr", {}, ...["#", "action", "status", "started", "exit", "output"].map((h) => el("th", { text: h })))));
  const body = el("tbody");
  for (const r of runs) {
    body.append(el("tr", {}, el("td", { text: r.number }), el("td", {}, el("code", { text: r.route })), el("td", {}, badge(r.status, r.status === "finished" && r.exit_code === 0 ? "ok" : r.status === "running" ? "" : "bad")),
      el("td", { text: r.started }), el("td", { text: r.exit_code === null ? "" : r.exit_code }), el("td", {}, el("code", { text: r.output || "" }))));
  }
  table.append(body);
  box.append(el("h3", { text: "This plane's runs" }), table);
  if (state.jobs) {
    const jobs = el("table", {}, el("thead", {}, el("tr", {}, ...["directory", "command", "status", "started", "package", "error"].map((h) => el("th", { text: h })))));
    const jb = el("tbody");
    for (const j of state.jobs.runs) {
      jb.append(el("tr", {}, el("td", {}, el("code", { text: j.directory })), el("td", { text: j.command || "" }), el("td", {}, badge(j.status || "?", j.status === "succeeded" ? "ok" : "bad")),
        el("td", { text: j.started || "" }), el("td", { text: j.mod_ff ? `${j.name || ""} ${j.mod_ff}` : "" }), el("td", { text: j.error || "" })));
    }
    jobs.append(jb);
    box.append(el("h3", { text: "Receipts under " + state.jobs.jobs }), jobs);
  }
}

async function refreshAll() {
  const [library, jobs] = await Promise.all([api("/api/library"), api("/api/jobs")]);
  state.library = library;
  state.jobs = jobs;
  renderLibrary();
  renderScreen("pack", ["module-plan", "module-build", "project-verify"]);
  renderScreen("install", ["game-mods", "game-install-mod", "game-status", "game-info", "game-launch", "game-select-mod", "game-load-map", "game-check-load"]);
  renderScreen("agent", ["agent-probe", "agent-hosts", "agent-models", "agent-dispatch", "agent-status", "agent-send", "agent-interrupt"]);
  renderScreen("registry", ["registry-list", "registry-search", "registry-show", "registry-add", "module-fetch"]);
  refreshSelects();
  if (!$("#screen-runs").hidden) await renderRuns();
}

async function main() {
  try {
    const st = await api("/api/state");
    state.platform = st.platform;
    $("#state").textContent = `pat ${st.version} on ${st.platform.system}; library ${st.library.join(", ")}; jobs ${st.jobs}` +
      (st.platform.game_control_supported ? "" : "; game control needs native Windows");
    const { actions } = await api("/api/actions");
    state.actions = actions;
    await refreshAll();
  } catch (err) {
    $("#state").textContent = "";
    $("#state").append(badge("error", "bad"), " ", err.message, " — open the URL printed by pat plane serve (it carries the token).");
  }
  for (const button of document.querySelectorAll("nav button")) {
    button.addEventListener("click", () => showScreen(button.dataset.screen));
  }
  // A screen named in the fragment (#token=…&screen=pack) opens directly.
  const wanted = (location.hash.match(/screen=([a-z]+)/) || [])[1];
  if (wanted && document.querySelector(`nav button[data-screen="${wanted}"]`)) showScreen(wanted);
}

function showScreen(name) {
  for (const b of document.querySelectorAll("nav button")) b.classList.toggle("selected", b.dataset.screen === name);
  for (const section of document.querySelectorAll("main section")) section.hidden = section.dataset.screen !== name;
  if (name === "runs") renderRuns();
}

main();
