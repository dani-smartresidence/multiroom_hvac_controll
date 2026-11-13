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
    var ps = $("#print-shown");
    ps.hidden = !shown.length || shown.length === ROOMS.length;
    ps.textContent = "Print shown (" + shown.length + ")";
    ps.href = "print?auto=1&rooms=" + encodeURIComponent(shown.map(function (r) { return r.id; }).join(","));
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

  // ------------------------------------------------------------ thermostat control
  var PENDING = {}, TIMERS = {}, OPEN = {};
  var MODE_LABEL = { off: "Off", heat: "Heat", cool: "Cool", auto: "Auto", heat_cool: "Heat / cool", dry: "Dry", fan_only: "Fan" };
  function rangeText(r) {
    var t = "Range " + num(r.set_min) + "–" + num(r.set_max) + " °C";
    var lim = [];
    if (r.entity_min != null && r.entity_min > r.min_temp) lim.push("thermostat min " + num(r.entity_min));
    if (r.entity_max != null && r.entity_max < r.max_temp) lim.push("thermostat max " + num(r.entity_max));
    return t + (lim.length ? " (limited by " + lim.join(", ") + ")" : "");
  }
  // Live state of the thermostat, read-only.
  function nowCell(r) {
    var html = '<div class="mlbl">Thermostat now</div><div class="mono muted ent">' + esc(r.climate || "no thermostat") + "</div>";
    if (!r.climate) return html;
    if (!r.available) return html + '<div class="live-state off">Unavailable</div>';
    var mode = MODE_LABEL[r.hvac_mode] || r.hvac_mode || "–";
    var preset = r.preset_mode && r.preset_mode !== "none" ? presetLabel(r.preset_mode) : "";
    html += '<div class="live-state' + (r.hvac_mode === "off" ? " off" : "") + '"><b>' + esc(mode) + "</b>" +
      (preset ? ' <span class="pill">' + esc(preset) + "</span>" : "") +
      (r.hvac_mode !== "off" && r.target != null ? " · target <b>" + num(r.target) + " °C</b>" : "") + "</div>";
    html += '<div class="live-cur">Room <b>' + num(r.current) + " °C</b>" + (r.hvac_action ? ' · <span class="act ' + esc(r.hvac_action) + '">' + esc(r.hvac_action) + "</span>" : "") + "</div>";
    if (r.hold) html += '<div class="hold">' + (r.hold.kind === "planned" ? "Planned period" : "Guest manual heating") + " until " + hm(r.hold.end) + "</div>";
    if (r.planned) html += '<div class="muted">' + r.planned + " planned</div>";
    html += '<div class="muted small">' + esc(rangeText(r)) + "</div>";
    return html;
  }
  // The room's saved settings: what the controls change, applied now and restored after events/timers.
  function climateCell(r) {
    var head = '<div class="mlbl">Room settings</div>';
    if (!r.climate || !r.available) return head + '<div class="muted">Thermostat unavailable</div>';
    var d = r.default || {};
    var saved = !!d.hvac_mode;
    var temp = PENDING[r.id] != null ? PENDING[r.id] : (d.temperature != null ? d.temperature : r.target);
    var mode = d.hvac_mode || r.hvac_mode;
    var preset = saved ? (d.preset_mode || "none") : (r.preset_mode || "none");
    var stepper = '<div class="stepper' + (PENDING[r.id] != null ? " pending" : "") + '">' +
      '<button type="button" class="small" data-temp="' + esc(r.id) + '" data-dir="-1"' + (temp != null && temp <= r.set_min ? " disabled" : "") + ' aria-label="Lower">−</button>' +
      "<b>" + num(temp) + " °C</b>" +
      '<button type="button" class="small" data-temp="' + esc(r.id) + '" data-dir="1"' + (temp != null && temp >= r.set_max ? " disabled" : "") + ' aria-label="Raise">+</button></div>';
    var modes = (r.hvac_modes || []).map(function (m) {
      return '<option value="' + esc(m) + '"' + (m === mode ? " selected" : "") + ">" + esc(MODE_LABEL[m] || m) + "</option>";
    }).join("");
    var sel = modes ? '<select class="mode" data-mode="' + esc(r.id) + '" aria-label="Mode">' + modes + "</select>" : "";
    var presets = r.preset_modes || [];
    if (presets.length) {
      var opts = presets.slice();
      if (opts.indexOf(preset) === -1) opts.unshift(preset);
      sel += '<select class="mode preset" data-preset="' + esc(r.id) + '" aria-label="Preset">' + opts.map(function (p) {
        return '<option value="' + esc(p) + '"' + (p === preset ? " selected" : "") + ">" + esc(presetLabel(p)) + "</option>";
      }).join("") + "</select>";
    }
    var ecoEnd = r.manual_end === "eco" && presets.indexOf(r.eco_preset) !== -1;
    var note = saved ? "Saved. Restored after calendar events" + (ecoEnd ? "; guest manual heating ends in Eco." : " and timers.") :
      'Not saved yet: shows the live values. After events: ' + (r.fallback === "setback" ? "setback " + num(r.setback_temp) + " °C" : "Off") + ".";
    var differs = saved && (d.hvac_mode !== r.hvac_mode || (d.preset_mode && d.preset_mode !== (r.preset_mode || "none")) ||
      (!d.preset_mode && d.hvac_mode !== "off" && d.temperature != null && r.target != null && Math.abs(d.temperature - r.target) > 0.01));
    if (differs) note += ' <span class="diff">Thermostat differs now' + (r.hold ? " (guest heating)" : "") + ".</span>";
    return head + '<div class="tctl">' + stepper + sel + "</div>" + '<div class="after">' + note + "</div>";
  }

  var PRESET_LABEL = { none: "No preset", away: "Away", eco: "Eco", comfort: "Comfort", home: "Home", sleep: "Sleep",
    boost: "Boost", activity: "Activity" };
  function presetLabel(p) { return PRESET_LABEL[p] || (p.charAt(0).toUpperCase() + p.slice(1).replace(/_/g, " ")); }
  function roomById(id) { return ROOMS.filter(function (r) { return r.id === id; })[0]; }
  function replaceRoom(updated) {
    ROOMS = ROOMS.map(function (r) { return r.id === updated.id ? updated : r; });
    renderRooms();
  }
  function flash(msg) {
    var el = $("#flash");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(flash.t);
    flash.t = setTimeout(function () { el.hidden = true; }, 5000);
  }
  function sendRoom(id, path, body) {
    return fetch("api/rooms/" + encodeURIComponent(id) + "/" + path, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body)
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (b) {
        if (!r.ok) throw new Error(b.error || ("HTTP " + r.status));
        return b;
      });
    });
  }
  function stepTemp(id, dir) {
    var r = roomById(id);
    if (!r) return;
    var st = r.step || 0.5, base = PENDING[id] != null ? PENDING[id] : (r.target != null ? r.target : 21);
    var v = Math.round((base + dir * st) / st) * st;
    PENDING[id] = Math.min(r.set_max, Math.max(r.set_min, Math.round(v * 100) / 100));
    renderRooms();
    clearTimeout(TIMERS[id]);
    TIMERS[id] = setTimeout(function () {
      var value = PENDING[id];
      sendRoom(id, "temperature", { temperature: value }).then(function (row) {
        if (PENDING[id] === value) delete PENDING[id];
        replaceRoom(row);
        flash(row.name + ": target set to " + num(value) + " °C");
      }).catch(function (e) {
        delete PENDING[id];
        renderRooms();
        flash(r.name + ": " + e.message);
      });
    }, 700);
  }
  document.addEventListener("change", function (ev) {
    var ps = ev.target.closest("select[data-preset]");
    if (ps) {
      var pid = ps.getAttribute("data-preset"), pr = roomById(pid), preset = ps.value;
      ps.disabled = true;
      return sendRoom(pid, "preset", { preset_mode: preset }).then(function (row) {
        replaceRoom(row);
        flash(row.name + ": preset " + presetLabel(preset));
      }).catch(function (e) {
        renderRooms();
        flash((pr ? pr.name : pid) + ": " + e.message);
      });
    }
    var s = ev.target.closest("select[data-mode]");
    if (!s) return;
    var id = s.getAttribute("data-mode"), r = roomById(id), mode = s.value;
    s.disabled = true;
    sendRoom(id, "mode", { hvac_mode: mode }).then(function (row) {
      replaceRoom(row);
      flash(row.name + ": mode " + (MODE_LABEL[mode] || mode));
    }).catch(function (e) {
      renderRooms();
      flash((r ? r.name : id) + ": " + e.message);
    });
  });

  function row(r) {
    var issues = (r.issues || []).map(function (i) { return '<span class="issue">' + esc(i) + "</span>"; }).join(" ");
    var ev = r.next_event;
    var open = OPEN[r.id];
    return "<tr data-id=\"" + esc(r.id) + "\"" + (open ? ' class="open"' : "") + ">" +
      "<td class=\"c-room\"><div class=\"rhead\"><div><b class=\"rname\">" + esc(r.name) + "</b><div class=\"muted\">" + esc(r.subtitle) +
        '<span class="m-only"> · ' + (r.pin_enabled ? "PIN on" : "no PIN") + "</span></div><div class=\"mono muted d-only\">" + esc(r.id) + "</div></div>" +
        '<button type="button" class="more m-only" data-more="' + esc(r.id) + '" aria-expanded="' + (open ? "true" : "false") + '">' + (open ? "Less ▴" : "Details ▾") + "</button></div>" +
        (issues ? "<div>" + issues + "</div>" : "") + "</td>" +
      "<td class=\"c-now\">" + nowCell(r) + "</td>" +
      "<td class=\"c-temp\">" + climateCell(r) + "</td>" +
      "<td class=\"mono c-x\"><div class=\"mlbl\">Calendar &amp; lead time</div>" + esc(r.calendar || "–") + "<div>" + esc(r.lead_time || "default") + " → " + esc(r.lead_minutes) + " min</div></td>" +
      "<td class=\"c-x\"><div class=\"mlbl\">Next event</div>" + (ev ? esc(ev.summary) + "<div class=\"muted\">" + time(ev.start) + "</div><div class=\"muted\">precondition " + time(ev.precondition_start) + "</div>" : "<span class=\"muted\">none</span>") + "</td>" +
      "<td class=\"c-x c-qr\"><div class=\"mlbl\">QR code</div><a href=\"print?auto=1&room=" + encodeURIComponent(r.id) + "\" target=\"_blank\" rel=\"noopener\"><img class=\"qr\" alt=\"QR\" src=\"qr/" + encodeURIComponent(r.id) + ".svg?g=" + r.generation + "&c=" + encodeURIComponent(r.url.split("/").pop()) + "\"></a>" +
      "<div class=\"url\">" + esc(r.url) + " <b>(" + esc(r.code_kind || "random") + ")</b></div>" +
        (r.code_kind !== "random" && !r.pin_enabled ? '<div class="issue">Easy-to-guess link: set a PIN</div>' : "") + "<div class=\"muted\">" + r.open_pages + " open now</div></td>" +
      "<td class=\"c-x\"><div class=\"mlbl\">PIN &amp; code</div><div>" + (r.pin_enabled ? "<b>On</b>" : "<span class=\"muted\">Off</span>") + "</div>" +
      "<div class=\"btns\"><button class=\"small\" data-pin=\"" + esc(r.id) + "\">" + (r.pin_enabled ? "Change PIN" : "Set PIN") + "</button>" +
      (r.pin_enabled ? "<button class=\"small\" data-nopin=\"" + esc(r.id) + "\">Remove PIN</button>" : "") +
      "<button class=\"small\" data-code=\"" + esc(r.id) + "\" data-current=\"" + esc(r.code_kind !== "random" ? r.url.split("/").pop() : "") + "\">Custom code</button>" +
      (r.readable_codes && r.code_kind !== "readable" ? "<button class=\"small\" data-readable=\"" + esc(r.id) + "\">Readable code</button>" : "") +
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
        var change = a.action === "set_preset" ? "Preset " + esc(a.old || "none") + " → " + esc(a.new)
          : a.action === "code_readable" ? "Readable QR code"
          : a.action === "code_custom" ? "Custom QR code"
          : a.action === "set_hvac_mode" ? "Mode " + esc(a.old) + " → " + esc(a.new)
          : a.action === "set_temperature" ? num(a.old) + " → " + num(a.new) + " °C"
          : a.action === "rotate_token" ? "QR code replaced"
          : a.action === "heating_on" ? "Manual heating on, " + num(a.new) + " °C until " + hm(a.until)
          : a.action === "heating_until" ? "Manual heating now ends " + hm(a.until)
          : a.action === "heating_planned" ? "Planned " + hm(a.start) + "–" + hm(a.until) + ", " + num(a.new) + " °C"
          : a.action === "heating_plan_cancelled" ? "Planned period removed"
          : a.action === "heating_off" ? "Heating turned off (" + esc(a.reason) + ")"
          : a.action === "setback" ? "Setback to " + num(a.new) + " °C (" + esc(a.reason) + ")"
          : a.action === "hold_end_eco" ? "Manual heating ended → Eco (" + esc(a.new) + ")"
          : a.action === "restore_default" ? "Back to room settings: " + esc(MODE_LABEL[a.mode] || a.mode) + (a.preset ? " · preset " + esc(presetLabel(a.preset)) : (a.mode !== "off" && a.new != null ? " " + num(a.new) + " °C" : "")) + " (" + esc(String(a.reason).replace("_", " ")) + ")"
          : a.action === "hold_end_kept_for_event" ? "Manual heating ended, kept on for event"
          : esc(a.action) + " " + esc(a.new || "");
        return "<tr data-room=\"" + esc(a.room) + "\"><td class=\"a-time\">" + new Date(a.ts * 1000).toLocaleString([], { timeZone: TZ, dateStyle: "short", timeStyle: "short" }) + "</td><td class=\"a-room\">" + esc(a.room) + "</td><td class=\"a-change\">" + change + "</td><td class=\"mono a-client\">" + esc(a.client) + "</td></tr>";
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
    var mb = ev.target.closest("button[data-more]");
    if (mb) { var mid = mb.getAttribute("data-more"); OPEN[mid] = !OPEN[mid]; return renderRooms(); }
    var tb = ev.target.closest("button[data-temp]");
    if (tb) return stepTemp(tb.getAttribute("data-temp"), parseInt(tb.getAttribute("data-dir"), 10));
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
    var rd = ev.target.closest("[data-readable]");
    if (rd) {
      var rid2 = rd.getAttribute("data-readable");
      return dialog({
        title: "Readable code for " + rid2 + "?",
        text: "The link is rebuilt from the room's floor and name in Home Assistant, e.g. …/demisol-d01-sala-sport. The current printed code stops working. Anyone who knows the room name can guess this link, so set a PIN too.",
        okLabel: "Use readable code",
        onOk: function () { return postJson("api/rooms/" + encodeURIComponent(rid2) + "/readable", {}); }
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
  // Heights of the sticky header and search bar, so the table head sticks right below them.
  function measureSticky() {
    var root = document.documentElement.style;
    root.setProperty("--top-h", document.querySelector(".top").offsetHeight + "px");
    root.setProperty("--filters-h", ($("#filters").hidden ? 0 : $("#filters").offsetHeight) + "px");
  }
  window.addEventListener("resize", measureSticky);
  if (window.ResizeObserver) {
    var ro = new ResizeObserver(measureSticky);
    ro.observe(document.querySelector(".top"));
    ro.observe($("#filters"));
  }
  measureSticky();
  setInterval(function () {
    var a = document.activeElement;
    if (a && a.matches && a.matches("select.mode")) return;  // also preset menus  // don't close an open mode menu
    load();
  }, 30000);
})();
