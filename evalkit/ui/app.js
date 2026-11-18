/* AgentEval 控制台前端：只认 /api/overview、/api/suite/{slug}、/api/run/{slug}、/api/status
   没有框架、没有 CDN —— 副本可以直接随仓库分发，离线也能开（静态快照走 web.py）。 */
const $ = (s) => document.querySelector(s);
const COL = { ok: "#2ee6c0", warn: "#ffb84d", bad: "#ff6b6b" };
const state = { ov: null, active: null, cache: {}, sort: { key: "rule_score", dir: -1 }, open: null };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (v, suf = "") => (v === null || v === undefined ? "—" : v + suf);
const color = (rate) => (rate >= 90 ? COL.ok : rate >= 70 ? COL.warn : COL.bad);

async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error(`${path} → ${r.status}`);
  return r.json();
}

function toast(msg, ms = 2600) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("on");
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.remove("on"), ms);
}

/* ---------------------------------------------------------------- rail */
function ringSvg(rate) {
  const c = color(rate);
  return `<span class="ring" style="background:conic-gradient(${c} ${rate}%,#1a2632 0)">
    <i>${rate}%</i></span>`;
}

function renderRail() {
  const ov = state.ov;
  $("#rail-count").textContent = `${ov.totals.systems}`;
  $("#rail").innerHTML = ov.suites
    .map(
      (s) => `<div class="s ${state.active === s.slug ? "on" : ""}" data-slug="${s.slug}">
        ${ringSvg(s.rate)}
        <span class="meta"><span class="n">${esc(s.suite)}</span>
        <em>${s.cases} 条 · p50 ${fmt(s.p50)}s</em></span>
        <button class="runbtn" data-run="${s.slug}" title="跑这套">▶</button>
      </div>`
    )
    .join("");
  $("#f-runs").textContent = ov.runs_dir;
  $("#f-gen").textContent = ov.generated_at;
}

/* ---------------------------------------------------------------- KPI */
function renderKpis() {
  const t = state.ov.totals;
  const cards = [
    { k: "规则通过率", v: t.rate + "%", cls: "acc", s: `${t.pass} / ${t.cases} 条用例` },
    { k: "Judge 一致率", v: fmt(t.judge_rate, "%"), cls: "", s: `${t.judge_n} 条被判` },
    { k: "待修 badcase", v: t.badcases, cls: t.badcases ? "warn" : "", s: `risk_fail ${t.risk_fail}` },
    { k: "接入系统", v: t.systems, cls: "", s: "python × 5 · http × 1" },
  ];
  $("#kpis").innerHTML = cards
    .map((c) => `<div class="kpi"><div class="k">${c.k}</div>
      <div class="v ${c.cls}">${c.v}</div><div class="s">${c.s}</div></div>`)
    .join("");
}

/* ---------------------------------------------------------------- 通过率条 */
function renderBars() {
  const head = `<div class="brow bhead"><div class="nm">系统</div><div></div>
    <div class="val">通过率</div><div class="sm">judge</div><div class="sm">hit@1</div><div class="sm">p50</div></div>`;
  $("#bars").innerHTML = head + state.ov.suites
    .map((s) => {
      const c = color(s.rate);
      return `<div class="brow" data-slug="${s.slug}">
        <div class="nm">${esc(s.suite)}</div>
        <div class="track"><i style="width:${s.rate}%;background:${c}"></i></div>
        <div class="val" style="color:${c}">${s.rate}%</div>
        <div class="sm">${fmt(s.judge_rate, "%")}</div>
        <div class="sm">${fmt(s.hit1, "%")}</div>
        <div class="sm">${fmt(s.p50)}s</div>
      </div>`;
    })
    .join("");
}

/* ---------------------------------------------------------------- 明细表 */
async function casesFor(slug) {
  if (state.cache[slug]) return state.cache[slug];
  const d = await api(`/api/suite/${slug}`);
  state.cache[slug] = d.cases.map((c) => ({ ...c, suite: slug }));
  return state.cache[slug];
}

async function allCases() {
  const slugs = state.ov.suites.map((s) => s.slug);
  const all = await Promise.all(slugs.map(casesFor));
  return all.flat();
}

function applyFilter(rows) {
  const q = $("#q").value.trim().toLowerCase();
  const onlyFail = $("#only-fail").checked;
  return rows.filter((r) => {
    if (onlyFail && r.rule_pass) return false;
    if (!q) return true;
    return [r.id, r.category, r.answer, (r.turns || []).join(" ")]
      .join(" ").toLowerCase().includes(q);
  });
}

