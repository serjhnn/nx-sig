// nX-sig web: the chart page, served as /js/chart.js
// after /js/app.js
//
// the price of a stock over a period, like 'chart
// <stock> period <n> days': app.js asks
// /api/chart/<stock>?days=<n> every interval (the
// server keeps the bars a minute, so new bars come
// in by themselves) and this draws them as a line in
// an SVG: the average buy price as a dashed line, the
// trades as B / S marks, a few price and date labels
// and the cached price as the last point. A tap or
// hover shows the date and price of the nearest
// point. The stock and the period are in the address
// (/chart?stock=TSMX&days=30); without a stock it is
// the first one held (/api/trades), else the first
// of the config. Redrawn when the width changes.

(function () {
  "use strict";

  var $ = nx.$;
  var el = nx.el;
  var num = nx.num;
  var SVG = "http://www.w3.org/2000/svg";
  // the room around the line: the price labels right,
  // the dates below
  var PAD = { left: 4, right: 52, top: 12, bottom: 24 };
  // about how wide a date label is, with a gap
  var DATE_ROOM = 72;
  var stock = null; // the stock shown
  var days = 5; // the period shown
  var lastData = null; // the last /api/chart
  var refresh = null; // asks /api/chart right away
  var shown = null; // the drawn chart, for the tip
  var tipAt = null; // the point the tip shows

  function make(tag, attrs, text) {
    var node = document.createElementNS(SVG, tag);
    Object.keys(attrs).forEach(function (k) {
      node.setAttribute(k, attrs[k]);
    });
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function pad2(n) {
    return (n < 10 ? "0" : "") + n;
  }

  // "2026-10-12T14:30:00" -> Date, local as sent
  function parse(iso) {
    var m = /^(\d+)-(\d+)-(\d+)T(\d+):(\d+)/.exec(iso || "");
    if (!m) return null;
    return new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5]);
  }

  function dayMonth(d) {
    return pad2(d.getDate()) + "." + pad2(d.getMonth() + 1);
  }

  // a date under the chart: "12.10", "10.26" (month
  // and year) for a long period, "14:30" within a day
  function dateLabel(d, span) {
    if (days > 180) {
      return pad2(d.getMonth() + 1) + "." +
        String(d.getFullYear()).slice(-2);
    }
    if (span < 1) {
      return pad2(d.getHours()) + ":" + pad2(d.getMinutes());
    }
    return dayMonth(d);
  }

  // the tip's date: with the time unless daily bars
  function tipDate(p) {
    var text = dayMonth(p.t) + "." +
      String(p.t.getFullYear()).slice(-2);
    if (p.live) return text + " " + pad2(p.t.getHours()) +
      ":" + pad2(p.t.getMinutes()) + " now";
    if (lastData.timeframe === "1Day") return text;
    return text + " " + pad2(p.t.getHours()) + ":" +
      pad2(p.t.getMinutes());
  }

  // the points, oldest first, with the cached price
  // as the last one when it is newer
  function series(data) {
    var points = data.points.map(function (p) {
      return { t: parse(p[0]), price: p[1] };
    });
    var updated = parse(data.updated);
    var last = points[points.length - 1];
    if (last && data.price !== null && updated &&
        updated > last.t) {
      points.push({ t: updated, price: data.price, live: true });
    }
    return points;
  }

  // the index of the point nearest in time to t
  function nearest(points, t) {
    var best = 0;
    points.forEach(function (p, i) {
      if (Math.abs(p.t - t) < Math.abs(points[best].t - t)) {
        best = i;
      }
    });
    return best;
  }

  // ---------- the summary above the chart ----------

  function summary(data, points) {
    $("c-name").textContent = data.stock;
    var first = points[0];
    var last = points[points.length - 1];
    nx.put($("c-price"), "price", last ? num(last.price, 2) : "-");
    var change = null;
    if (first && last && first.price) {
      change = (last.price - first.price) / first.price * 100;
    }
    var chip = $("c-change");
    nx.put(chip, "change", change === null
      ? "-" : nx.signed(change, 2) + "%");
    chip.className = "chip " + (nx.trend(change) || "idle");
    $("c-info").textContent = data.label + " bars" +
      (data.avg !== null ? " · avg " + num(data.avg, 2) : "");
  }

  // ---------- the chart ----------

  function drawChart(data, points) {
    var box = $("plot");
    box.textContent = "";
    shown = null;
    var w = box.clientWidth;
    var h = box.clientHeight;
    var n = points.length;
    var trades = data.trades.map(function (t) {
      return { t: parse(t.time), side: t.side, price: t.price };
    });
    var values = points.map(function (p) { return p.price; })
      .concat(trades.map(function (one) { return one.price; }));
    if (data.avg !== null) values.push(data.avg);
    var low = Math.min.apply(null, values);
    var high = Math.max.apply(null, values);
    if (high - low < 1e-9) {
      low -= 1;
      high += 1;
    }
    var room = (high - low) * 0.08;
    low -= room;
    high += room;
    var plotW = w - PAD.left - PAD.right;
    var plotH = h - PAD.top - PAD.bottom;
    // the points evenly spaced: no gaps for nights
    // and weekends
    function x(i) {
      return PAD.left + (n === 1 ? plotW / 2 : i * plotW / (n - 1));
    }
    function y(v) {
      return PAD.top + (high - v) / (high - low) * plotH;
    }
    var svg = make("svg", {
      width: w,
      height: h,
      viewBox: "0 0 " + w + " " + h,
      class: "plot-svg",
      role: "img",
      "aria-label": data.stock + " over " + data.days + " days"
    });

    // the price labels and their lines
    var taken = [];
    if (data.avg !== null) taken.push(y(data.avg));
    for (var k = 0; k <= 3; k++) {
      var value = low + room + (high - low - 2 * room) * k / 3;
      var at = y(value);
      svg.appendChild(make("line", {
        x1: PAD.left, x2: PAD.left + plotW, y1: at, y2: at,
        class: "grid"
      }));
      var free = taken.every(function (other) {
        return Math.abs(other - at) > 14;
      });
      if (free) {
        svg.appendChild(make("text", {
          x: w - PAD.right + 6, y: at + 4, class: "ylabel"
        }, num(value, 2)));
      }
    }

    // the dates, as many as fit, none twice
    var count = Math.max(2, Math.floor(plotW / DATE_ROOM));
    var span = (points[n - 1].t - points[0].t) / 864e5;
    var previous = null;
    for (k = 0; k < count && n > 1; k++) {
      var i = Math.round(k * (n - 1) / (count - 1));
      var text = dateLabel(points[i].t, span);
      if (text === previous) continue;
      previous = text;
      var anchor = k === 0 ? "start" : k === count - 1 ? "end" : "middle";
      svg.appendChild(make("text", {
        x: x(i), y: h - 6, "text-anchor": anchor, class: "xlabel"
      }, text));
    }

    // the average buy price
    if (data.avg !== null) {
      var ay = y(data.avg);
      svg.appendChild(make("line", {
        x1: PAD.left, x2: PAD.left + plotW, y1: ay, y2: ay,
        class: "avg"
      }));
      svg.appendChild(make("text", {
        x: w - PAD.right + 6, y: ay + 4, class: "ylabel avg-label"
      }, num(data.avg, 2)));
    }

    // the price: the area below it and the line
    var path = points.map(function (p, i) {
      return (i ? "L" : "M") + x(i).toFixed(1) + " " +
        y(p.price).toFixed(1);
    }).join(" ");
    if (n > 1) {
      svg.appendChild(make("path", {
        d: path + " L" + x(n - 1).toFixed(1) + " " +
          (PAD.top + plotH) + " L" + x(0).toFixed(1) + " " +
          (PAD.top + plotH) + " Z",
        class: "area"
      }));
    }
    svg.appendChild(make("path", { d: path, class: "line" }));
    var last = points[n - 1];
    svg.appendChild(make("circle", {
      cx: x(n - 1), cy: y(last.price), r: 3.5,
      class: last.live ? "last live" : "last"
    }));

    // the trades, at the point nearest in time
    trades.forEach(function (trade) {
      var tx = x(nearest(points, trade.t));
      var ty = y(trade.price);
      var g = make("g", { class: "trade " + trade.side });
      g.appendChild(make("circle", { cx: tx, cy: ty, r: 8 }));
      g.appendChild(make("text", {
        x: tx, y: ty + 4, "text-anchor": "middle"
      }, trade.side));
      svg.appendChild(g);
    });

    // what a tap or hover shows
    var cursor = make("line", {
      y1: PAD.top, y2: PAD.top + plotH, class: "cursor",
      visibility: "hidden"
    });
    var dot = make("circle", { r: 4.5, class: "cursor-dot",
      visibility: "hidden" });
    svg.appendChild(cursor);
    svg.appendChild(dot);
    box.appendChild(svg);
    shown = {
      points: points, x: x, y: y, cursor: cursor, dot: dot,
      step: n > 1 ? plotW / (n - 1) : plotW, w: w
    };
    if (tipAt !== null) showTip(Math.min(tipAt, n - 1));
  }

  // ---------- the tip ----------

  function showTip(i) {
    if (!shown) return;
    tipAt = i;
    var p = shown.points[i];
    var px = shown.x(i);
    shown.cursor.setAttribute("x1", px);
    shown.cursor.setAttribute("x2", px);
    shown.cursor.setAttribute("visibility", "visible");
    shown.dot.setAttribute("cx", px);
    shown.dot.setAttribute("cy", shown.y(p.price));
    shown.dot.setAttribute("visibility", "visible");
    var tip = $("tip");
    tip.textContent = tipDate(p) + "  " + num(p.price, 2);
    tip.hidden = false;
    var left = px - tip.offsetWidth / 2;
    left = Math.max(0, Math.min(left, shown.w - tip.offsetWidth));
    tip.style.left = left + "px";
  }

  function hideTip() {
    tipAt = null;
    $("tip").hidden = true;
    if (!shown) return;
    shown.cursor.setAttribute("visibility", "hidden");
    shown.dot.setAttribute("visibility", "hidden");
  }

  function pointAt(event) {
    if (!shown) return;
    var box = $("plot").getBoundingClientRect();
    var i = Math.round((event.clientX - box.left - PAD.left) /
      shown.step);
    showTip(Math.max(0, Math.min(i, shown.points.length - 1)));
  }

  $("plot").addEventListener("pointermove", pointAt);
  $("plot").addEventListener("pointerdown", pointAt);
  $("plot").addEventListener("pointerleave", function (event) {
    // on a phone the tip stays until the next tap
    if (event.pointerType === "mouse") hideTip();
  });

  // ---------- drawing ----------

  function fillPicker(names) {
    var select = $("c-stock");
    if (select.options.length) return;
    names.forEach(function (name) {
      var option = el("option", "", name);
      option.value = name;
      select.appendChild(option);
    });
    select.value = stock;
  }

  function draw(data) {
    // an answer for the stock or period shown before
    if (data.stock !== stock || data.days !== days) return;
    lastData = data;
    fillPicker(data.names);
    var points = series(data);
    summary(data, points);
    $("c-empty").hidden = points.length > 0;
    $("c-empty").textContent = "no prices for " + data.stock +
      " in the last " + data.days + " days";
    $("legend").hidden = !points.length;
    $("lg-avg").hidden = data.avg === null;
    ["B", "S"].forEach(function (side) {
      $("lg-" + side.toLowerCase()).hidden =
        !data.trades.some(function (t) {
          return t.side === side;
        });
    });
    var last = points[points.length - 1];
    $("lg-now").hidden = !(last && last.live);
    if (!points.length) {
      $("plot").textContent = "";
      shown = null;
      hideTip();
      return;
    }
    drawChart(data, points);
  }

  // ---------- the stock and the period ----------

  function checkPeriod() {
    Array.prototype.forEach.call(
      document.querySelectorAll('input[name="days"]'),
      function (input) {
        input.checked = Number(input.value) === days;
      }
    );
  }

  // show stock over days: the address, the controls,
  // ask right away
  function choose() {
    history.replaceState(null, "", "/chart?stock=" +
      encodeURIComponent(stock) + "&days=" + days);
    $("c-stock").value = stock;
    checkPeriod();
    hideTip();
    $("c-name").textContent = stock;
    if (refresh) {
      refresh();
    } else {
      refresh = nx.poll(function () {
        return "/api/chart/" + encodeURIComponent(stock) +
          "?days=" + days;
      }, draw);
    }
  }

  $("c-stock").addEventListener("change", function () {
    stock = $("c-stock").value;
    choose();
  });
  Array.prototype.forEach.call(
    document.querySelectorAll('input[name="days"]'),
    function (input) {
      input.addEventListener("change", function () {
        days = Number(input.value);
        choose();
      });
    }
  );

  var width = null;
  window.addEventListener("resize", function () {
    var now = $("plot").clientWidth;
    if (lastData && now !== width) {
      width = now;
      draw(lastData);
    }
  });

  // the stock and days of the address; a stock not
  // in the config, or none: the first one held, else
  // the first of the config
  var query = new URLSearchParams(location.search);
  var asked = (query.get("stock") || "").toUpperCase();
  var askedDays = Number(query.get("days"));
  if (Number.isInteger(askedDays) && askedDays >= 1 &&
      askedDays <= 1825) {
    days = askedDays;
  }
  fetch("/api/trades", { cache: "no-store" })
    .then(nx.answer)
    .then(function (found) {
      // /api/trades: the stocks that have trades
      if (found.names.indexOf(asked) >= 0) {
        stock = asked;
      } else {
        var held = found.stocks.filter(function (s) {
          return s.count !== 0;
        })[0];
        stock = held ? held.stock : found.names[0];
      }
      choose();
    })
    .catch(function (error) {
      nx.showNotice(error.status === 403
        ? "Positions not shown." : "Can't reach the server.",
        String(error.message || error) + ".");
    });
})();
