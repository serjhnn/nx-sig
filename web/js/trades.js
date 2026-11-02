// nX-sig web: the trades page, served as
// /js/trades.js after /js/app.js
//
// app.js asks /api/trades for the stocks that have
// trades (with their price and gain) every interval;
// this draws them as chips. the chosen stock (its
// name in the address, e.g. /trades#SOXL) shows its
// gain and its trades, newest first; they come from
// /api/trades/<stock>, asked again only when the
// stock's number of trades or its last trade
// changed.
//
// unless config "web" "read_only" is on (the
// answers' read_only), "Add trade" opens a form
// (POST /api/trades/add) and each trade has a delete
// button (POST /api/trades/delete, after asking);
// the server checks them like the shell and its
// texts are shown.

(function () {
  "use strict";

  var $ = nx.$;
  var el = nx.el;
  var num = nx.num;
  var signed = nx.signed;
  var trend = nx.trend;
  var put = nx.put;
  var shortDate = nx.shortDate;
  var lastData = null; // the last /api/trades
  var chosen = null; // the chosen stock's name
  var detail = null; // the last /api/trades/<chosen>
  var loading = null; // the stock being asked for
  var chips = {}; // stock name -> its button
  var refresh = null; // asks /api/trades right away
  var scrolledTo = null; // the chip last scrolled to
  var TRASH = "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13" +
    "M9 7V4h6v3";

  function pctText(s) {
    return s.pct === null ? "-" : signed(s.pct, 1) + "%";
  }

  function hashName() {
    return decodeURIComponent(location.hash.slice(1))
      .toUpperCase();
  }

  // the stock to show: the address's, the one shown,
  // the first one held, the first one
  function pick(rows) {
    var names = rows.map(function (s) { return s.stock; });
    var want = hashName();
    if (names.indexOf(want) >= 0) return want;
    if (names.indexOf(chosen) >= 0) return chosen;
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].count !== 0) return rows[i].stock;
    }
    return names.length ? names[0] : null;
  }

  // ---------- the chips ----------

  function chip(s) {
    var button = chips[s.stock];
    if (!button) {
      button = el("button", "stock");
      button.type = "button";
      button.appendChild(el("b", "", s.stock));
      button.appendChild(el("span"));
      button.appendChild(el("span", "chip idle"));
      button.addEventListener("click", function () {
        choose(s.stock);
      });
      chips[s.stock] = button;
    }
    var parts = button.children;
    put(parts[1], s.stock + ":held", s.count === 0
      ? "none held" : s.count + " @ " + num(s.avg, 2));
    put(parts[2], s.stock + ":pct", pctText(s));
    parts[2].className = "chip " + (trend(s.gain) || "idle");
    button.setAttribute("aria-pressed",
      String(s.stock === chosen));
    return button;
  }

  function drawChips(rows) {
    var box = $("stocks");
    var names = {};
    rows.forEach(function (s) {
      names[s.stock] = true;
      // appending again keeps the config order
      box.appendChild(chip(s));
    });
    Object.keys(chips).forEach(function (name) {
      if (!names[name]) {
        box.removeChild(chips[name]);
        delete chips[name];
      }
    });
    var count = rows.reduce(function (sum, s) {
      return sum + s.trades;
    }, 0);
    $("stocks-sub").textContent = rows.length
      ? count + (count === 1 ? " trade" : " trades") : "";
    $("no-stocks").hidden = rows.length > 0;
  }

  // ---------- the chosen stock ----------

  function drawChosen(s) {
    $("stock-name").textContent = s.stock;
    $("stock-name").href = "/chart?stock=" +
      encodeURIComponent(s.stock);
    var gain = $("stock-gain");
    put(gain, "chosen:gain", s.gain === null
      ? "-" : signed(s.gain, 2));
    gain.className = trend(s.gain);
    var pct = $("stock-pct");
    put(pct, "chosen:pct", pctText(s));
    pct.className = "chip " + (trend(s.gain) || "idle");
    var held = s.count === 0 ? "none held"
      : s.count + " held at " + num(s.avg, 2) +
        " · cost " + num(s.cost, 2);
    $("stock-sub").textContent = held + " · price " +
      num(s.price, 2);
  }

  function drawTrades() {
    var body = $("trades");
    body.textContent = "";
    // newest first
    detail.trades.slice().reverse().forEach(function (t) {
      var tr = el("tr");
      tr.appendChild(el("td", "", String(t.id)));
      tr.appendChild(el("td", "",
        shortDate(t.date) + " " + t.time));
      var type = el("td");
      type.appendChild(el("span", "side " +
        (t.type === "BUY" ? "buy" : "sell"), t.type));
      tr.appendChild(type);
      tr.appendChild(el("td", "", String(t.count)));
      tr.appendChild(el("td", "px", num(t.price, 2)));
      tr.appendChild(el("td", "wide-only",
        num(t.count * t.price, 2)));
      if (canChange()) tr.appendChild(deleteCell(t));
      body.appendChild(tr);
    });
    $("del-col").hidden = !canChange();
    var count = detail.trades.length;
    $("trades-sub").textContent =
      count + (count === 1 ? " trade" : " trades");
    $("no-trades").hidden = count > 0;
  }

  // ---------- changes ----------

  function canChange() {
    return lastData !== null && !lastData.read_only;
  }

  // after a change: the stock's trades and the chips
  // anew, now
  function changed(text, name) {
    nx.tell(text);
    detail = null;
    if (name && name !== chosen) {
      chosen = name;
      history.replaceState(null, "", "#" + name);
    }
    refresh();
  }

  function deleteCell(t) {
    var td = el("td", "act");
    var button = el("button", "del");
    button.type = "button";
    var label = "Delete trade " + t.id;
    button.setAttribute("aria-label", label);
    button.title = label;
    var svg = document.createElementNS(
      "http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    var path = document.createElementNS(
      "http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", TRASH);
    svg.appendChild(path);
    button.appendChild(svg);
    button.addEventListener("click", function () {
      remove(detail.stock.stock, t, button);
    });
    td.appendChild(button);
    return td;
  }

  // delete trade t of stock name, after asking, like
  // 'rm trade'
  function remove(name, t, button) {
    var question = "Delete " + name + " trade " + t.id +
      ": " + t.type + " " + t.count + " @ " +
      num(t.price, 2) + " on " + shortDate(t.date) +
      " " + t.time + "?";
    if (!window.confirm(question)) return;
    button.disabled = true;
    nx.send("/api/trades/delete", { stock: name, id: t.id })
      .then(function (result) {
        changed(result.text, name);
      })
      .catch(function (error) {
        button.disabled = false;
        nx.tell("not deleted: " +
          (error.message || error), true);
      });
  }

  // "2026-09-02" (a date input) -> "02.09.2026"
  function dotDate(value) {
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value);
    return m ? m[3] + "." + m[2] + "." + m[1] : value;
  }

  function openForm() {
    var select = $("f-stock");
    select.textContent = "";
    lastData.names.forEach(function (name) {
      var option = el("option", "", name);
      option.value = name;
      select.appendChild(option);
    });
    select.value = chosen || lastData.names[0];
    $("f-buy").checked = true;
    ["f-count", "f-price", "f-date", "f-time"].forEach(
      function (id) { $(id).value = ""; });
    $("f-error").hidden = true;
    $("add").hidden = false;
    $("add-open").setAttribute("aria-expanded", "true");
    $("f-count").focus();
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
    var count = $("f-count").value.trim();
    var price = $("f-price").value.trim();
    // an input of type number gives "" for what
    // isn't a number
    if (!count || !price) {
      formError("give the count and the price");
      return;
    }
    var change = {
      stock: $("f-stock").value,
      type: form.elements.type.value,
      count: Number(count),
      price: Number(price)
    };
    var date = $("f-date").value;
    var time = $("f-time").value;
    if (date || time) {
      change.date = dotDate(date);
      change.time = time;
    }
    $("f-submit").disabled = true;
    nx.send("/api/trades/add", change)
      .then(function (result) {
        $("f-submit").disabled = false;
        closeForm();
        changed(result.text, change.stock);
      })
      .catch(function (error) {
        $("f-submit").disabled = false;
        formError(error.message || error);
      });
  }

  $("add-open").addEventListener("click", function () {
    if ($("add").hidden) openForm(); else closeForm();
  });
  $("f-cancel").addEventListener("click", closeForm);
  $("add-form").addEventListener("submit", submit);

  // the trades of the chosen stock are out of date
  function stale(s) {
    if (!detail || detail.stock.stock !== s.stock) {
      return true;
    }
    var had = detail.stock;
    return had.trades !== s.trades ||
      (had.last && had.last.id) !== (s.last && s.last.id);
  }

  function load(name) {
    if (loading === name) return;
    loading = name;
    fetch("/api/trades/" + encodeURIComponent(name),
      { cache: "no-store" })
      .then(nx.answer)
      .then(function (data) {
        loading = null;
        // another stock was chosen meanwhile
        if (data.stock.stock !== chosen) return;
        detail = data;
        drawTrades();
      })
      .catch(function (error) {
        loading = null;
        nx.showNotice("Trades not loaded.",
          String(error.message || error) + ".");
      });
  }

  function choose(name) {
    if (name === chosen) return;
    chosen = name;
    // keep it in the address, without a new history
    // entry for every chip
    history.replaceState(null, "", "#" + name);
    if (lastData) draw(lastData);
  }

  function draw(data) {
    var wasReadOnly = lastData && lastData.read_only;
    lastData = data;
    var rows = data.stocks;
    chosen = pick(rows);
    drawChips(rows);
    $("add-open").hidden = data.read_only;
    if (data.read_only) closeForm();
    if (data.read_only) {
      $("stocks-sub").textContent +=
        (rows.length ? " · " : "") + "read-only";
    }
    var s = rows.filter(function (row) {
      return row.stock === chosen;
    })[0];
    $("chosen").hidden = !s;
    if (!s) return;
    if (scrolledTo !== s.stock) {
      // a new chip goes in front of the others: keep
      // the chosen one in sight (only when it changes,
      // not against the user's scrolling)
      chips[s.stock].scrollIntoView(
        { block: "nearest", inline: "nearest" });
      scrolledTo = s.stock;
    }
    drawChosen(s);
    if (detail && detail.stock.stock !== s.stock) {
      // another stock: don't show the old one's trades
      $("trades").textContent = "";
      $("trades-sub").textContent = "";
      $("no-trades").hidden = true;
    }
    if (stale(s)) {
      load(s.stock);
    } else if (wasReadOnly !== data.read_only) {
      // the delete buttons come or go
      drawTrades();
    }
  }

  window.addEventListener("hashchange", function () {
    var name = hashName();
    if (chips[name]) choose(name);
  });

  refresh = nx.poll("/api/trades", draw);
})();