function sortRows(rows) {
  const { key, dir } = state.sort;
  return rows.slice().sort((a, b) => {
    const pick = (r) =>
      key === "verdict" ? (r.rule_pass ? 1 : 0) : r[key] === null || r[key] === undefined ? -Infinity : r[key];
    const va = pick(a), vb = pick(b);
    if (typeof va === "string" || typeof vb === "string") return String(va).localeCompare(String(vb)) * dir;
    return (va - vb) * dir;
  });
}

async function renderTable() {
  const rows = sortRows(applyFilter(state.active ? await casesFor(state.active) : await allCases()));
  $("#table-title").textContent = state.active
    ? `${state.ov.suites.find((s) => s.slug === state.active).suite} · 用例明细`
    : "全部用例";
  $("#table-note").textContent = `${rows.length} 条`;
  document.querySelectorAll("th[data-sort]").forEach((th) =>
    th.classList.toggle("sorted", th.dataset.sort === state.sort.key));

  const tb = $("#cases tbody");
  tb.innerHTML = rows
    .map((r) => {
      const v = r.rule_pass
        ? '<span class="pill ok"><span class="dotp"></span>通过</span>'
        : r.risk_fail
        ? '<span class="pill risk"><span class="dotp"></span>风险否决</span>'
        : '<span class="pill no"><span class="dotp"></span>失败</span>';
      return `<tr class="row" data-slug="${r.suite}" data-id="${esc(r.id)}">
        <td class="id">${esc(r.id)}</td>
        <td>${esc(r.category || "")}</td>
        <td class="num">${fmt(r.rule_score)}</td>
        <td class="num">${fmt(r.judge_score)}</td>
        <td class="num">${fmt(r.t_sut)}s</td>
        <td>${v}</td>
        <td class="chev">›</td>
      </tr>`;
    })
    .join("");
  $("#empty").hidden = rows.length > 0;
}

/* ---------------------------------------------------------------- badcase 卡 */
function renderBadcards() {
  const items = [];
  state.ov.suites.forEach((s) => s.badcases.forEach((b) => items.push({ slug: s.slug, id: b, suite: s.suite })));
  $("#badcards").innerHTML = items.length
    ? items
        .map(
          (b) => `<div class="bcard" data-slug="${b.slug}" data-id="${esc(b.id)}">
            <div class="bid">${esc(b.id)}</div>
            <div class="bs">${esc(b.suite)}</div></div>`
        )
        .join("")
    : '<div class="bnone">当前没有 badcase。</div>';
}

/* ---------------------------------------------------------------- 抽屉 */
function checksHtml(checks) {
  return (checks || [])
    .map((c) => {
      const cls = c.result === true ? "ok" : c.result === false ? "no" : "na";
      const label = c.result === true ? "通过" : c.result === false ? "失败" : "NA";
      return `<span class="chk ${cls}">${esc(c.check)} · ${esc(c.dim)} · ${label}${
        c.err ? " · " + esc(c.err) : ""}</span>`;
    })
    .join("");
}

function dimsHtml(dims) {
  const keys = Object.keys(dims || {});
  if (!keys.length) return '<span class="warnline">该用例没有可计分的维度</span>';
  return `<div class="dims">${keys
    .map((k) => {
      const v = dims[k];
      const num = v === "NA" ? 0 : Number(v);
      return `<div class="dim"><span>${esc(k)}</span>
        <span class="dt"><i style="width:${num * 10}%"></i></span>
        <span class="mono">${esc(v)}</span></div>`;
    })
    .join("")}</div>`;
}

