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
//
// unless config "web" "read_only" is on, the process
// bar has Run or Stop (POST /api/alerts/run, stop),
// "Add alert" opens a form for a basetrades or a
// gain alert (POST /api/alerts/add) and each card has
// Delete (after asking; POST /api/alerts/delete).
// The server checks them like the shell; its texts
// are shown.

(function () {
  "use strict";

  var $ = nx.$;
  var el = nx.el;
  var num = nx.num;
  var put = nx.put;
  var cards = {}; // alert id -> its card's parts
  var lastData = null; // the last /api/alerts
  var refresh = null; // asks /api/alerts right away

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
    $("proc-acts").hidden = !canChange();
    // nothing to check without an alert
    $("proc-run").hidden = p.state === "running" ||
      !lastData.alerts.length;
    $("proc-stop").hidden = p.state !== "running";
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
    c.acts = el("span", "acts");
    c.del = el("button", "btn danger sm", "Delete");
    c.del.type = "button";
    c.del.addEventListener("click", function () {
      remove(a.id, c.del);
    });
    c.acts.appendChild(c.del);
    c.foot.appendChild(c.acts);
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
    c.acts.hidden = !canChange();
    return c.box;
  }

  // ---------- changes ----------

  function canChange() {
    return lastData !== null && !lastData.read_only;
  }

  function busy(b, text) {
    b.dataset.text = b.textContent;
    b.textContent = text;
    b.disabled = true;
  }

  function idle(b) {
    if (b.dataset.text) b.textContent = b.dataset.text;
    b.disabled = false;
  }

  // run or stop the process
  function act(what, b, text) {
    busy(b, text);
    nx.send("/api/alerts/" + what, {})
      .then(function (result) {
        idle(b);
        nx.tell(result.text);
        refresh();
      })
      .catch(function (error) {
        idle(b);
        nx.tell("the alerts not " +
          (what === "run" ? "started" : "stopped") + ": " +
          (error.message || error), true);
      });
  }

  // delete alert id, after asking, like 'rm alert'
  function remove(id, b) {
    var a = lastData.alerts.filter(function (one) {
      return one.id === id;
    })[0];
    var question = "Delete alert " + id +
      (a ? ": " + a.kind + " " + a.text : "") + "?";
    if (lastData.alerts.length === 1 &&
        lastData.process.state === "running") {
      question += " It is the last one: the alerts " +
        "process stops.";
    }
    if (!window.confirm(question)) return;
    busy(b, "Deleting…");
    nx.send("/api/alerts/delete", { id: id })
      .then(function (result) {
        nx.tell(result.text);
        refresh();
      })
      .catch(function (error) {
        idle(b);
        nx.tell("alert " + id + " not deleted: " +
          (error.message || error), true);
      });
  }

  // ---------- the add form ----------

  var HINT = {
    basetrades: "A message each time the price of a " +
      "basetrade's stock crosses this percent below " +
      "(down) or above (up) its buying price.",
    gain: "A message each time the gain (or loss) of a " +
      "held stock, or of each one with all, reaches the " +
      "amount: in money for the whole position, or in % " +
      "of its average buy price."
  };

  function kind() {
    return $("add-form").elements.kind.value;
  }

  // the fields of the kind chosen
  function showKind() {
    var gain = kind() === "gain";
    $("f-percent-field").hidden = gain;
    $("f-stock-field").hidden = !gain;
    $("f-value-field").hidden = !gain;
    $("f-unit-field").hidden = !gain;
    $("f-dir-label").textContent =
      gain ? "Gain or loss" : "Direction";
    $("f-down-text").textContent = gain ? "Loss" : "Down";
    $("f-up-text").textContent = gain ? "Gain" : "Up";
    $("f-hint").textContent = HINT[kind()];
  }

  function openForm() {
    var select = $("f-stock");
    select.textContent = "";
    ["all"].concat(lastData.names).forEach(function (name) {
      var option = el("option", "", name);
      option.value = name;
      select.appendChild(option);
    });
    $("f-basetrades").checked = true;
    $("f-down").checked = true;
    $("f-percent").value = "";
    $("f-value").value = "";
    $("f-unit").value = "amount";
    showKind();
    $("f-error").hidden = true;
    $("add").hidden = false;
    $("add-open").setAttribute("aria-expanded", "true");
    $("f-percent").focus();
  }

  function closeForm() {
    $("add").hidden = true;
    $("add-open").setAttribute("aria-expanded", "false");
  }

  function formError(text) {
    $("f-error").textContent = nx.sentence(text);
    $("f-error").hidden = false;
  }

  function submit(event) {
    event.preventDefault();
    var form = $("add-form");
    var down = form.elements.direction.value === "down";
    var change;
    // an input of type number gives "" for what
    // isn't a number
    if (kind() === "basetrades") {
      var percent = $("f-percent").value.trim();
      if (!percent) {
        formError("give the percent");
        return;
      }
      change = {
        kind: "basetrades",
        direction: down ? "down" : "up",
        percent: Number(percent)
      };
    } else {
      var value = $("f-value").value.trim();
      if (!value) {
        formError("give the gain");
        return;
      }
      change = {
        kind: "gain",
        stock: $("f-stock").value,
        // a loss is a negative gain, as in the shell
        value: (down ? -1 : 1) * Number(value),
        in_percent: $("f-unit").value === "percent"
      };
    }
    busy($("f-submit"), "Saving…");
    nx.send("/api/alerts/add", change)
      .then(function (result) {
        idle($("f-submit"));
        closeForm();
        if (result.start_error) {
          nx.tell(result.text + ", but the alerts aren't " +
            "checked: " + result.start_error, true);
        } else {
          nx.tell(result.text);
        }
        refresh();
      })
      .catch(function (error) {
        idle($("f-submit"));
        formError(error.message || error);
      });
  }

  $("add-open").addEventListener("click", function () {
    if ($("add").hidden) openForm(); else closeForm();
  });
  $("f-cancel").addEventListener("click", closeForm);
  $("add-form").addEventListener("submit", submit);
  Array.prototype.forEach.call(
    $("add-form").elements.kind,
    function (radio) {
      radio.addEventListener("change", showKind);
    }
  );
  $("proc-run").addEventListener("click", function () {
    act("run", $("proc-run"), "Starting…");
  });
  $("proc-stop").addEventListener("click", function () {
    act("stop", $("proc-stop"), "Stopping…");
  });

  // ---------- drawing ----------

  function draw(data) {
    lastData = data;
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
    $("alerts-sub").textContent = (count
      ? count + (count === 1 ? " alert" : " alerts") +
        " · " + reached + " reached"
      : "") + (data.read_only
      ? (count ? " · " : "") + "read-only" : "");
    $("no-alerts").hidden = count > 0;
    $("add-open").hidden = data.read_only;
    if (data.read_only) closeForm();
  }

  refresh = nx.poll("/api/alerts", draw);
})();
