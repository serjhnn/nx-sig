// nX-sig web: the basetrades page, served as
// /js/basetrades.js after /js/app.js
//
// app.js asks /api/basetrades every interval; this
// draws a card per basetrade, like 'ls basetrades
// al': its stock, count and buying price, the
// stock's price and its change % from the buying
// price, and a line with the buying price and the
// levels of the basetrades alerts as ticks and the
// price as a dot; below it each alert, marked when
// the price reached it. A card is made once and only
// its texts change, so nothing jumps while the page
// updates.

(function () {
  "use strict";

  var $ = nx.$;
  var el = nx.el;
  var num = nx.num;
  var put = nx.put;
  var cards = {}; // stock name -> its card's parts

  // ---------- the line ----------

  // the buying price and the alert levels as ticks on
  // a line, low prices left, the price as a dot; the
  // line spans all of them with a little room
  function drawLine(box, b) {
    box.textContent = "";
    var values = [b.buy].concat(b.alerts.map(function (a) {
      return a.level;
    }));
    if (b.price !== null) values.push(b.price);
    var low = Math.min.apply(null, values);
    var high = Math.max.apply(null, values);
    var room = (high - low) * 0.08 || b.buy * 0.05 || 1;
    low -= room;
    high += room;
    function at(value) {
      return (value - low) / (high - low) * 100;
    }
    var line = el("div", "rungs-line");
    box.appendChild(line);
    b.alerts.forEach(function (a) {
      var tick = el("i", a.reached ? "tick reached" : "tick");
      tick.style.left = at(a.level) + "%";
      tick.appendChild(el("span", "", num(a.level, 2)));
      line.appendChild(tick);
    });
    var buy = el("i", "tick next");
    buy.style.left = at(b.buy) + "%";
    buy.appendChild(el("span", "", num(b.buy, 2)));
    line.appendChild(buy);
    if (b.price !== null) {
      var dot = el("i", "dot-price");
      dot.style.left = at(b.price) + "%";
      dot.appendChild(el("span", "", num(b.price, 2)));
      line.appendChild(dot);
    }
  }

  // ---------- a card ----------

  function card(name) {
    var c = cards[name];
    if (c) return c;
    c = { box: el("article", "ladder basetrade") };
    var head = el("div", "ladder-h");
    c.stock = el("b", "", name);
    c.what = el("span", "what");
    c.change = el("span", "chip idle");
    head.appendChild(c.stock);
    head.appendChild(c.what);
    head.appendChild(c.change);
    c.box.appendChild(head);
    var now = el("div", "ladder-next");
    c.price = el("span");
    c.away = el("span", "muted");
    now.appendChild(c.price);
    now.appendChild(c.away);
    c.box.appendChild(now);
    c.line = el("div", "rungs");
    c.line.setAttribute("aria-hidden", "true");
    c.box.appendChild(c.line);
    c.alerts = el("div", "bt-alerts");
    c.box.appendChild(c.alerts);
    cards[name] = c;
    return c;
  }

  function drawAlerts(box, b) {
    box.textContent = "";
    if (!b.alerts.length) {
      box.appendChild(el("span", "muted",
        "no basetrades alerts"));
      return;
    }
    b.alerts.forEach(function (a) {
      var chip = el("span", a.reached ? "chip warn" : "chip idle",
        a.text + " · " + num(a.level, 2) +
        (a.reached ? " · reached" : ""));
      chip.title = "alert " + a.id;
      box.appendChild(chip);
    });
  }

  function drawCard(b) {
    var c = card(b.stock);
    var k = b.stock + ":";
    c.box.setAttribute("aria-label", "Basetrade " + b.stock);
    c.what.textContent = b.count + " @ " + num(b.buy, 2);
    put(c.change, k + "change", b.change_pct === null
      ? "-" : nx.signed(b.change_pct, 2) + "%");
    var trend = nx.trend(b.change_pct);
    c.change.className = "chip " + (trend || "idle");
    put(c.price, k + "price", b.price === null
      ? "no price" : "price " + num(b.price, 2));
    c.price.className = trend;
    c.away.textContent = "cost " + num(b.buy * b.count, 2);
    drawLine(c.line, b);
    drawAlerts(c.alerts, b);
    return c.box;
  }

  // ---------- drawing ----------

  function draw(data) {
    var box = $("basetrades");
    var names = {};
    data.basetrades.forEach(function (b) {
      names[b.stock] = true;
      // appending again keeps the config order
      box.appendChild(drawCard(b));
    });
    Object.keys(cards).forEach(function (name) {
      if (!names[name]) {
        box.removeChild(cards[name].box);
        delete cards[name];
      }
    });
    var count = data.basetrades.length;
    $("basetrades-sub").textContent = (count
      ? count + (count === 1 ? " basetrade" : " basetrades")
      : "") + (data.read_only
      ? (count ? " · " : "") + "read-only" : "");
    $("no-basetrades").hidden = count > 0;
  }

  nx.poll("/api/basetrades", draw);
})();
