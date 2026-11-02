// nX-sig web: the alerts page, served as
// /js/alerts.js after /js/app.js
//
// app.js asks /api/alerts every interval; this draws
// the alerts process (running, on another device,
// stopped) and a card per saved alert: its text
// ("down 10%", "TSMX +100"), its kind and a table of
// its level per stock with the price and how far it
// still has to move, or "reached". A card is made
// once and only its texts change.

(function () {
  "use strict";

  var $ = nx.$;
  var el = nx.el;
  var num = nx.num;
  var put = nx.put;
  var cards = {}; // alert id -> its card's parts

  var KIND = {
    basetrades: "from each basetrade",
    gain: "gain"
  };

  // ---------- the process ----------

  function drawProcess(p) {
    var dot = "off", chip = "idle", word = "stopped";
    var text = "not running, the alerts aren't checked";
    if (p.state === "running") {
      dot = "";
      chip = "up";
      word = "running";
      text = p.updated
        ? "last check " + nx.clock(p.updated)
        : "starting, no check yet";
    } else if (p.state === "elsewhere") {
      dot = "warn";
      chip = "warn";
      word = "elsewhere";
      text = "not here, the background tasks run on " +
        p.owner;
    }
    $("proc-dot").className = "dot " + dot;
    $("proc-state").className = "chip " + chip;
    $("proc-state").textContent = word;
    put($("proc-text"), "proc", text);
  }

  // ---------- a card ----------

  function card(a) {
    var c = cards[a.id];
    if (c) return c;
    c = { box: el("article", "alert") };
    var head = el("div", "alert-h");
    c.text = el("b");
    c.kind = el("span", "what");
    head.appendChild(c.text);
    head.appendChild(c.kind);
    c.box.appendChild(head);
    var wrap = el("div", "tbl-wrap");
    var table = el("table", "levels");
    var tr = el("tr");
    ["Stock", "Level", "Price", "To go"].forEach(function (t) {
      var th = el("th", "", t);
      th.scope = "col";
      tr.appendChild(th);
    });
    var thead = el("thead");
    thead.appendChild(tr);
    table.appendChild(thead);
    c.rows = el("tbody");
    table.appendChild(c.rows);
    wrap.appendChild(table);
    c.box.appendChild(wrap);
    c.none = el("p", "alert-none");
    c.box.appendChild(c.none);
    c.foot = el("div", "ladder-foot");
    c.about = el("span");
    c.foot.appendChild(c.about);
    c.box.appendChild(c.foot);
    cards[a.id] = c;
    return c;
  }

  // the "To go" cell: the distance, or a chip once
  // reached (green up, red down)
  function toGo(td, a, r) {
    td.textContent = "";
    if (r.reached) {
      td.appendChild(el("span",
        "chip " + (a.direction === "up" ? "up" : "down"),
        "reached"));
    } else {
      td.textContent = r.away_pct === null
        ? "-" : num(r.away_pct, 1) + "%";
    }
  }

  function drawRows(c, a) {
    c.rows.textContent = "";
    a.levels.forEach(function (r) {
      var tr = el("tr");
      if (r.reached) tr.className = "reached";
      tr.appendChild(el("td", "key", r.stock));
      tr.appendChild(el("td", "", num(r.level, 2)));
      tr.appendChild(el("td", "px", num(r.price, 2)));
      var td = el("td");
      toGo(td, a, r);
      tr.appendChild(td);
      c.rows.appendChild(tr);
    });
  }

  function drawCard(a) {
    var c = card(a);
    c.box.setAttribute("aria-label", "Alert " + a.id + ", " +
      a.text);
    c.text.textContent = a.text;
    c.kind.textContent = KIND[a.kind] || a.kind;
    drawRows(c, a);
    var empty = !a.levels.length;
    c.rows.parentNode.parentNode.hidden = empty;
    c.none.hidden = !empty;
    c.none.textContent = a.kind === "gain"
      ? (a.stock === "all" ? "no stock held"
        : a.stock + " isn't held")
      : "no basetrades yet";
    var reached = a.levels.filter(function (r) {
      return r.reached;
    }).length;
    c.about.textContent = "#" + a.id + " · " +
      (reached ? reached + " reached · " : "") +
      "since " + nx.shortDate(a.created.split(" ")[0]);
    return c.box;
  }

  function draw(data) {
    drawProcess(data.process);
    var box = $("alerts");
    var ids = {};
    data.alerts.forEach(function (a) {
      ids[a.id] = true;
      // appending again keeps the id order
      box.appendChild(drawCard(a));
    });
    Object.keys(cards).forEach(function (id) {
      if (!ids[id]) {
        box.removeChild(cards[id].box);
        delete cards[id];
      }
    });
    var count = data.alerts.length;
    var reached = data.alerts.filter(function (a) {
      return a.levels.some(function (r) { return r.reached; });
    }).length;
    $("alerts-sub").textContent = count
      ? count + (count === 1 ? " alert" : " alerts") +
        " · " + reached + " reached"
      : "";
    $("no-alerts").hidden = count > 0;
  }

  nx.poll("/api/alerts", draw);
})();
