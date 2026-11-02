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

(function () {
  "use strict";

  var $ = nx.$;
  var el = nx.el;
  var num = nx.num;
  var signed = nx.signed;
  var trend = nx.trend;
  var lastData = null; // the last /api/trades
  var chosen = null; // the chosen stock's name
  var detail = null; // the last /api/trades/<chosen>
  var loading = null; // the stock being asked for
  var chips = {}; // stock name -> its button
  var shown = {}; // key -> text, to flash changes

  // set a node's text; flash it when it changed
  function put(node, key, text) {
    node.textContent = text;
    if (key in shown && shown[key] !== text) {
      node.classList.remove("flash");
      void node.offsetWidth; // restart the animation
      node.classList.add("flash");
    }
    shown[key] = text;
  }

  // "02.09.2026" -> "02.09.26", as the shell
  function shortDate(date) {
    return date.length === 10
      ? date.slice(0, 6) + date.slice(-2) : date;
  }

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
      body.appendChild(tr);
    });
    var count = detail.trades.length;
    $("trades-sub").textContent =
      count + (count === 1 ? " trade" : " trades");
    $("no-trades").hidden = count > 0;
  }

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
      .then(function (response) {
        return response.json().catch(function () {
          return {};
        }).then(function (body) {
          if (!response.ok) {
            throw new Error(body.error ||
              "the server answered " + response.status);
          }
          return body;
        });
      })
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
    lastData = data;
    var rows = data.stocks;
    chosen = pick(rows);
    drawChips(rows);
    var s = rows.filter(function (row) {
      return row.stock === chosen;
    })[0];
    $("chosen").hidden = !s;
    if (!s) return;
    drawChosen(s);
    if (detail && detail.stock.stock !== s.stock) {
      // another stock: don't show the old one's trades
      $("trades").textContent = "";
      $("trades-sub").textContent = "";
      $("no-trades").hidden = true;
    }
    if (stale(s)) load(s.stock);
  }

  window.addEventListener("hashchange", function () {
    var name = hashName();
    if (chips[name]) choose(name);
  });

  nx.poll("/api/trades", draw);
})();
