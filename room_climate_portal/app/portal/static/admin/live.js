(function () {
  "use strict";
  // Live updates for the admin page: each view is polled, and only the rows and sections whose markup
  // changed are replaced. A node is left alone while someone is using it (a field touched in the last
  // TOUCH_MS, or a value typed but not saved yet); open <details> and drawn charts (data-keep) survive
  // a replacement, and focus moves to the same control in the new markup.

  var FIELDS = "input:not([type=button]):not([type=submit]):not([type=reset]), select, textarea";
  var FOCUSABLE = "button, input, select, textarea, a[href], summary";
  var TOUCH_MS = 15000;

  var touched = 0;
  ["pointerdown", "keydown", "input", "focusin"].forEach(function (type) {
    document.addEventListener(type, function (ev) {
      if (ev.target && ev.target.matches && ev.target.matches(FIELDS)) touched = Date.now();
    }, true);
  });

  function fieldsOf(node) {
    if (!node || node.nodeType !== 1) return [];
    var inner = Array.prototype.slice.call(node.querySelectorAll(FIELDS));
    return node.matches(FIELDS) ? [node].concat(inner) : inner;
  }
  // The value a field shows now, or the one its markup sets.
  function valueOf(el, fromMarkup) {
    if (el.type === "checkbox" || el.type === "radio") return String(fromMarkup ? el.defaultChecked : el.checked);
    if (el.matches("select")) {
      var opts = Array.prototype.slice.call(el.options);
      var picked = opts.filter(function (o) { return fromMarkup ? o.defaultSelected : o.selected; });
      if (!picked.length && fromMarkup && opts.length && !el.multiple) picked = [opts[0]];
      return picked.map(function (o) { return o.value; }).join("\n");
    }
    return fromMarkup ? el.defaultValue : el.value;
  }
  function edited(el) { return valueOf(el, false) !== valueOf(el, true); }

  // Someone is using ``old``: a field inside it was touched just now, or holds a value that neither its
  // own markup nor the incoming one (``fresh``) has. Once the server caught up, the value is no conflict.
  function busy(old, fresh) {
    if (!old || old.nodeType !== 1) return false;
    var a = document.activeElement;
    if (a && old.contains(a) && a.matches(FIELDS) && Date.now() - touched < TOUCH_MS) return true;
    var theirs = fieldsOf(fresh);
    return fieldsOf(old).some(function (f, i) {
      if (!edited(f)) return false;
      return !theirs[i] || valueOf(theirs[i], true) !== valueOf(f, false);
    });
  }
  function parse(html) {
    var t = document.createElement("template");
    t.innerHTML = html;
    return t.content;
  }
  // Carry the parts of the old node that only exist in the browser over to its replacement. After an
  // action (``forced``) the page's own markup decides which <details> are open.
  // Returns a function that restores focus, to call once the new node is in the page.
  function carry(from, to, forced) {
    var opened = from.querySelectorAll("details"), fresh = to.querySelectorAll("details");
    for (var i = 0; !forced && i < opened.length && i < fresh.length; i++) if (opened[i].open) fresh[i].open = true;
    from.querySelectorAll("[data-keep]").forEach(function (old) {
      if (!old.childNodes.length) return;
      var id = old.getAttribute("data-keep");
      var mate = Array.prototype.filter.call(to.querySelectorAll("[data-keep]"), function (n) { return n.getAttribute("data-keep") === id; })[0];
      if (mate) mate.replaceWith(old);
    });
    var a = document.activeElement;
    if (!a || !from.contains(a)) return null;
    var idx = Array.prototype.indexOf.call(from.querySelectorAll(FOCUSABLE), a);
    return idx === -1 ? null : function () {
      var target = to.querySelectorAll(FOCUSABLE)[idx];
      if (target && !target.disabled) target.focus({ preventScroll: true });
    };
  }
  function flagChanged(node) {
    if (node.nodeType !== 1) return;
    node.classList.remove("live-changed");
    void node.offsetWidth;  // restart the animation
    node.classList.add("live-changed");
  }

  // Replace ``old`` by ``markup``, unless nothing changed or it is busy (``force`` skips that check:
  // the page just saved this row and wants the server's version). Returns the node now in the page.
  function swap(old, markup, mark, force) {
    if (old.__live === markup && !force) return old;
    var frag = parse(markup);
    var node = frag.firstElementChild;
    if (!node) return old;
    if (!force && busy(old, node)) return old;  // try again next time: __live still holds the old markup
    node.__live = markup;
    var refocus = carry(old, node, force);
    old.replaceWith(node);
    if (refocus) refocus();
    if (mark && old.__live !== undefined) flagChanged(node);
    return node;
  }
  function keyOf(node, i) {
    return (node.nodeType === 1 && node.getAttribute("data-key")) || "#" + i;
  }
  function attachedAfter(node) {
    var out = [];
    for (var s = node.nextElementSibling; s && s.hasAttribute("data-attached"); s = s.nextElementSibling) out.push(s);
    return out;
  }

  // Patch a container (a tbody, a list of cards) whose children each carry data-key.
  // Rows the page inserts after a child (data-attached, e.g. an opened chart) move with it.
  // ``force``: key or list of keys to replace even if busy.
  function list(container, markup, force) {
    if (!container) return;
    var forced = [].concat(force == null ? [] : force).map(String);
    if (container.__liveAll === markup && !forced.length) return;
    var mark = !!container.__liveSeen;  // no highlight on the first render
    container.__liveSeen = true;
    var items = Array.prototype.slice.call(parse(markup).children);
    var old = {};
    Array.prototype.forEach.call(container.children, function (n, i) {
      if (!n.hasAttribute("data-attached")) old[keyOf(n, i)] = n;
    });
    var stale = false, order = [], used = {};
    items.forEach(function (item, i) {
      var key = keyOf(item, i), html = item.outerHTML, node = old[key];
      used[key] = true;
      if (node) {
        node = swap(node, html, mark, forced.indexOf(key) !== -1);
        if (node.__live !== html) stale = true;
      } else {
        node = item;
        node.__live = html;
        if (mark) flagChanged(node);
      }
      order.push(node);
      if (node.parentNode === container) Array.prototype.push.apply(order, attachedAfter(node));
    });
    Object.keys(old).forEach(function (key) {
      if (used[key]) return;
      var node = old[key];
      if (busy(node, null) && forced.indexOf(key) === -1) { stale = true; order.push(node); return; }
      attachedAfter(node).forEach(function (s) { s.remove(); });
      node.remove();
    });
    order.forEach(function (node, pos) {  // put everything in order, moving only what is out of place
      var here = container.children[pos];
      if (here !== node) container.insertBefore(node, here || null);
    });
    // A busy child kept its old markup, so the next update has to compare again.
    container.__liveAll = stale ? null : markup;
  }

  // Set the content of one element (a status or summary line), only if it changed and nobody is using it.
  // Not highlighted: these lines carry clocks ("updated at 14:05") that change without news.
  function html(el, markup) {
    if (!el || el.__live === markup) return;
    if (el.__live !== undefined) {
      var probe = document.createElement(el.tagName);
      probe.innerHTML = markup;
      if (busy(el, probe)) return;
    }
    el.innerHTML = markup;
    el.__live = markup;
  }

  // ------------------------------------------------------------ polling
  // A job reloads one view. It runs only while ``when()`` says its view is shown, the tab is visible and
  // no dialog is open, never twice at once. Coming back to the tab refreshes straight away.
  var JOBS = [];
  function dialogOpen() {
    var d = document.getElementById("dlg");
    return !!(d && !d.hidden);
  }
  function run(job) {
    if (job.running || document.hidden || dialogOpen() || (job.when && !job.when())) return;
    job.running = true;
    var done = function () { job.running = false; job.last = Date.now(); };
    try {
      Promise.resolve(job.fn()).then(done, done);
    } catch (e) {
      done();
    }
  }
  function every(ms, fn, when) {
    var job = { ms: ms, fn: fn, when: when, last: Date.now(), running: false };
    JOBS.push(job);
    return job;
  }
  setInterval(function () {
    var now = Date.now();
    JOBS.forEach(function (job) { if (now - job.last >= job.ms) run(job); });
  }, 1000);
  function refreshNow() { JOBS.forEach(run); }
  document.addEventListener("visibilitychange", function () { if (!document.hidden) refreshNow(); });

  window.Live = { list: list, html: html, every: every, refreshNow: refreshNow };
})();
