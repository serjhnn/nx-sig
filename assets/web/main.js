// nX-sig web: the main page, served as /main.js
//
// asks /api/status every "interval" seconds (the
// server's config "web" "interval") and changes only
// the numbers, no reload; pauses while the tab is
// hidden. on an error it keeps the last values and
// says what went wrong. the theme button switches
// dark and light, kept in localStorage.

(function () {
  "use strict";

  var THEME_KEY = "nx-theme";
  var MINUS = "−";
  var timer = null;
  var last = {}; // cell key -> text, to flash changes
  var lastData = null;

  function $(id) {
    return document.getElementById(id);
  }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) {
      node.textContent = text;
    }
    return node;
  }

  // ---------- numbers and times ----------

  function num(value, digits) {
    if (value === null || value === undefined) return "-";
    return value.toFixed(digits);
  }

  function signed(value, digits) {
    if (value === null || value === undefined) return "-";
    var text = Math.abs(value).toFixed(digits);
    if (Number(text) === 0) return text;
    return (value < 0 ? MINUS : "+") + text;
  }

  function trend(value) {
    if (value === null || value === undefined) return "";
    if (value > 0) return "up";
    if (value < 0) return "down";
    return "";
  }

  function pad(n) {
    return (n < 10 ? "0" : "") + n;
  }

  // "2026-11-02T14:30:05" -> Date (local time, as sent)
  function parse(iso) {
    if (!iso) return null;
    var m = /^(\d+)-(\d+)-(\d+)T(\d+):(\d+):(\d+)/.exec(iso);
    if (!m) return null;
    return new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5], +m[6]);
  }

  function clock(iso) {
    var d = parse(iso);
    if (!d) return "-";
    return pad(d.getHours()) + ":" + pad(d.getMinutes()) +
      ":" + pad(d.getSeconds());
  }

  function dayTime(iso) {
    var d = parse(iso);
    if (!d) return "-";
    return pad(d.getDate()) + "." + pad(d.getMonth() + 1) +
      " " + pad(d.getHours()) + ":" + pad(d.getMinutes());
  }

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

  function setLive(state, text) {
    $("live-dot").className = "dot " + state;
    $("live-text").textContent = text;
  }

  function showNotice(title, text) {
    $("notice-title").textContent = title;
    // the server's texts start lowercase, like the
    // shell's
    $("notice-text").textContent =
      text.charAt(0).toUpperCase() + text.slice(1);
    $("notice").hidden = false;
  }

  function draw(data) {
    lastData = data;
    $("demo").hidden = !data.demo;
    drawTotal(data);
    drawPositions(data);
    drawTasks(data);
    drawTrades(data);
    if (data.error) {
      setLive("warn", data.updated ? clock(data.updated) : "no prices");
      showNotice(
        "Prices not updated.",
        data.error + (data.updated
          ? ". Showing the prices from " + clock(data.updated) + "."
          : ".")
      );
    } else if (data.updated) {
      setLive("", clock(data.updated));
      $("notice").hidden = true;
    } else {
      setLive("off", "waiting for prices");
      $("notice").hidden = true;
    }
  }

  // ---------- asking the server ----------

  // the server said no (403), failed (500) or
  // can't be reached (it stopped, no network)
  function failed(error) {
    var title = "Can't reach the server.";
    if (error.status === 403) {
      title = "Positions not shown.";
    } else if (error.status) {
      title = "Server error.";
    }
    var text = String(error.message || error);
    setLive("warn", lastData && lastData.updated
      ? clock(lastData.updated) : "no data");
    showNotice(title, text + "." +
      (lastData ? " Showing the last values." : ""));
  }

  function next(seconds) {
    clearTimeout(timer);
    if (!document.hidden) {
      timer = setTimeout(poll, Math.max(1, seconds) * 1000);
    }
  }

  function poll() {
    var interval = lastData ? lastData.interval : 5;
    fetch("/api/status", { cache: "no-store" })
      .then(function (response) {
        return response.json().catch(function () {
          return {};
        }).then(function (body) {
          if (!response.ok) {
            var error = new Error(body.error ||
              "the server answered " + response.status);
            error.status = response.status;
            throw error;
          }
          return body;
        });
      })
      .then(function (data) {
        draw(data);
        // the first prices come a moment after the
        // first ask: ask again soon
        next(data.updated ? data.interval : 1);
      })
      .catch(function (error) {
        failed(error);
        next(interval);
      });
  }

  document.addEventListener("visibilitychange", function () {
    clearTimeout(timer);
    if (!document.hidden) poll();
  });

  // ---------- theme ----------

  $("theme").addEventListener("click", function () {
    var root = document.documentElement;
    var current = root.dataset.theme;
    var dark = current
      ? current === "dark"
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    var chosen = dark ? "light" : "dark";
    root.dataset.theme = chosen;
    try {
      localStorage.setItem(THEME_KEY, chosen);
    } catch (e) {}
  });

  poll();
})();
