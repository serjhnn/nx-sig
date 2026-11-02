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
//
// unless config "web" "read_only" is on, "Add
// basetrade" opens a form (a stock, from its trades
// or a price and count, filled in with its lowest buy
// since the last sell; POST /api/basetrades/add),
// "All from trades" sets every stock's from its
// trades and each card has Delete (both after
// asking; POST /api/basetrades/add with "all",
// /api/basetrades/delete). The server checks them
// like the shell; its texts are shown.

(function () {
  "use strict";

  var $ = nx.$;
  var el = nx.el;
  var num = nx.num;
  var put = nx.put;
  var cards = {}; // stock name -> its card's parts
  var lastData = null; // the last /api/basetrades
  var refresh = null; // asks /api/basetrades right away
  var typed = false; // price or count typed in by hand

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
    c.stock = el("b");
    c.stock.appendChild(nx.chartLink(name));
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
    c.foot = el("div", "ladder-foot");
    c.acts = el("span", "acts");
    c.del = el("button", "btn danger sm", "Delete");
    c.del.type = "button";
    c.del.addEventListener("click", function () {
      remove(name, c.del);
    });
    c.acts.appendChild(c.del);
    c.foot.appendChild(c.acts);
    c.box.appendChild(c.foot);
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
    c.foot.hidden = !canChange();
    return c.box;
  }

  // ---------- changes ----------

  function canChange() {
    return lastData !== null && !lastData.read_only;
  }

  function busy(button, text) {
    button.dataset.text = button.textContent;
    button.textContent = text;
    button.disabled = true;
  }

  function idle(button) {
    if (button.dataset.text) {
      button.textContent = button.dataset.text;
    }
    button.disabled = false;
  }

  function saved(name) {
    return lastData.basetrades.filter(function (b) {
      return b.stock === name;
    })[0];
  }

  // "30 at 28.75", as the shell
  function amount(count, price) {
    return count + " at " + String(Number(price.toFixed(6)));
  }

  // delete the basetrade of name, after asking, like
  // 'rm basetrade'
  function remove(name, button) {
    var b = saved(name);
    var what = b ? ": " + amount(b.count, b.buy) : "";
    if (!window.confirm("Delete the basetrade of " + name +
      what + "?")) return;
    busy(button, "Deleting…");
    nx.send("/api/basetrades/delete", { stock: name })
      .then(function (result) {
        nx.tell(result.text);
        refresh();
      })
      .catch(function (error) {
        idle(button);
        nx.tell("basetrade of " + name + " not deleted: " +
          (error.message || error), true);
      });
  }

  // every stock's basetrade from its trades, after
  // asking, like 'add basetrade all'
  function addAll() {
    var older = Object.keys(lastData.from_trades)
      .filter(saved);
    var question = "Set each stock's basetrade from its " +
      "lowest buy since the last sell?" + (older.length
      ? " This replaces the basetrades of " +
        older.join(", ") + "." : "");
    if (!window.confirm(question)) return;
    var button = $("all-btn");
    busy(button, "Saving…");
    nx.send("/api/basetrades/add", { stock: "all" })
      .then(function (result) {
        idle(button);
        nx.tell(result.text);
        refresh();
      })
      .catch(function (error) {
        idle(button);
        nx.tell("basetrades not set: " +
          (error.message || error), true);
      });
  }

  // ---------- the form ----------

  function fromTrades() {
    return $("f-trades").checked;
  }

  // the fields and the hint of the chosen stock and
  // source; price and count from its lowest buy
  // until typed in
  function fillForm() {
    var name = $("f-stock").value;
    var lowest = lastData.from_trades[name];
    var own = !fromTrades();
    $("f-price-field").hidden = !own;
    $("f-count-field").hidden = !own;
    if (!typed) {
      $("f-price").value = lowest ? lowest.price.toFixed(2) : "";
      $("f-count").value = lowest ? lowest.count : "";
    }
    var hint = lowest
      ? "Lowest buy since the last sell: " +
        amount(lowest.count, lowest.price) + " (" +
        nx.shortDate(lowest.date) + ")."
      : "No buy of " + name + " since the last sell.";
    var b = saved(name);
    if (b) {
      hint += " Replaces the basetrade " +
        amount(b.count, b.buy) + ".";
    }
    $("f-hint").textContent = hint;
  }

  function openForm() {
    var select = $("f-stock");
    select.textContent = "";
    lastData.names.forEach(function (name) {
      var option = el("option", "", name);
      option.value = name;
      select.appendChild(option);
    });
    typed = false;
    pickSource();
    $("f-error").hidden = true;
    $("add").hidden = false;
    $("add-open").setAttribute("aria-expanded", "true");
    select.focus();
  }

  // "the trades" when the stock has a lowest buy,
  // else price and count
  function pickSource() {
    var lowest = lastData.from_trades[$("f-stock").value];
    $(lowest ? "f-trades" : "f-own").checked = true;
    fillForm();
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
    var change = { stock: $("f-stock").value };
    if (fromTrades()) {
      change.from_trades = true;
    } else {
      var price = $("f-price").value.trim();
      var count = $("f-count").value.trim();
      // an input of type number gives "" for what
      // isn't a number
      if (!price || !count) {
        formError("give the price and the count");
        return;
      }
      change.price = Number(price);
      change.count = Number(count);
    }
    busy($("f-submit"), "Saving…");
    nx.send("/api/basetrades/add", change)
      .then(function (result) {
        idle($("f-submit"));
        closeForm();
        nx.tell(result.text);
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
  $("all-btn").addEventListener("click", addAll);
  $("f-cancel").addEventListener("click", closeForm);
  $("add-form").addEventListener("submit", submit);
  $("f-stock").addEventListener("change", function () {
    typed = false;
    pickSource();
  });
  $("f-trades").addEventListener("change", fillForm);
  $("f-own").addEventListener("change", fillForm);
  ["f-price", "f-count"].forEach(function (id) {
    $(id).addEventListener("input", function () {
      typed = true;
    });
  });

  // ---------- drawing ----------

  function draw(data) {
    lastData = data;
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
    $("acts").hidden = data.read_only;
    if (data.read_only) {
      closeForm();
    } else if (!$("add").hidden) {
      // a new basetrade or trade changes the hint
      fillForm();
    }
  }

  refresh = nx.poll("/api/basetrades", draw);
})();
