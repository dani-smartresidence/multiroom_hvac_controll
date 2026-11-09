(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function num(v) { return v == null ? "–" : Number(v).toFixed(1); }
  var TZ;
  function time(iso) { return new Date(iso).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit", timeZone: TZ }); }

  function hm(iso) { return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", timeZone: TZ }); }

  // ------------------------------------------------------------ search / filter
  var ROOMS = [], FILTER = "all";
  try { FILTER = sessionStorage.getItem("rcp-admin-filter") || "all"; $("#q").value = sessionStorage.getItem("rcp-admin-q") || ""; } catch (e) { /* ignore */ }
  function fold(s) { return String(s == null ? "" : s).normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase(); }
  function haystack(r) {
    return fold([r.name, r.subtitle, r.id, r.climate, r.calendar, r.url, r.hvac_mode, r.next_event && r.next_event.summary].join(" "));
  }
  var DAY = 86400000;
  var TESTS = {
    all: function () { return true; },
    heating: function (r) { return r.hvac_mode && r.hvac_mode !== "off" && r.hvac_mode !== "unavailable"; },
    manual: function (r) { return !!r.hold || r.planned > 0; },
    event: function (r) { return r.next_event && new Date(r.next_event.start) - Date.now() < DAY; },
    pin: function (r) { return r.pin_enabled; },
    nopin: function (r) { return !r.pin_enabled; },
    issues: function (r) { return (r.issues || []).length > 0; }
  };
  function matches(r, words) {
    if (!TESTS[FILTER](r)) return false;
    var h = haystack(r);
    return words.every(function (w) { return h.indexOf(w) !== -1; });
  }
  function renderRooms() {
    var words = fold($("#q").value).split(/\s+/).filter(Boolean);
    var shown = ROOMS.filter(function (r) { return matches(r, words); });
    $("#rooms tbody").innerHTML = shown.map(row).join("") ||
      '<tr class="nomatch"><td colspan="7">No room matches. <button type="button" class="small" id="clear">Clear search</button></td></tr>';
    $("#count").textContent = shown.length === ROOMS.length ? ROOMS.length + " rooms" : shown.length + " of " + ROOMS.length + " rooms";
    document.querySelectorAll("#chips button").forEach(function (b) {
      var f = b.getAttribute("data-f");
      b.classList.toggle("on", f === FILTER);
      var n = ROOMS.filter(TESTS[f]).length;
      b.innerHTML = esc(b.getAttribute("data-label") || b.textContent) + (f === "all" ? "" : "<b>" + n + "</b>");
    });
    var ids = {};
    shown.forEach(function (r) { ids[r.id] = 1; });
    document.querySelectorAll("#audit tbody tr[data-room]").forEach(function (tr) {
      tr.hidden = (words.length || FILTER !== "all") && !ids[tr.getAttribute("data-room")];
    });
  }
  document.querySelectorAll("#chips button").forEach(function (b) { b.setAttribute("data-label", b.textContent); });
  $("#q").addEventListener("input", function () {
    try { sessionStorage.setItem("rcp-admin-q", this.value); } catch (e) { /* ignore */ }
    renderRooms();
  });
  $("#q").addEventListener("keydown", function (ev) { if (ev.key === "Escape") { this.value = ""; this.dispatchEvent(new Event("input")); } });
  $("#chips").addEventListener("click", function (ev) {
    var b = ev.target.closest("button[data-f]");
    if (!b) return;
    FILTER = b.getAttribute("data-f");
    try { sessionStorage.setItem("rcp-admin-filter", FILTER); } catch (e) { /* ignore */ }
    renderRooms();
  });

  function row(r) {
    var issues = (r.issues || []).map(function (i) { return '<span class="issue">' + esc(i) + "</span>"; }).join(" ");
    var ev = r.next_event;
    return "<tr data-id=\"" + esc(r.id) + "\">" +
      "<td><b>" + esc(r.name) + "</b><div class=\"muted\">" + esc(r.subtitle) + "</div><div class=\"mono muted\">" + esc(r.id) + "</div>" + (issues ? "<div>" + issues + "</div>" : "") + "</td>" +
      "<td class=\"mono\">" + esc(r.climate || "–") + "<div class=\"muted\">" + esc(r.hvac_mode || "") + " · " + num(r.min_temp) + "–" + num(r.max_temp) + " °C</div></td>" +
      "<td>" + num(r.current) + " / <b>" + num(r.target) + "</b> °C" +
        (r.hold ? '<div class="hold">Manual until ' + hm(r.hold.end) + "</div>" : "") +
        (r.planned ? '<div class="muted">' + r.planned + " planned</div>" : "") + "</td>" +
      "<td class=\"mono\">" + esc(r.calendar || "–") + "<div>" + esc(r.lead_time || "default") + " → " + esc(r.lead_minutes) + " min</div></td>" +
      "<td>" + (ev ? esc(ev.summary) + "<div class=\"muted\">" + time(ev.start) + "</div><div class=\"muted\">precondition " + time(ev.precondition_start) + "</div>" : "<span class=\"muted\">none</span>") + "</td>" +
      "<td><a href=\"print?room=" + encodeURIComponent(r.id) + "\" target=\"_blank\" rel=\"noopener\"><img class=\"qr\" alt=\"QR\" src=\"qr/" + encodeURIComponent(r.id) + ".svg?g=" + r.generation + "\"></a>" +
      "<div class=\"url\">" + esc(r.url) + (r.custom_code ? " <b>(custom)</b>" : "") + "</div><div class=\"muted\">" + r.open_pages + " open now</div></td>" +
      "<td><div>" + (r.pin_enabled ? "<b>On</b>" : "<span class=\"muted\">Off</span>") + "</div>" +
      "<div class=\"btns\"><button class=\"small\" data-pin=\"" + esc(r.id) + "\">" + (r.pin_enabled ? "Change PIN" : "Set PIN") + "</button>" +
      (r.pin_enabled ? "<button class=\"small\" data-nopin=\"" + esc(r.id) + "\">Remove PIN</button>" : "") +
      "<button class=\"small\" data-code=\"" + esc(r.id) + "\" data-current=\"" + esc(r.custom_code ? r.url.split("/").pop() : "") + "\">Custom code</button>" +
      "<button class=\"small\" data-rotate=\"" + esc(r.id) + "\">New random code</button></div></td></tr>";
  }

  function load() {
    fetch("api/status").then(function (r) { return r.json(); }).then(function (s) {
      TZ = s.time_zone || undefined;
      $("#status").innerHTML = '<span class="dot ' + (s.ha_connected ? "on" : "") + '"></span>' +
        (s.ha_connected ? "Connected to Home Assistant" : "Not connected to Home Assistant") +
        " · public URL <code>" + esc(s.public_url) + "</code> · label <code>" + esc(s.room_label) + "</code> · " + esc(s.time_zone);
      $("#label").textContent = s.room_label;
      loadRest();
    }).catch(loadRest);
  }

  function loadRest() {
    fetch("api/rooms").then(function (r) { return r.json(); }).then(function (rooms) {
      ROOMS = rooms;
      if (!TESTS[FILTER]) FILTER = "all";
      renderRooms();
      $("#empty").hidden = rooms.length > 0;
      $("#rooms").hidden = rooms.length === 0;
      $("#filters").hidden = rooms.length === 0;
    });
    fetch("api/audit?limit=50").then(function (r) { return r.json(); }).then(function (rows) {
      $("#audit tbody").innerHTML = rows.map(function (a) {
        var change = a.action === "set_temperature" ? num(a.old) + " → " + num(a.new) + " °C"
          : a.action === "rotate_token" ? "QR code replaced"
          : a.action === "heating_on" ? "Manual heating on, " + num(a.new) + " °C until " + hm(a.until)
          : a.action === "heating_until" ? "Manual heating now ends " + hm(a.until)
          : a.action === "heating_planned" ? "Planned " + hm(a.start) + "–" + hm(a.until) + ", " + num(a.new) + " °C"
          : a.action === "heating_plan_cancelled" ? "Planned period removed"
          : a.action === "heating_off" ? "Heating turned off (" + esc(a.reason) + ")"
          : a.action === "setback" ? "Setback to " + num(a.new) + " °C (" + esc(a.reason) + ")"
          : a.action === "hold_end_kept_for_event" ? "Manual heating ended, kept on for event"
          : esc(a.action) + " " + esc(a.new || "");
        return "<tr data-room=\"" + esc(a.room) + "\"><td>" + new Date(a.ts * 1000).toLocaleString([], { timeZone: TZ }) + "</td><td>" + esc(a.room) + "</td><td>" + change + "</td><td class=\"mono\">" + esc(a.client) + "</td></tr>";
      }).join("") || '<tr><td colspan="4" class="muted">No changes yet.</td></tr>';
      renderRooms();
    });
  }

  // In-page dialog. Browser prompt()/confirm() are blocked inside the HA Ingress
  // panel and the HA mobile app, so nothing here relies on them.
  function dialog(opts) {
    var d = $("#dlg");
    $("#dlg-title").textContent = opts.title;
    $("#dlg-text").textContent = opts.text || "";
    $("#dlg-err").textContent = "";
    var input = $("#dlg-input");
    input.hidden = !opts.input;
    input.value = opts.value || "";
    input.type = opts.text_input ? "text" : "password";
    input.setAttribute("inputmode", opts.text_input ? "text" : "numeric");
    input.maxLength = opts.text_input ? 64 : 8;
    input.placeholder = opts.placeholder || "PIN";
    input.classList.toggle("text", !!opts.text_input);
    var ok = $("#dlg-ok");
    ok.textContent = opts.okLabel || "OK";
    ok.className = opts.danger ? "danger" : "primary";
    ok.disabled = false;
    d.hidden = false;
    if (opts.input) setTimeout(function () { input.focus(); }, 30);
    function close() { d.hidden = true; ok.onclick = null; $("#dlg-cancel").onclick = null; $("#dlg-form").onsubmit = null; }
    $("#dlg-cancel").onclick = close;
    $("#dlg-form").onsubmit = function (ev) {
      ev.preventDefault();
      var value = input.value.trim();
      var err = opts.validate ? opts.validate(value) : null;
      if (err) { $("#dlg-err").textContent = err; return; }
      ok.disabled = true;
      opts.onOk(value).then(function (failure) {
        ok.disabled = false;
        if (failure) { $("#dlg-err").textContent = failure; return; }
        close();
        load();
      });
    };
  }

  function postJson(url, body) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) {
        if (r.ok) return null;
        return r.text().then(function (t) {
          try { return JSON.parse(t).error || t; } catch (e) { return t || ("HTTP " + r.status); }
        });
      })
      .catch(function () { return "Cannot reach the add-on."; });
  }

  function validPin(v) { return /^\d{4,8}$/.test(v) ? null : "The PIN must be 4 to 8 digits."; }

  document.addEventListener("click", function (ev) {
    if (ev.target.id === "clear") {
      $("#q").value = ""; FILTER = "all";
      try { sessionStorage.removeItem("rcp-admin-q"); sessionStorage.removeItem("rcp-admin-filter"); } catch (e) { /* ignore */ }
      return renderRooms();
    }
    var p = ev.target.closest("[data-pin]");
    if (p) {
      var rid = p.getAttribute("data-pin");
      return dialog({
        title: "PIN for " + rid, text: "4 to 8 digits. Phones that already unlocked this room must enter the new PIN.",
        input: true, okLabel: "Save PIN", validate: validPin,
        onOk: function (v) { return postJson("api/rooms/" + encodeURIComponent(rid) + "/pin", { pin: v }); }
      });
    }
    var n = ev.target.closest("[data-nopin]");
    if (n) {
      var nid = n.getAttribute("data-nopin");
      return dialog({
        title: "Remove the PIN for " + nid + "?", text: "Anyone with the room's QR code can then change its temperature.",
        okLabel: "Remove PIN", danger: true,
        onOk: function () { return postJson("api/rooms/" + encodeURIComponent(nid) + "/pin", { pin: null }); }
      });
    }
    var c = ev.target.closest("[data-code]");
    if (c) {
      var cid = c.getAttribute("data-code");
      return dialog({
        title: "Custom code for " + cid,
        text: "The room link becomes …/" + "<code>. 4-64 letters, digits, - or _. The current printed code stops working. " +
          "Short or guessable codes (like a room number) let anyone try them, so also set a PIN for this room.",
        input: true, text_input: true, placeholder: "e.g. camera204-x7k", value: c.getAttribute("data-current"),
        okLabel: "Save code",
        validate: function (v) { return /^[A-Za-z0-9_-]{4,64}$/.test(v) ? null : "Use 4 to 64 letters, digits, - or _."; },
        onOk: function (v) { return postJson("api/rooms/" + encodeURIComponent(cid) + "/code", { code: v }); }
      });
    }
    var b = ev.target.closest("[data-rotate]");
    if (!b) return;
    var id = b.getAttribute("data-rotate");
    dialog({
      title: "New random code for " + id + "?", text: "Replaces the current code (also a custom one). The printed code stops working immediately. Print the new one afterwards.",
      okLabel: "New random code", danger: true,
      onOk: function () { return postJson("api/rooms/" + encodeURIComponent(id) + "/rotate", {}); }
    });
  });
  $("#pin-all").addEventListener("click", function () {
    dialog({
      title: "Same PIN for all rooms", text: "Replaces every room's PIN. Leave empty to remove the PIN from all rooms.",
      input: true, okLabel: "Apply to all rooms",
      validate: function (v) { return v === "" ? null : validPin(v); },
      onOk: function (v) { return postJson("api/pin_all", { pin: v || null }); }
    });
  });
  $("#reload").addEventListener("click", function () {
    this.disabled = true;
    var btn = this;
    fetch("api/reload", { method: "POST" }).then(function () { btn.disabled = false; load(); });
  });
  load();
  setInterval(load, 30000);
})();