async function openCase(slug, id) {
  const rows = await casesFor(slug);
  const r = rows.find((x) => x.id === id);
  if (!r) return;
  state.open = { slug, id };
  $("#d-id").textContent = `${r.id}`;
  $("#d-sub").textContent = `${state.ov.suites.find((s) => s.slug === slug)?.suite || slug} · ${r.category || ""}`;
  const body = [];
  body.push(`<div class="dsec"><h3>输入 <em>${(r.turns || []).length} 轮</em></h3>
    <div class="turns">${(r.turns || []).map((t) => `<div class="turn">${esc(t)}</div>`).join("")}</div></div>`);
  body.push(`<div class="dsec"><h3>实际输出 <em>rule ${fmt(r.rule_score)} · judge ${fmt(r.judge_score)}</em></h3>
    <pre>${esc(r.answer || "(空)")}</pre></div>`);
  if (r.error) body.push(`<div class="dsec"><h3>SUT 异常</h3><div class="warnline">${esc(r.error)}</div></div>`);
  body.push(`<div class="dsec"><h3>断言 <em>${(r.checks || []).length} 条</em></h3>
    <div class="checks">${checksHtml(r.checks)}</div></div>`);
  body.push(`<div class="dsec"><h3>维度得分 <em>0-10</em></h3>${dimsHtml(r.dim_scores)}</div>`);
  if (r.judge_reason) body.push(`<div class="dsec"><h3>Judge 理由</h3><div class="turn">${esc(r.judge_reason)}</div></div>`);
  if (r.retrieved && r.retrieved.length)
    body.push(`<div class="dsec"><h3>检索命中</h3><div class="kv">${r.retrieved
      .map((x) => `<span>${esc(typeof x === "string" ? x : x.source || "")}</span><b></b>`)
      .join("")}</div></div>`);
  body.push(`<div class="dsec"><h3>耗时</h3><div class="kv">
    <span>SUT</span><b>${fmt(r.t_sut)}s</b><span>suite</span><b>${esc(slug)}</b></div></div>`);
  $("#d-body").innerHTML = body.join("");
  $("#drawer").classList.add("on");
  $("#drawer").setAttribute("aria-hidden", "false");
  $("#backdrop").classList.add("on");
}

function closeDrawer() {
  $("#drawer").classList.remove("on");
  $("#drawer").setAttribute("aria-hidden", "true");
  $("#backdrop").classList.remove("on");
  state.open = null;
}

/* ---------------------------------------------------------------- 跑批 */
async function runSuite(slug) {
  try {
    const r = await api(`/api/run/${slug}`, { method: "POST" });
    if (!r.started) return toast(`已经在跑了（自 ${r.since}）`);
    toast(`已开始跑 ${slug} …`);
    $("#runmeta").textContent = `running ${slug}`;
    const timer = setInterval(async () => {
      const st = await api("/api/status");
      const cur = st.running[slug];
      if (!cur || cur.state !== "running") {
        clearInterval(timer);
        $("#runmeta").textContent = "";
        toast(cur && cur.state === "failed" ? `${slug} 跑批失败，看终端输出` : `${slug} 跑完了，刷新中…`);
        state.cache = {};
        await load();
      }
    }, 1600);
  } catch (e) {
    toast(`跑批失败：${e.message}`);
  }
}

/* ---------------------------------------------------------------- 事件 */
function bind() {
  $("#rail").addEventListener("click", (e) => {
    const run = e.target.closest("[data-run]");
    if (run) { e.stopPropagation(); return runSuite(run.dataset.run); }
    const item = e.target.closest(".s");
    if (item) selectSuite(item.dataset.slug);
  });
  $("#bars").addEventListener("click", (e) => {
    const row = e.target.closest(".brow");
    if (row) selectSuite(row.dataset.slug);
  });
  $("#cases").addEventListener("click", (e) => {
    const tr = e.target.closest("tr.row");
    if (tr) openCase(tr.dataset.slug, tr.dataset.id);
  });
  $("#badcards").addEventListener("click", (e) => {
    const c = e.target.closest(".bcard");
    if (c) openCase(c.dataset.slug, c.dataset.id);
  });
  document.querySelectorAll("th[data-sort]").forEach((th) =>
    th.addEventListener("click", async () => {
      const k = th.dataset.sort;
      state.sort = { key: k, dir: state.sort.key === k ? -state.sort.dir : -1 };
      await renderTable();
    }));
  $("#q").addEventListener("input", debounce(renderTable, 180));
  $("#only-fail").addEventListener("change", renderTable);
  $("#btn-refresh").addEventListener("click", async () => { state.cache = {}; await load(); toast("已刷新"); });
  $("#btn-export").addEventListener("click", async () => {
    const data = await api("/api/overview");
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "agenteval-overview.json";
    a.click();
    toast("已导出 overview.json");
  });
  $("#d-close").addEventListener("click", closeDrawer);
  $("#backdrop").addEventListener("click", closeDrawer);
  $("#d-rerun").addEventListener("click", () => state.open && runSuite(state.open.slug));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

async function selectSuite(slug) {
  state.active = state.active === slug ? null : slug;
  renderRail();
  await renderTable();
  if (state.active) toast(`只看 ${slug}`);
}

/* ---------------------------------------------------------------- 启动 */
async function load() {
  state.ov = await api("/api/overview");
  renderRail();
  renderKpis();
  renderBars();
  renderBadcards();
  await renderTable();
}

bind();
load().catch((e) => {
  document.body.insertAdjacentHTML(
    "beforeend",
    `<div class="toast on">加载失败：${esc(e.message)} —— 先跑 <b>python -m evalkit.cli serve</b></div>`);
});
