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
// point. The stocks and periods are in the address
// (/chart?stock=TSMX&days=30&stock=SOXL&days=5, a
// pair per chart); without a known stock it is
// the first one held (/api/trades), else the first
// of the config. Redrawn when the width changes.
//
// each chart is a Chart, made from the page's
// #chart-tpl: its own stock, period, data, tip and
// polling, its parts found by data-part; the page
// keeps them in charts, in the order shown. "Add
// chart" adds one (the next held stock not shown,
// the period of the last chart), at most MAX_CHARTS;
// each has a close button while there are several.

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
  var MAX_CHARTS = 4;
  var charts = []; // the charts shown, a Chart each
  var stocks = null; // /api/trades: names and stocks
  var count = 0; // the charts made, for unique names

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
  function dateLabel(d, span, days) {
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
  function tipDate(p, timeframe) {
    var text = dayMonth(p.t) + "." +
      String(p.t.getFullYear()).slice(-2);
    if (p.live) return text + " " + pad2(p.t.getHours()) +
      ":" + pad2(p.t.getMinutes()) + " now";
    if (timeframe === "1Day") return text;
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

  // ---------- a chart ----------

  // a chart of stock over days, a copy of #chart-tpl
  // put into #charts
  function Chart(stock, days) {
    count += 1;
    this.id = count;
    this.stock = stock;
    this.days = days;
    this.lastData = null; // the last /api/chart
    this.refresh = null; // asks /api/chart right away
    this.shown = null; // the drawn chart, for the tip
    this.tipAt = null; // the point the tip shows
    this.width = null; // the plot's width drawn at
    this.root = document.importNode(
      $("chart-tpl").content, true
    ).querySelector(".chart");
    this.link();
    $("charts").appendChild(this.root);
  }

  // the part of the chart named name (data-part)
  Chart.prototype.part = function (name) {
    return this.root.querySelector(
      '[data-part="' + name + '"]'
    );
  };

  // the period inputs of this chart
  Chart.prototype.periods = function () {
    return this.part("periods").querySelectorAll("input");
  };

  // names unique to this chart (the labels, the
  // radio group) and the events of its controls
  Chart.prototype.link = function () {
    var self = this;
    var name = "c" + this.id;
    this.part("stock").id = name + "-stock";
    this.part("stock-label").htmlFor = name + "-stock";
    this.part("period-label").id = name + "-period";
    this.part("periods").setAttribute(
      "aria-labelledby", name + "-period"
    );
    this.part("stock").addEventListener("change", function () {
      self.stock = self.part("stock").value;
      self.choose();
      update();
    });
    Array.prototype.forEach.call(this.periods(), function (input) {
      input.name = name + "-days";
      input.addEventListener("change", function () {
        self.days = Number(input.value);
        self.choose();
      });
    });
    this.part("close").addEventListener("click", function () {
      closeChart(self);
    });
    var plot = this.part("plot");
    function at(event) {
      self.pointAt(event);
    }
    plot.addEventListener("pointermove", at);
    plot.addEventListener("pointerdown", at);
    plot.addEventListener("pointerleave", function (event) {
      // on a phone the tip stays until the next tap
      if (event.pointerType === "mouse") self.hideTip();
    });
  };

  // ---------- the summary above the chart ----------

  Chart.prototype.summary = function (data, points) {
    this.part("name").textContent = data.stock;
    var first = points[0];
    var last = points[points.length - 1];
    nx.put(this.part("price"), "price" + this.id,
      last ? num(last.price, 2) : "-");
    var change = null;
    if (first && last && first.price) {
      change = (last.price - first.price) / first.price * 100;
    }
    var chip = this.part("change");
    nx.put(chip, "change" + this.id, change === null
      ? "-" : nx.signed(change, 2) + "%");
    chip.className = "chip " + (nx.trend(change) || "idle");
    this.part("info").textContent = data.label + " bars" +
      (data.avg !== null ? " · avg " + num(data.avg, 2) : "");
  };

  // ---------- the chart ----------

  Chart.prototype.drawChart = function (data, points) {
    var box = this.part("plot");
    box.textContent = "";
    this.shown = null;
    var w = box.clientWidth;
    var h = box.clientHeight;
    this.width = w;
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
      var text = dateLabel(points[i].t, span, data.days);
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
    this.shown = {
      points: points, x: x, y: y, cursor: cursor, dot: dot,
      step: n > 1 ? plotW / (n - 1) : plotW, w: w
    };
    if (this.tipAt !== null) {
      this.showTip(Math.min(this.tipAt, n - 1));
    }
  };

  // ---------- the tip ----------

  Chart.prototype.showTip = function (i) {
    var shown = this.shown;
    if (!shown) return;
    this.tipAt = i;
    var p = shown.points[i];
    var px = shown.x(i);
    shown.cursor.setAttribute("x1", px);
    shown.cursor.setAttribute("x2", px);
    shown.cursor.setAttribute("visibility", "visible");
    shown.dot.setAttribute("cx", px);
    shown.dot.setAttribute("cy", shown.y(p.price));
    shown.dot.setAttribute("visibility", "visible");
    var tip = this.part("tip");
    tip.textContent = tipDate(p, this.lastData.timeframe) +
      "  " + num(p.price, 2);
    tip.hidden = false;
    var left = px - tip.offsetWidth / 2;
    left = Math.max(0, Math.min(left, shown.w - tip.offsetWidth));
    tip.style.left = left + "px";
  };

  Chart.prototype.hideTip = function () {
    this.tipAt = null;
    this.part("tip").hidden = true;
    if (!this.shown) return;
    this.shown.cursor.setAttribute("visibility", "hidden");
    this.shown.dot.setAttribute("visibility", "hidden");
  };

  Chart.prototype.pointAt = function (event) {
    if (!this.shown) return;
    var box = this.part("plot").getBoundingClientRect();
    var i = Math.round((event.clientX - box.left - PAD.left) /
      this.shown.step);
    this.showTip(
      Math.max(0, Math.min(i, this.shown.points.length - 1))
    );
  };

  // ---------- drawing ----------

  Chart.prototype.fillPicker = function (names) {
    var select = this.part("stock");
    if (select.options.length) return;
    names.forEach(function (name) {
      var option = el("option", "", name);
      option.value = name;
      select.appendChild(option);
    });
    select.value = this.stock;
  };

  Chart.prototype.draw = function (data) {
    // an answer for the stock or period shown before
    if (data.stock !== this.stock || data.days !== this.days) {
      return;
    }
    var self = this;
    this.lastData = data;
    this.fillPicker(data.names);
    var points = series(data);
    this.summary(data, points);
    var empty = this.part("empty");
    empty.hidden = points.length > 0;
    empty.textContent = "no prices for " + data.stock +
      " in the last " + data.days + " days";
    this.part("legend").hidden = !points.length;
    this.part("lg-avg").hidden = data.avg === null;
    ["B", "S"].forEach(function (side) {
      self.part("lg-" + side.toLowerCase()).hidden =
        !data.trades.some(function (t) {
          return t.side === side;
        });
    });
    var last = points[points.length - 1];
    this.part("lg-now").hidden = !(last && last.live);
    if (!points.length) {
      this.part("plot").textContent = "";
      this.shown = null;
      this.hideTip();
      return;
    }
    this.drawChart(data, points);
  };

  // redrawn when the plot's width changed
  Chart.prototype.resize = function () {
    var now = this.part("plot").clientWidth;
    if (this.lastData && now !== this.width) {
      this.draw(this.lastData);
    }
  };

  // ---------- the stock and the period ----------

  // show stock over days: the address, the controls,
  // ask right away
  Chart.prototype.choose = function () {
    var self = this;
    saveAddress();
    this.part("stock").value = this.stock;
    Array.prototype.forEach.call(this.periods(), function (input) {
      input.checked = Number(input.value) === self.days;
    });
    this.hideTip();
    this.part("name").textContent = this.stock;
    if (this.refresh) {
      this.refresh();
    } else {
      this.refresh = nx.poll(function () {
        return "/api/chart/" + encodeURIComponent(self.stock) +
          "?days=" + self.days;
      }, function (data) {
        self.draw(data);
      });
    }
  };

  // ---------- the page ----------

  // the charts in the address, in the order shown
  function saveAddress() {
    var query = charts.map(function (one) {
      return "stock=" + encodeURIComponent(one.stock) +
        "&days=" + one.days;
    }).join("&");
    history.replaceState(null, "", "/chart?" + query);
  }

  function resizeAll() {
    charts.forEach(function (one) {
      one.resize();
    });
  }

  window.addEventListener("resize", resizeAll);

  // the stock a new chart shows: the first held one
  // not shown, else the first of the config not
  // shown; null when all are
  function nextStock() {
    var shown = charts.map(function (one) {
      return one.stock;
    });
    var held = stocks.stocks.filter(function (s) {
      return s.count !== 0;
    }).map(function (s) {
      return s.stock;
    });
    var free = held.concat(stocks.names).filter(function (name) {
      return shown.indexOf(name) < 0;
    });
    return free.length ? free[0] : null;
  }

  // the close buttons, "Add chart" and why it is
  // off, the columns; the charts redrawn when their
  // width changed
  function update() {
    var several = charts.length > 1;
    charts.forEach(function (one) {
      one.part("close").hidden = !several;
      one.root.classList.toggle("closable", several);
    });
    $("charts").classList.toggle("multi", several);
    var why = "";
    if (charts.length >= MAX_CHARTS) {
      why = "at most " + MAX_CHARTS + " charts";
    } else if (nextStock() === null) {
      why = "every stock is shown";
    }
    $("add-chart").disabled = why !== "";
    $("add-why").textContent = why;
    $("charts-foot").hidden = false;
    resizeAll();
  }

  function addChart(stock, days) {
    var chart = new Chart(stock, days);
    charts.push(chart);
    chart.choose();
    update();
    return chart;
  }

  function closeChart(chart) {
    if (charts.length < 2) return;
    if (chart.refresh) chart.refresh.stop();
    chart.root.remove();
    charts.splice(charts.indexOf(chart), 1);
    saveAddress();
    update();
  }

  $("add-chart").addEventListener("click", function () {
    var stock = nextStock();
    if (stock === null || charts.length >= MAX_CHARTS) return;
    var last = charts[charts.length - 1];
    var chart = addChart(stock, last ? last.days : 5);
    chart.root.scrollIntoView({ block: "nearest" });
  });

  // days of the address as a number; missing or
  // not 1 to 1825: 5
  function toDays(text) {
    var days = Number(text);
    var fine = Number.isInteger(days) && days >= 1 &&
      days <= 1825;
    return fine ? days : 5;
  }

  // the charts of the address with a stock of the
  // config, a stock and days each, in pairs
  // (?stock=TSMX&days=30&stock=SOXL&days=5), at most
  // MAX_CHARTS; none: the first stock held, else the
  // first of the config, with the first days
  function start(found) {
    var query = new URLSearchParams(location.search);
    var all = query.getAll("days");
    var known = query.getAll("stock").map(function (name, i) {
      return { stock: name.toUpperCase(), days: toDays(all[i]) };
    }).filter(function (one) {
      return found.names.indexOf(one.stock) >= 0;
    }).slice(0, MAX_CHARTS);
    if (!known.length) {
      var held = found.stocks.filter(function (s) {
        return s.count !== 0;
      })[0];
      known = [{
        stock: held ? held.stock : found.names[0],
        days: toDays(all[0])
      }];
    }
    known.forEach(function (one) {
      addChart(one.stock, one.days);
    });
  }

  fetch("/api/trades", { cache: "no-store" })
    .then(nx.answer)
    .then(function (found) {
      // /api/trades: the stocks that have trades
      stocks = found;
      start(found);
    })
    .catch(function (error) {
      nx.showNotice(error.status === 403
        ? "Positions not shown." : "Can't reach the server.",
        String(error.message || error) + ".");
    });
})();
