// nX-sig web: the main page, served as /js/main.js
// after /js/app.js
//
// draws /api/status: the total, the positions, the
// background tasks and the last trades; app.js asks
// for it and changes only the numbers, no reload.

(function () {
  "use strict";

  var $ = nx.$;
  var el = nx.el;
  var num = nx.num;
  var signed = nx.signed;
  var trend = nx.trend;
  var dayTime = nx.dayTime;
  var last = {}; // cell key -> text, to flash changes

  // ---------- drawing ----------

  // a table cell; flash it when its text changed
  function cell(row, key, text, cls) {
    var td = el("td", cls, text);
    if (key in last && last[key] !== text) {
      td.classList.add("flash");
    }
    last[key] = text;
    row.appendChild(td);
    return td;
  }

  function drawTotal(data) {
    var total = data.total;
    var priced = data.positions.some(function (p) {
      return p.gain !== null;
    });
    var t = $("total");
    var pct = $("total-pct");
    if (!priced) {
      t.textContent = "-";
      t.className = "";
      pct.textContent = "-";
      pct.className = "chip idle";
      $("total-sub").textContent = data.positions.length
        ? "waiting for prices" : "no stocks held";
      return;
    }
    t.textContent = signed(total.gain, 2);
    t.className = trend(total.gain);
    pct.textContent = total.pct === null
      ? "-" : signed(total.pct, 2) + "%";
    pct.className = "chip " + (trend(total.gain) || "idle");
    var value = data.positions.reduce(function (sum, p) {
      return p.price === null ? sum : sum + p.count * p.price;
    }, 0);
    $("total-sub").textContent = "cost " + num(total.cost, 2) +
      " · value " + num(value, 2);
  }

  function drawPositions(data) {
    var body = $("positions");
    var rows = data.positions;
    var most = rows.reduce(function (m, p) {
      return p.pct === null ? m : Math.max(m, Math.abs(p.pct));
    }, 0);
    body.textContent = "";
    rows.forEach(function (p) {
      var tr = el("tr");
      var k = p.stock + ":";
      tr.appendChild(el("td", "key", p.stock));
      cell(tr, k + "count", String(p.count));
      cell(tr, k + "avg", num(p.avg, 2));
      cell(tr, k + "price", num(p.price, 2), "px");
      cell(tr, k + "gain", signed(p.gain, 2), trend(p.gain));
      cell(tr, k + "pct", p.pct === null
        ? "-" : signed(p.pct, 1), trend(p.gain));
      var barCell = el("td", "wide-only");
      if (p.pct !== null && most > 0) {
        var bar = el("div", "gbar");
        var fill = el("i", trend(p.gain));
        fill.style.width =
          Math.round(Math.abs(p.pct) / most * 100) + "%";
        bar.appendChild(fill);
        barCell.appendChild(bar);
      }
      tr.appendChild(barCell);
      body.appendChild(tr);
    });
    if (rows.length) {
      var sum = el("tr", "sum");
      var g = data.total.gain;
      var priced = rows.some(function (p) {
        return p.gain !== null;
      });
      sum.appendChild(el("td", "", "Total"));
      sum.appendChild(el("td"));
      sum.appendChild(el("td"));
      sum.appendChild(el("td"));
      cell(sum, "total:gain", priced ? signed(g, 2) : "-",
        trend(g));
      cell(sum, "total:pct", data.total.pct === null
        ? "-" : signed(data.total.pct, 1), trend(g));
      sum.appendChild(el("td", "wide-only"));
      body.appendChild(sum);
    }
    $("no-positions").hidden = rows.length > 0;

    $("kpi-count").textContent = String(rows.length);
    var best = null;
    rows.forEach(function (p) {
      if (p.pct !== null && (!best || p.pct > best.pct)) {
        best = p;
      }
    });
    $("kpi-best").textContent = best ? best.stock : "-";
    $("kpi-best").className = "kpi " + (best ? trend(best.pct) : "");
  }

  function taskItem(dotClass, title, detail, chipClass, chip) {
    var li = el("li");
    li.appendChild(el("span", "dot " + dotClass));
    var text = el("div");
    text.appendChild(el("div", "t", title));
    text.appendChild(el("div", "d", detail));
    li.appendChild(text);
    li.appendChild(el("span", "chip " + chipClass, chip));
    return li;
  }

  var MAIL_WORDS = {
    "not started": "see 'run mail-broker'",
    "stopped": "stopped",
    "no reply": "not responding",
    "unknown": "unknown state"
  };

  function drawTasks(data) {
    var list = $("tasks");
    list.textContent = "";
    var mailRow = false;
    data.tasks.forEach(function (t) {
      var detail = "pid " + t.pid;
      if (t.started) detail += ", since " + dayTime(t.started);
      if (t.task === "mail-broker") {
        mailRow = true;
        if (data.mail_broker.last_order) {
          detail = "last order " + data.mail_broker.last_order;
        }
      }
      list.appendChild(taskItem(
        t.healthy ? "" : "warn", t.task, detail,
        t.healthy ? "up" : "down", t.state
      ));
    });
    var mail = data.mail_broker;
    if (!mailRow && mail.state !== "demo") {
      var word = MAIL_WORDS[mail.state] || mail.state;
      var when = mail.updated ? "last seen " + dayTime(mail.updated)
        : "not running";
      list.appendChild(taskItem(
        "off", "mail-broker", when, "idle", word
      ));
    }
    if (mail.error) {
      list.appendChild(taskItem(
        "warn", "mail broker error",
        dayTime(mail.error.time) + ": " + mail.error.text,
        "down", "error"
      ));
    }
    if (!list.children.length) {
      list.appendChild(taskItem(
        "off", "no background tasks running",
        "see 'ls tasks' in the shell", "idle", "-"
      ));
    }
    var owner = $("owner");
    if (data.owner) {
      owner.textContent = "background tasks run " +
        (data.owner.here ? "here (" + data.owner.name + ")"
          : "on " + data.owner.name);
      owner.hidden = false;
    } else {
      owner.hidden = true;
    }
    $("kpi-tasks").textContent = String(data.tasks.length);
  }

  function drawTrades(data) {
    var list = $("trades");
    list.textContent = "";
    data.last_trades.forEach(function (t) {
      var li = el("li");
      var side = t.type === "BUY" ? "buy" : "sell";
      li.appendChild(el("span", "side " + side, t.type));
      var text = el("div");
      text.appendChild(el("div", "t", t.stock + " · " + t.count));
      text.appendChild(el("div", "d", t.date + " " + t.time));
      li.appendChild(text);
      li.appendChild(el("span", "r px", num(t.price, 2)));
      list.appendChild(li);
    });
    $("no-trades").hidden = data.last_trades.length > 0;
  }

  function draw(data) {
    drawTotal(data);
    drawPositions(data);
    drawTasks(data);
    drawTrades(data);
  }

  nx.poll("/api/status", draw);
})();
