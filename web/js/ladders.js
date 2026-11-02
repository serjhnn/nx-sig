// nX-sig web: the ladders page, served as
// /js/ladders.js after /js/app.js
//
// app.js asks /api/ladders every interval; this draws
// a card per saved ladder: its stock, "down 1 from
// 35", its state, the next level and how far the price
// still has to move to it, and a picture of the rungs
// (the last level, the next three) with the price as
// a dot. A card is made once and only its texts
// change, so nothing jumps while the page updates.

(function () {
  "use strict";

  var $ = nx.$;
  var el = nx.el;
  var num = nx.num;
  var put = nx.put;
  var cards = {}; // ladder id -> its card's parts

  var STATE_CHIP = {
    running: "up",
    crashed: "down",
    stopped: "idle",
    done: "idle"
  };

  // a step as the shell writes it: 1, 2.5, 0.25
  function g(value) {
    return String(Number(value.toFixed(6)));
  }

  // ---------- the rungs ----------

  // the levels as ticks on a line, low prices left;
  // the price as a dot, at an end with an arrow when
  // it is beyond the levels
  function drawRungs(box, l) {
    box.textContent = "";
    if (!l.levels.length) return;
    var values = [l.last].concat(l.levels);
    var low = Math.min.apply(null, values) - l.step / 2;
    var high = Math.max.apply(null, values) + l.step / 2;
    function at(value) {
      return (value - low) / (high - low) * 100;
    }
    var line = el("div", "rungs-line");
    box.appendChild(line);
    values.forEach(function (value, i) {
      var cls = i === 0 ? "tick sent" : i === 1 ? "tick next" : "tick";
      var tick = el("i", cls);
      tick.style.left = at(value) + "%";
      tick.appendChild(el("span", "", num(value, 2)));
      line.appendChild(tick);
    });
    if (l.price !== null) {
      var where = at(l.price);
      var dot = el("i", "dot-price");
      var label = num(l.price, 2);
      if (where < 0) {
        where = 0;
        label = "‹ " + label;
        dot.classList.add("off");
      } else if (where > 100) {
        where = 100;
        label = label + " ›";
        dot.classList.add("off");
      }
      dot.style.left = where + "%";
      dot.appendChild(el("span", "", label));
      line.appendChild(dot);
    }
  }

  // ---------- a card ----------

  function card(l) {
    var c = cards[l.id];
    if (c) return c;
    c = { box: el("article", "ladder") };
    var head = el("div", "ladder-h");
    c.stock = el("b");
    c.what = el("span", "what");
    c.state = el("span", "chip idle");
    head.appendChild(c.stock);
    head.appendChild(c.what);
    head.appendChild(c.state);
    c.box.appendChild(head);
    var next = el("div", "ladder-next");
    c.next = el("span");
    c.away = el("span");
    next.appendChild(c.next);
    next.appendChild(c.away);
    c.box.appendChild(next);
    c.rungs = el("div", "rungs");
    c.rungs.setAttribute("aria-hidden", "true");
    c.box.appendChild(c.rungs);
    c.foot = el("div", "ladder-foot");
    c.box.appendChild(c.foot);
    cards[l.id] = c;
    return c;
  }

  function awayText(l) {
    if (l.next === null) return "";
    if (l.price === null) return "no price";
    if (l.away <= 0) {
      return l.state === "running"
        ? "price at the level" : "price past the level";
    }
    return num(l.away, 2) + " to go (" +
      num(l.away_pct, 1) + "%)";
  }

  function drawCard(l) {
    var c = card(l);
    var k = l.id + ":";
    c.box.setAttribute("aria-label", "Ladder " + l.id + ", " +
      l.stock + " " + l.direction + " " + g(l.step));
    c.stock.textContent = l.stock;
    c.what.textContent = l.direction + " " + g(l.step) +
      " from " + g(l.from);
    c.state.textContent = l.state;
    c.state.className = "chip " + (STATE_CHIP[l.state] || "idle");
    put(c.next, k + "next", l.next === null
      ? "no level left" : "next " + num(l.next, 2));
    put(c.away, k + "away", awayText(l));
    c.away.className = l.away !== null && l.away <= 0
      ? "chip warn" : "muted";
    // a done ladder: nothing to draw
    c.rungs.hidden = !l.levels.length;
    drawRungs(c.rungs, l);
    var sent = l.last === l.from ? "none sent yet"
      : "last sent " + num(l.last, 2);
    c.foot.textContent = "#" + l.id + " · " + sent +
      " · since " + nx.shortDate(l.created.split(" ")[0]);
    return c.box;
  }

  function draw(data) {
    var box = $("ladders");
    var ids = {};
    data.ladders.forEach(function (l) {
      ids[l.id] = true;
      // appending again keeps the id order
      box.appendChild(drawCard(l));
    });
    Object.keys(cards).forEach(function (id) {
      if (!ids[id]) {
        box.removeChild(cards[id].box);
        delete cards[id];
      }
    });
    var running = data.ladders.filter(function (l) {
      return l.state === "running";
    }).length;
    var count = data.ladders.length;
    $("ladders-sub").textContent = count
      ? count + (count === 1 ? " ladder" : " ladders") +
        " · " + running + " running"
      : "";
    $("no-ladders").hidden = count > 0;
  }

  nx.poll("/api/ladders", draw);
})();
