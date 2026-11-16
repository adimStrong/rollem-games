// Roll'em link bridge for Chad Smash. The player's link is /chad/#<code> (same code as Roll It).
// Entries are SHARED with Roll It: one qualifying deposit = one play in either game, never both.
// START = POST /api/play/<code> {game:"chad"}: the server checks deposit + turnover, draws the prize and records it
// BEFORE the 15-second game runs. Hits are for fun only; the reward shown at the end is the server's amount.
// No link = demo (practise, no reward).
window.RG = (function () {
  const el = id => document.getElementById(id);
  let raw = ""; try { raw = decodeURIComponent(location.hash.slice(1)).toLowerCase() } catch (e) { raw = "" }
  const code = /^[a-z0-9]{1,32}-[a-z0-9]{2,8}$/.test(raw) ? raw : "";
  const enc = encodeURIComponent(code);
  let S = null, CONF = null, pending = null, busy = false, startHTML = "", timer = null;
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const php = n => "₱" + Number(n || 0).toLocaleString("en-PH", { minimumFractionDigits: Number(n) % 1 ? 2 : 0, maximumFractionDigits: 2 });
  async function post(path, body) {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    const j = await r.json().catch(() => ({})); return { ok: r.ok, status: r.status, ...j };
  }
  function mech() {
    if (!CONF || !el("mech")) return;   // the reward card replaces the start screen; nothing to fill then
    const wager = (CONF.wagerCats || []).includes("all") ? "Any game counts" : "Slot games only";
    el("mech").innerHTML = ["Deposit " + php(CONF.perPlay) + " = 1 entry", (CONF.turnover || 1) + "x wagering", wager,
      "Max " + CONF.maxPlays + " entries per day", "Shared with Roll It"].map(t => "<span>" + esc(t) + "</span>").join("");
    el("rgFoot").innerHTML = "Every play wins a bonus, set by the server when you press START. Entries are shared with Roll It: "
      + "each " + esc(php(CONF.perPlay)) + " deposit gives one play in <b>either</b> game, not both. Play until " + esc(CONF.playUntil || "23:59") + ".";
  }
  function setStart(enabled, label) { const b = el("start"); if (!b || !el("ov").contains(b)) return; b.disabled = !enabled; b.textContent = label || "START"; }
  function status(msg, bad) { const s = el("rgStatus"); if (!s) return; s.textContent = msg || ""; s.classList.toggle("bad", !!bad); }
  function lastUnseenChad() {
    const P = (S && S.plays) || []; const last = P[P.length - 1];
    return last && last.game === "chad" && !last.seen ? last : null;
  }
  function showReward(pl, again) {
    const ov = el("ov"); ov.hidden = false;
    ov.innerHTML = "<h2>YOUR BONUS</h2><div class='rg-reward'>" + php(pl.amount)
      + (pl.tier === 99 ? "<small>MILESTONE PRIZE</small>" : "") + "</div>"
      + "<p class='rg-status'>Recorded automatically — no screenshot needed. Credited the next day at 1:00 PM.</p>"
      + "<button class='btn' id='again'>" + (again || "OK") + "</button>";
    claim(pl); el("again").onclick = backToStart;
    const row = el("againRow"); if (row) { row.innerHTML = ""; row.appendChild(el("again")); row.hidden = false; }
  }
  async function claim(pl) {
    if (!pl) return;
    ((S && S.plays) || []).forEach(p => { if (p.id === pl.id) p.seen = 1 });   // keep the local copy in step so OK doesn't re-show it
    if (pl.seen) return; pl.seen = 1;
    try { await post("/api/seen/" + enc, { id: pl.id }) } catch (e) {}
  }
  function backToStart() {
    pending = null; busy = false;
    const row = el("againRow"); if (row) { row.hidden = true; row.innerHTML = ""; }
    const ov = el("ov"); ov.innerHTML = startHTML; ov.hidden = false;
    if (typeof faceRow === "function") try { faceRow() } catch (e) {}
    el("start").onclick = onStart; mech(); render(); load();
  }
  function render() {
    if (busy || !el("start")) return;   // game running, or the reward card is up

    if (!code) { status("DEMO — practise for free. Ask your agent for your link to win a real bonus."); setStart(true, "START (DEMO)"); return; }
    if (!S) { status("Loading your entries…"); setStart(false); return; }
    if (!S.exists) { status("This link is not valid. Ask your agent for a new link.", true); setStart(false); return; }
    const who = el("rgWho"); who.hidden = false; who.innerHTML = "For <b>" + esc(S.name) + "</b> · " + esc(S.account);
    el("rgSwitch").href = "/#" + code;
    if (S.expired) { status("This link has expired (it was for another day). Ask your agent for a new link.", true); setStart(false); return; }
    const un = lastUnseenChad(); if (un) { showReward(un, "OK"); return; }
    if (S.stopped) { status("The game is paused by the admin right now." + (S.stopNote ? " (" + S.stopNote + ")" : ""), true); setStart(false); return; }
    if (!S.playOpen) { status("Game closed for today. Come back tomorrow.", true); setStart(false); return; }
    if (S.capped) { status("Today's bonus budget is used up. Try again tomorrow.", true); setStart(false); return; }
    if (S.free) {
      if (S.playsUsed >= 1) { status("Nagamit na ang promo link na ito — isang laro lang. Salamat sa paglalaro!", true); setStart(false); return; }
      status("🎁 FREE PLAY promo — isang libreng laro, walang deposit o turnover na kailangan. Good luck!");
      setStart(true, "START (FREE)"); return;
    }
    const used = S.playsUsed, total = S.playsTotal, max = (CONF && CONF.maxPlays) || 5;
    if (used >= max) { status("You used all " + max + " plays for today (Roll It + Chad Smash). Come back tomorrow!", true); setStart(false); return; }
    if (!total || used >= total) { status("No entry left. Deposit " + php(CONF && CONF.perPlay) + " or more for your next play — this page unlocks on its own."); setStart(false); return; }
    if (!S.betOk) { status("Finish your turnover first: " + (S.missing || []).join(" · ") + ". This page refreshes on its own.", true); setStart(false); return; }
    status("Entry " + (used + 1) + " of " + total + " ready · used today: " + used + " (both games)");
    setStart(true, "START");
  }
  async function load() {
    if (!code) { try { CONF = await fetch("/api/config").then(r => r.json()) } catch (e) {} mech(); render(); return; }
    try { const r = await fetch("/api/session/" + enc).then(r => r.json()); if (r.config) CONF = r.config; S = r } catch (e) {}
    mech(); render();
  }
  async function onStart() {
    if (busy) return;
    if (!code) { pending = null; busy = true; startGame(); return; }
    if (!S || el("start").disabled) return;
    busy = true; setStart(false, "STARTING…"); status("Locking in your bonus…");
    let r; try { r = await post("/api/play/" + enc, { game: "chad" }) } catch (e) { r = { ok: false, msg: "No connection. Try again." } }
    if (!r.ok || !r.play) { busy = false; status(r.msg || "Could not start. Try again.", true); if (r.exists) S = r; setTimeout(() => { render() }, 2500); return; }
    S = r; pending = r.play; startGame();
  }
  return {
    init() {
      startHTML = el("ov").innerHTML; el("start").onclick = onStart; load();
      timer = setInterval(() => { if (!busy) load() }, 20000);
    },
    resultHTML() {
      if (!code) return "<div class='rg-reward'>Demo — no reward<small>Get your link from your agent to win a real bonus</small></div><button class='btn' id='again'>PLAY AGAIN</button>";
      if (!pending) return "<button class='btn' id='again'>OK</button>";
      return "<div class='rg-reward'><small>YOUR BONUS</small>" + php(pending.amount) + (pending.tier === 99 ? "<small>MILESTONE PRIZE</small>" : "") + "</div>"
        + "<button class='btn' id='again'>OK</button>";
    },
    afterResult() {
      const b = el("again");
      if (!code) { b.onclick = () => { busy = true; startGame() }; busy = false; return; }
      claim(pending); b.onclick = backToStart;
    },
  };
})();
