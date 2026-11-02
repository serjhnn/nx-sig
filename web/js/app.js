// nX-sig web: what every page shares, served as
// /js/app.js before the page's own script
//
// window.nx has:
//   $(id), el(tag, cls, text)   find and make elements
//   num, signed, trend          numbers as text
//   clock, dayTime              ISO times as text
//   shortDate("02.09.2026")     "02.09.26", as the shell
//   chartLink(name)             a link to the chart of
//       stock name, with the name as its text
//   binButton(label)            a bin button (class
//       "del") that deletes, label its name
//   put(node, key, text)        set a node's text, flash
//       it when the text under key changed
//   showNotice(title, text), hideNotice()
//   sentence(text)              a server text as a sentence
//   tell(text, failed)          the result of a change in
//       the page's #done box: a few seconds, longer for
//       a failure (the notice is for the polling)
//   answer(response)            the JSON of a fetch
//       response, or an Error with the server's text
//   send(url, data)             POSTs data (an object)
//       as JSON with the server's token; a promise of
//       the answer, or an Error with the server's text
//   poll(url, draw)             asks url (or what the
//       function url gives each time) every
//       "interval" seconds (the server's config "web"
//       "interval"), calls draw(data); pauses while
//       the tab is hidden. on an error it keeps the
//       last data and says what went wrong; the top
//       bar shows the prices' time and error. gives a
//       function that asks again right away; its
//       stop() ends the asking (a closed chart)
// it also marks the open page in the menu, opens
// and closes More (the other pages, on a phone) and
// runs the theme button (dark or light, kept in
// localStorage).

(function () {
  "use strict";

  var THEME_KEY = "nx-theme";
  var MINUS = "−";

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

  // "02.09.2026" -> "02.09.26", as the shell
  function shortDate(date) {
    return date.length === 10
      ? date.slice(0, 6) + date.slice(-2) : date;
  }

  // a link to the chart page of stock name
  function chartLink(name) {
    var link = el("a", "to-chart", name);
    link.href = "/charts?stock=" + encodeURIComponent(name);
    return link;
  }

  var SVG = "http://www.w3.org/2000/svg";
  var BIN = "M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13" +
    "M9 7V4h6v3";

  // a bin button that deletes, label its name (read
  // out and shown on hover)
  function binButton(label) {
    var button = el("button", "del");
    button.type = "button";
    button.setAttribute("aria-label", label);
    button.title = label;
    var svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("fill", "none");
    svg.setAttribute("stroke", "currentColor");
    svg.setAttribute("stroke-width", "2");
    svg.setAttribute("stroke-linecap", "round");
    svg.setAttribute("stroke-linejoin", "round");
    var path = document.createElementNS(SVG, "path");
    path.setAttribute("d", BIN);
    svg.appendChild(path);
    button.appendChild(svg);
    return button;
  }

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

  // ---------- the top bar and the notice ----------

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

  function hideNotice() {
    $("notice").hidden = true;
  }

  // the demo chip, the prices' time and error
  function showPrices(data) {
    $("demo").hidden = !data.demo;
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
      hideNotice();
    } else {
      setLive("off", "waiting for prices");
      hideNotice();
    }
  }

  // a server text as a sentence: capital first,
  // a full stop last
  function sentence(text) {
    text = String(text);
    return text.charAt(0).toUpperCase() + text.slice(1) +
      (/[.!?]$/.test(text) ? "" : ".");
  }

  var tellTimer = null;

  // the result of a change: in its own box, so the
  // next poll doesn't hide it
  function tell(text, failed) {
    var box = $("done");
    $("done-text").textContent = sentence(text);
    box.className = "notice " + (failed ? "warn" : "ok");
    box.querySelector(".dot").className =
      "dot" + (failed ? " warn" : "");
    box.hidden = false;
    clearTimeout(tellTimer);
    tellTimer = setTimeout(function () {
      box.hidden = true;
    }, failed ? 15000 : 6000);
  }

  // ---------- asking the server ----------

  // the JSON of a response; an Error with the
  // server's text (and .status) if it isn't ok
  function answer(response) {
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
  }

  // a change: data as JSON, with the token the
  // server put into the page (scripts/web/api.py)
  function send(url, data) {
    return fetch(url, {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-NX-Token": document.querySelector(".top").dataset.token
      },
      body: JSON.stringify(data)
    }).then(answer);
  }

  // ask url every interval seconds, draw(data) each
  // answer
  function poll(url, draw) {
    var timer = null;
    var lastData = null;
    var stopped = false;

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
      if (!document.hidden && !stopped) {
        timer = setTimeout(ask, Math.max(1, seconds) * 1000);
      }
    }

    function ask() {
      var interval = lastData ? lastData.interval : 5;
      var address = typeof url === "function" ? url() : url;
      fetch(address, { cache: "no-store" })
        .then(answer)
        .then(function (data) {
          if (stopped) return;
          lastData = data;
          showPrices(data);
          draw(data);
          // the first prices come a moment after the
          // first ask: ask again soon
          next(data.updated ? data.interval : 1);
        })
        .catch(function (error) {
          if (stopped) return;
          failed(error);
          next(interval);
        });
    }

    function visible() {
      clearTimeout(timer);
      if (!document.hidden) ask();
    }

    document.addEventListener("visibilitychange", visible);
    ask();
    var again = function () {
      if (stopped) return;
      clearTimeout(timer);
      ask();
    };
    again.stop = function () {
      stopped = true;
      clearTimeout(timer);
      document.removeEventListener("visibilitychange", visible);
    };
    return again;
  }

  // ---------- the menu and the theme ----------

  Array.prototype.forEach.call(
    document.querySelectorAll(".nav a[href]"),
    function (link) {
      if (link.getAttribute("href") === location.pathname) {
        link.setAttribute("aria-current", "page");
        // a page under More: More is the current tab
        if (link.closest(".more")) {
          $("more-btn").classList.add("current");
        }
      }
    }
  );

  // More opens and closes the list of the other
  // pages (on a phone); a tap outside or Escape
  // closes it
  function openMore(open) {
    document.querySelector(".nav").classList.toggle("open", open);
    $("more-btn").setAttribute("aria-expanded", String(open));
  }

  $("more-btn").addEventListener("click", function (event) {
    event.stopPropagation();
    openMore($("more-btn").getAttribute("aria-expanded") !== "true");
  });
  document.addEventListener("click", function (event) {
    if (!event.target.closest(".more")) openMore(false);
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") openMore(false);
  });

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

  window.nx = {
    $: $,
    el: el,
    num: num,
    signed: signed,
    trend: trend,
    clock: clock,
    dayTime: dayTime,
    shortDate: shortDate,
    chartLink: chartLink,
    binButton: binButton,
    put: put,
    showNotice: showNotice,
    hideNotice: hideNotice,
    sentence: sentence,
    tell: tell,
    answer: answer,
    send: send,
    poll: poll
  };
})();
