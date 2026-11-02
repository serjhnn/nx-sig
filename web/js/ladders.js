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
//
// unless config "web" "read_only" is on, "Add ladder"
// opens a form (POST /api/ladders/add, "from" filled
// with the stock's price) and each card has Run or
// Stop and Delete (after asking; POST
// /api/ladders/run, stop, delete). The server checks
// them like the shell; its texts are shown.

(function () {
  "use strict";

  var $ = nx.$;
  var el = nx.el;
  var num = nx.num;
  var put = nx.put;
  var cards = {}; // ladder id -> its card's parts
  var lastData = null; // the last /api/ladders
  var refresh = null; // asks /api/ladders right away
  var fromTouched = false; // "from" typed in by hand

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
    c.about = el("span");
    c.foot.appendChild(c.about);
    c.acts = el("span", "acts");
    c.run = button("Run", "btn primary sm", function () {
      act("run", l.id, c.run, "Starting…");
    });
    c.stop = button("Stop", "btn sm", function () {
      act("stop", l.id, c.stop, "Stopping…");
    });
    c.del = button("Delete", "btn danger sm", function () {
      remove(l.id, c.del);
    });
    c.acts.appendChild(c.run);
    c.acts.appendChild(c.stop);
    c.acts.appendChild(c.del);
    c.foot.appendChild(c.acts);
    c.box.appendChild(c.foot);
    cards[l.id] = c;
    return c;
  }

  function button(text, cls, click) {
    var b = el("button", cls, text);
    b.type = "button";
    b.addEventListener("click", click);
    return b;
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
    c.about.textContent = "#" + l.id + " · " + sent +
      " · since " + nx.shortDate(l.created.split(" ")[0]);
    c.acts.hidden = !canChange();
    // a done ladder has no level left to run for
    c.run.hidden = l.state === "running" || l.state === "done";
    c.stop.hidden = l.state !== "running";
    c.box.dataset.state = l.state;
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

  // run or stop ladder id
  function act(what, id, b, text) {
    busy(b, text);
    nx.send("/api/ladders/" + what, { id: id })
      .then(function (result) {
        idle(b);
        nx.tell(result.text);
        refresh();
      })
      .catch(function (error) {
        idle(b);
        nx.tell("ladder " + id + " not " +
          (what === "run" ? "started" : "stopped") + ": " +
          (error.message || error), true);
      });
  }

  // delete ladder id, after asking, like 'rm ladder'
  function remove(id, b) {
    var l = lastData.ladders.filter(function (one) {
      return one.id === id;
    })[0];
    var what = l ? " (" + l.stock + " " + l.direction + " " +
      g(l.step) + " from " + g(l.from) + ")" : "";
    var question = (l && l.state === "running"
      ? "Stop and delete ladder " : "Delete ladder ") +
      id + what + "?";
    if (!window.confirm(question)) return;
    busy(b, "Deleting…");
    nx.send("/api/ladders/delete", { id: id })
      .then(function (result) {
        nx.tell(result.text);
        refresh();
      })
      .catch(function (error) {
        idle(b);
        nx.tell("ladder " + id + " not deleted: " +
          (error.message || error), true);
      });
  }

  // "from": the stock's price, unless typed in
  function fillFrom() {
    if (fromTouched) return;
    var price = lastData.prices[$("f-stock").value];
    $("f-from").value = price === undefined
      ? "" : price.toFixed(2);
  }

  function openForm() {
    var select = $("f-stock");
    select.textContent = "";
    lastData.names.forEach(function (name) {
      var option = el("option", "", name);
      option.value = name;
      select.appendChild(option);
    });
    $("f-down").checked = true;
    $("f-step").value = "";
    $("f-run").checked = true;
    fromTouched = false;
    fillFrom();
    $("f-error").hidden = true;
    $("add").hidden = false;
    $("add-open").setAttribute("aria-expanded", "true");
    select.focus();
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
    var step = $("f-step").value.trim();
    var from = $("f-from").value.trim();
    // an input of type number gives "" for what
    // isn't a number
    if (!step || !from) {
      formError("give the step and the from price");
      return;
    }
    var change = {
      stock: $("f-stock").value,
      direction: $("add-form").elements.direction.value,
      step: Number(step),
      from: Number(from),
      run: $("f-run").checked
    };
    busy($("f-submit"), change.run ? "Starting…" : "Saving…");
    nx.send("/api/ladders/add", change)
      .then(function (result) {
        idle($("f-submit"));
        closeForm();
        if (result.start_error) {
          nx.tell(result.text + ", but not started: " +
            result.start_error, true);
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
  $("f-stock").addEventListener("change", fillFrom);
  $("f-from").addEventListener("input", function () {
    fromTouched = true;
  });

  // ---------- drawing ----------

  function draw(data) {
    lastData = data;
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
    $("ladders-sub").textContent = (count
      ? count + (count === 1 ? " ladder" : " ladders") +
        " · " + running + " running"
      : "") + (data.read_only
      ? (count ? " · " : "") + "read-only" : "");
    $("no-ladders").hidden = count > 0;
    $("add-open").hidden = data.read_only;
    if (data.read_only) closeForm();
  }

  refresh = nx.poll("/api/ladders", draw);
})();
