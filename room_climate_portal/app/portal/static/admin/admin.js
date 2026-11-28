(function () {
  "use strict";
  function $(s) { return document.querySelector(s); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function num(v) { return v == null ? "–" : Number(v).toFixed(1).replace(".", ","); }
  var TZ;
  function time(iso) { return new Date(iso).toLocaleString("ro-RO", { weekday: "short", hour: "2-digit", minute: "2-digit", timeZone: TZ }); }

  function hm(iso) { return new Date(iso).toLocaleTimeString("ro-RO", { hour: "2-digit", minute: "2-digit", timeZone: TZ }); }

  // ------------------------------------------------------------ search / filter
  var ROOMS = [], FILTER = "all";
var LOGS = [];
var LOG_ACTION_FILTER = "all";
var LOG_Q = "";
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
    viewonly: function (r) { return !!r.view_only; },
    issues: function (r) { return (r.issues || []).length > 0; }
  };
  function matches(r, words) {
    if (!TESTS[FILTER](r)) return false;
    var h = haystack(r);
    return words.every(function (w) { return h.indexOf(w) !== -1; });
  }
  // ``force``: id of a room whose row must be redrawn even while in use (it was just saved or reset).
  function renderRooms(force) {
    var words = fold($("#q").value).split(/\s+/).filter(Boolean);
    var shown = ROOMS.filter(function (r) { return matches(r, words); });
    Live.list($("#rooms tbody"), shown.map(row).join("") ||
      '<tr class="nomatch"><td colspan="7">Nicio cameră nu se potrivește. <button type="button" class="small" id="clear">Șterge căutarea</button></td></tr>', force);
    var ps = $("#print-shown");
    ps.hidden = !shown.length || shown.length === ROOMS.length;
    ps.textContent = "Printează afișate (" + shown.length + ")";
    ps.href = "print?auto=1&rooms=" + encodeURIComponent(shown.map(function (r) { return r.id; }).join(","));
    $("#count").textContent = shown.length === ROOMS.length ? ROOMS.length + " camere" : shown.length + " din " + ROOMS.length + " camere";
    document.querySelectorAll("#chips button").forEach(function (b) {
      var f = b.getAttribute("data-f");
      b.classList.toggle("on", f === FILTER);
      var n = ROOMS.filter(TESTS[f]).length;
      Live.html(b, esc(b.getAttribute("data-label") || b.textContent) + (f === "all" ? "" : "<b>" + n + "</b>"));
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
  var ACTION = { idle: "inactiv", heating: "încălzește", cooling: "răcește", off: "oprit", drying: "dezumidifică", fan: "ventilează", preheating: "preîncălzește" };
  var MODE_LABEL = { off: "Oprit", heat: "Încălzire", cool: "Răcire", auto: "Automat", heat_cool: "Încălzire / răcire", dry: "Uscare", fan_only: "Ventilație" };
  var FLAME = '<svg width="13" height="13" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2c2 4 6 6 6 11a6 6 0 0 1-12 0c0-3 2-5 3-7 1 2 2 3 3 3 0-3-1-5 0-7z" fill="currentColor"/></svg>';
  function isHeating(r) { return !!(r.available && r.hvac_mode !== "off" && r.heating_on); }
  function rangeText(r) {
    var t = "Interval " + num(r.set_min) + "–" + num(r.set_max) + " °C";
    var lim = [];
    if (r.entity_min != null && r.entity_min > r.min_temp) lim.push("minimul termostatului " + num(r.entity_min));
    if (r.entity_max != null && r.entity_max < r.max_temp) lim.push("maximul termostatului " + num(r.entity_max));
    return t + (lim.length ? " (limitat de " + lim.join(", ") + ")" : "");
  }
  // Live state of the thermostat, read-only.
  function nowCell(r) {
    var html = '<div class="mlbl">Termostatul acum</div><div class="mono muted ent">' + esc(r.climate || "fără termostat") + "</div>";
    if (!r.climate) return html;
    if (!r.available) return html + '<div class="live-state off">Indisponibil</div>';
    var mode = MODE_LABEL[r.hvac_mode] || r.hvac_mode || "–";
    var preset = r.preset_mode && r.preset_mode !== "none" ? presetLabel(r.preset_mode) : "";
    html += '<div class="live-state' + (r.hvac_mode === "off" ? " off" : "") + '"><b>' + esc(mode) + "</b>" +
      (preset ? ' <span class="pill">' + esc(preset) + "</span>" : "") +
      (r.hvac_mode !== "off" && r.target != null ? " · țintă <b>" + num(r.target) + " °C</b>" : "") + "</div>";
    var heating = isHeating(r);
    html += '<div class="live-cur">Camera <b>' + num(r.current) + " °C</b>" +
      (heating ? ' · <span class="heat-badge">' + FLAME + "Încălzește</span>" : (r.hvac_action ? ' · <span class="act">' + esc(ACTION[r.hvac_action] || r.hvac_action) + "</span>" : "")) + "</div>";
    if (r.hold) html += '<div class="hold">' + (r.hold.kind === "planned" ? "Perioadă planificată" : "Încălzire manuală de la oaspeți") + " până la " + hm(r.hold.end) + "</div>";
    if (r.planned) html += '<div class="muted">' + r.planned + " planificate</div>";
    html += '<div class="muted small">' + esc(rangeText(r)) + "</div>";
    return html;
  }
  // The room's saved settings: what the controls change, applied now and restored after events/timers.
  function climateCell(r) {
    var head = '<div class="mlbl">Setările camerei</div>';
    if (!r.climate || !r.available) return head + '<div class="muted">Termostat indisponibil</div>';
    var d = r.default || {};
    var saved = !!d.hvac_mode;
    var temp = PENDING[r.id] != null ? PENDING[r.id] : (d.temperature != null ? d.temperature : r.target);
    var mode = d.hvac_mode || r.hvac_mode;
    var preset = saved ? (d.preset_mode || "none") : (r.preset_mode || "none");
    var stepper = '<div class="stepper' + (PENDING[r.id] != null ? " pending" : "") + '">' +
      '<button type="button" class="small" data-temp="' + esc(r.id) + '" data-dir="-1"' + (temp != null && temp <= r.set_min ? " disabled" : "") + ' aria-label="Mai puțin">−</button>' +
      "<b>" + num(temp) + " °C</b>" +
      '<button type="button" class="small" data-temp="' + esc(r.id) + '" data-dir="1"' + (temp != null && temp >= r.set_max ? " disabled" : "") + ' aria-label="Mai mult">+</button></div>';
    var modes = (r.hvac_modes || []).map(function (m) {
      return '<option value="' + esc(m) + '"' + (m === mode ? " selected" : "") + ">" + esc(MODE_LABEL[m] || m) + "</option>";
    }).join("");
    var sel = modes ? '<select class="mode" data-mode="' + esc(r.id) + '" aria-label="Mod">' + modes + "</select>" : "";
    var presets = r.preset_modes || [];
    if (presets.length) {
      var opts = presets.slice();
      if (opts.indexOf(preset) === -1) opts.unshift(preset);
      sel += '<select class="mode preset" data-preset="' + esc(r.id) + '" aria-label="Preset">' + opts.map(function (p) {
        return '<option value="' + esc(p) + '"' + (p === preset ? " selected" : "") + ">" + esc(presetLabel(p)) + "</option>";
      }).join("") + "</select>";
    }
    var ecoEnd = r.manual_end === "eco" && presets.indexOf(r.eco_preset) !== -1;
    var note = saved ? "Salvat. Revine după evenimentele din calendar" + (ecoEnd ? "; încălzirea manuală a oaspeților se încheie pe Eco." : " și după timere.") :
      'Nesalvat încă: arată valorile de acum. După evenimente: ' + (r.fallback === "setback" ? "coboară la " + num(r.setback_temp) + " °C" : "oprit") + ".";
    var differs = saved && (d.hvac_mode !== r.hvac_mode || (d.preset_mode && d.preset_mode !== (r.preset_mode || "none")) ||
      (!d.preset_mode && d.hvac_mode !== "off" && d.temperature != null && r.target != null && Math.abs(d.temperature - r.target) > 0.01));
    if (differs) note += ' <span class="diff">Termostatul are acum alte valori' + (r.hold ? " (încălzire de la oaspeți)" : "") + ".</span>";
    return head + '<div class="tctl">' + stepper + sel + "</div>" + '<div class="after">' + note + "</div>";
  }

  var CODE_KIND = { random: "aleator", readable: "ușor de citit", custom: "personalizat" };
  var PRESET_LABEL = { none: "Fără preset", away: "Plecat", eco: "Eco", comfort: "Confort", home: "Acasă", sleep: "Somn",
    boost: "Boost", activity: "Activitate", Winter: "Iarnă", Summer: "Vară", OFF: "Oprit" };
  function presetLabel(p) { return PRESET_LABEL[p] || (p.charAt(0).toUpperCase() + p.slice(1).replace(/_/g, " ")); }
  function roomById(id) { return ROOMS.filter(function (r) { return r.id === id; })[0]; }
  function replaceRoom(updated) {
    ROOMS = ROOMS.map(function (r) { return r.id === updated.id ? updated : r; });
    renderRooms(updated.id);
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
        flash(row.name + ": ținta e acum " + num(value) + " °C");
      }).catch(function (e) {
        delete PENDING[id];
        renderRooms(id);
        flash(r.name + ": " + e.message);
      });
    }, 700);
  }
  document.addEventListener("change", function (ev) {
    var li = ev.target.closest("input[data-lead]");
    if (li) {
      var lid = li.getAttribute("data-lead"), lr = roomById(lid), raw = li.value.trim();
      var mins = Number(raw);
      if (raw === "" || !Number.isInteger(mins) || mins < 0 || mins > 600) {
        renderRooms(lid);
        return flash((lr ? lr.name : lid) + ": preîncălzirea trebuie să fie între 0 și 600 de minute întregi");
      }
      li.disabled = true;
      return sendRoom(lid, "lead_time", { lead_minutes: mins }).then(function (row) {
        replaceRoom(row);
        flash(row.name + ": încălzirea pornește cu " + mins + " min înainte de evenimente");
      }).catch(function (e) { renderRooms(lid); flash((lr ? lr.name : lid) + ": " + e.message); });
    }
    var vo = ev.target.closest("input[data-vo]");
    if (vo) {
      var vid = vo.getAttribute("data-vo"), want = vo.checked;
      vo.disabled = true;
      return sendRoom(vid, "view_only", { view_only: want }).then(function (row) {
        replaceRoom(row);
        flash(row.name + (want ? ": doar vizualizare" : ": oaspeții pot modifica din nou"));
      }).catch(function (e) { renderRooms(vid); flash(e.message); });
    }
    var ps = ev.target.closest("select[data-preset]");
    if (ps) {
      var pid = ps.getAttribute("data-preset"), pr = roomById(pid), preset = ps.value;
      ps.disabled = true;
      return sendRoom(pid, "preset", { preset_mode: preset }).then(function (row) {
        replaceRoom(row);
        flash(row.name + ": preset " + presetLabel(preset));
      }).catch(function (e) {
        renderRooms(pid);
        flash((pr ? pr.name : pid) + ": " + e.message);
      });
    }
    var s = ev.target.closest("select[data-mode]");
    if (!s) return;
    var id = s.getAttribute("data-mode"), r = roomById(id), mode = s.value;
    s.disabled = true;
    sendRoom(id, "mode", { hvac_mode: mode }).then(function (row) {
      replaceRoom(row);
      flash(row.name + ": mod " + (MODE_LABEL[mode] || mode));
    }).catch(function (e) {
      renderRooms(id);
      flash((r ? r.name : id) + ": " + e.message);
    });
  });

  // Pre-heat lead before each calendar event, set per room here (events don't carry one).
  function leadCell(r) {
    var src = r.lead_source === "room" ? "doar această cameră" : r.lead_source === "estimated" ? "ora estimată pentru următorul eveniment"
      : "toate camerele";
    return '<div class="lead"><label>Pornește cu <input type="number" class="lead-in" min="0" max="600" step="5" inputmode="numeric" data-lead="' +
      esc(r.id) + '" value="' + esc(r.lead_minutes) + '" aria-label="Preîncălzire în minute"> min înainte de evenimente</label>' +
      (r.lead_source === "room" ? ' <button type="button" class="small" data-lead-reset="' + esc(r.id) + '">Resetează</button>' : "") +
      '</div><div class="muted small mono">' + esc(src) + "</div>";
  }

  var ISSUES = { missing_calendar: "fără calendar", missing_climate: "fără termostat", climate_not_found: "termostat inexistent",
    ambiguous_climate: "mai multe termostate", invalid_limits: "limite de temperatură greșite" };
  function issueText(i) {
    var k = String(i).split(":")[0], rest = String(i).slice(k.length);
    return (ISSUES[k] || k.replace(/_/g, " ")) + rest;
  }
  function row(r) {
    var issues = (r.issues || []).map(function (i) { return '<span class="issue">' + esc(issueText(i)) + "</span>"; }).join(" ");
    var ev = r.next_event;
    var open = OPEN[r.id];
    var cls = (open ? "open " : "") + (isHeating(r) ? "heating" : "");
    return "<tr data-id=\"" + esc(r.id) + "\" data-key=\"" + esc(r.id) + "\"" + (cls.trim() ? ' class="' + cls.trim() + '"' : "") + ">" +
      "<td class=\"c-room\"><div class=\"rhead\"><div><b class=\"rname\">" + esc(r.name) + (isHeating(r) ? ' <span class="flame" title="Încălzește">' + FLAME + "</span>" : "") + "</b><div class=\"muted\">" + esc(r.subtitle) +
        '<span class="m-only"> · ' + (r.pin_enabled ? "cu PIN" : "fără PIN") + "</span>" + (r.view_only ? ' <span class="vo-tag">🔒 Doar vizualizare</span>' : "") + "</div><div class=\"mono muted d-only\">" + esc(r.id) + "</div></div>" +
        '<button type="button" class="more m-only" data-more="' + esc(r.id) + '" aria-expanded="' + (open ? "true" : "false") + '">' + (open ? "Mai puțin ▴" : "Detalii ▾") + "</button></div>" +
        (issues ? "<div>" + issues + "</div>" : "") + "</td>" +
      "<td class=\"c-now\">" + nowCell(r) + "</td>" +
      "<td class=\"c-temp\">" + climateCell(r) + "</td>" +
      "<td class=\"c-x\"><div class=\"mlbl\">Calendar și preîncălzire</div><div class=\"mono\">" + esc(r.calendar || "–") + "</div>" + leadCell(r) + "</td>" +
      "<td class=\"c-x\"><div class=\"mlbl\">Următorul eveniment</div>" + (ev ? esc(ev.summary) + "<div class=\"muted\">" + time(ev.start) + "</div><div class=\"muted\">preîncălzire de la " + time(ev.precondition_start) + "</div>" : "<span class=\"muted\">niciunul</span>") + "</td>" +
      "<td class=\"c-x c-qr\"><div class=\"mlbl\">Cod QR</div><a href=\"print?auto=1&room=" + encodeURIComponent(r.id) + "\" target=\"_blank\" rel=\"noopener\"><img class=\"qr\" alt=\"QR\" src=\"qr/" + encodeURIComponent(r.id) + ".svg?g=" + r.generation + "&c=" + encodeURIComponent(r.url.split("/").pop()) + "\"></a>" +
      '<div class="caption">Text la printare: <b>' + (esc(r.print_caption) || '<span class="muted">(niciunul)</span>') + "</b>" +
        (r.own_caption ? ' <span class="muted">(doar această cameră)</span>' : "") +
        ' <button type="button" class="small" data-caption="' + esc(r.id) + '">Modifică</button></div>' +
      "<div class=\"url\">" + esc(r.url) + " <b>(" + esc(CODE_KIND[r.code_kind] || CODE_KIND.random) + ")</b></div>" +
        (r.code_kind !== "random" && !r.pin_enabled ? '<div class="issue">Link ușor de ghicit: setează un PIN</div>' : "") + "<div class=\"muted\">" + r.open_pages + " deschise acum</div></td>" +
      "<td class=\"c-x\"><div class=\"mlbl\">PIN și cod</div><div>" + (r.pin_enabled ? "<b>Activ</b>" : "<span class=\"muted\">Inactiv</span>") + "</div>" +
      '<div class="vo"><label class="switch"><input type="checkbox" data-vo="' + esc(r.id) + '"' + (r.view_only ? " checked" : "") + '><span></span></label> Doar vizualizare <span class="muted">(oaspeții văd, dar nu pot modifica)</span></div>' +
      "<div class=\"btns\"><button class=\"small\" data-pin=\"" + esc(r.id) + "\">" + (r.pin_enabled ? "Schimbă PIN-ul" : "Setează PIN") + "</button>" +
      (r.pin_enabled ? "<button class=\"small\" data-nopin=\"" + esc(r.id) + "\">Șterge PIN-ul</button>" : "") +
      "<button class=\"small\" data-code=\"" + esc(r.id) + "\" data-current=\"" + esc(r.code_kind !== "random" ? r.url.split("/").pop() : "") + "\">Cod personalizat</button>" +
      (r.readable_codes && r.code_kind !== "readable" ? "<button class=\"small\" data-readable=\"" + esc(r.id) + "\">Cod ușor de citit</button>" : "") +
      "<button class=\"small\" data-rotate=\"" + esc(r.id) + "\">Cod aleator nou</button></div></td></tr>";
  }

  function load() {
    return fetch("api/status").then(function (r) { return r.json(); }).then(function (s) {
      TZ = s.time_zone || undefined;
      Live.html($("#status"), '<span class="dot ' + (s.ha_connected ? "on" : "") + '"></span>' +
        (s.ha_connected ? "Conectat la Home Assistant" : "Neconectat la Home Assistant") +
        " · URL public <code>" + esc(s.public_url) + "</code> · etichetă <code>" + esc(s.room_label) + "</code> · " + esc(s.time_zone));
      $("#label").textContent = s.room_label;
      return loadRest();
    }).catch(loadRest);
  }

  // Log filtering and toggle
  var LOG_Q = "";
  function renderAudit() {
    var words = fold(LOG_Q).split(/\s+/).filter(Boolean);
    var shown = LOGS.filter(function (a) {
      var h = fold([a.room, a.action, a.client].join(" "));
      return words.every(function (w) { return h.indexOf(w) !== -1; });
    });
    Live.list($("#audit tbody"), shown.map(auditRow).join("") || '<tr><td colspan="4" class="muted">Nicio modificare încă.</td></tr>');
    renderRooms();
  }

  var REASON = {
    event_end: "sfârșit de eveniment", event_removed: "eveniment șters", timer: "timer", stopped: "oprit", preheat: "preîncălzire",
    preheat_warm: "cald înainte de eveniment", event: "eveniment", event_no_sensor: "eveniment fără senzor", frost: "antiîngheț",
    setback: "temperatura minimă de așteptare", coast: "oprire anticipată", test_a: "test A", test_b: "test B", idle: "nimic de încălzit",
    automation_on: "o automatizare preluată a fost repornită"
  };
  var FIELD = { boiler: "centrală", circuit: "circuit", valve: "robinet", temperature: "senzor", category: "încălzire", comfort: "confort" };
  function reason(r) { return REASON[r] || String(r || "").replace(/_/g, " "); }
  function when(ts) { return new Date(ts * 1000).toLocaleString("ro-RO", { timeZone: TZ, dateStyle: "short", timeStyle: "short" }); }
  // One line per entry of Recent changes.
  function changeText(a) {
    switch (a.action) {
      case "view_only": return "Pagina camerei: doar vizualizare";
      case "changes_allowed": return "Pagina camerei: modificări permise";
      case "set_preset": return "Preset " + esc(presetLabel(a.old || "none")) + " → " + esc(presetLabel(a.new || "none"));
      case "code_readable": return "Cod QR ușor de citit";
      case "code_custom": return "Cod QR personalizat";
      case "set_hvac_mode": return "Mod " + esc(MODE_LABEL[a.old] || a.old) + " → " + esc(MODE_LABEL[a.new] || a.new);
      case "set_temperature": return num(a.old) + " → " + num(a.new) + " °C";
      case "rotate_token": return "Cod QR înlocuit";
      case "heating_on": return "Încălzire manuală pornită, " + num(a.new) + " °C până la " + hm(a.until);
      case "heating_until": return "Încălzirea manuală se oprește acum la " + hm(a.until);
      case "heating_planned": return "Planificat " + hm(a.start) + "–" + hm(a.until) + ", " + num(a.new) + " °C";
      case "heating_plan_cancelled": return "Perioadă planificată ștearsă";
      case "heating_off": return "Încălzire oprită (" + esc(reason(a.reason)) + ")";
      case "setback": return "Coborâtă la " + num(a.new) + " °C (" + esc(reason(a.reason)) + ")";
      case "hold_end_eco": return "Încălzire manuală încheiată → Eco (" + esc(a.new) + ")";
      case "restore_default": return "Înapoi la setările camerei: " + esc(MODE_LABEL[a.mode] || a.mode) +
        (a.preset ? " · preset " + esc(presetLabel(a.preset)) : (a.mode !== "off" && a.new != null ? " " + num(a.new) + " °C" : "")) + " (" + esc(reason(a.reason)) + ")";
      case "hold_end_kept_for_event": return "Încălzire manuală încheiată, rămâne pornită pentru eveniment";
      case "control": return "Controler: " + esc(a.entity) + " → " + esc(a.new) + " (" + esc(reason(a.reason)) + (a.detail ? ", " + esc(a.detail) : "") + ")";
      case "control_mode": return "Comandă încălzire " + esc(modeName(a.old)) + " → " + esc(modeName(a.new)) +
        ((a.takeover || []).length ? " · preia " + esc(a.takeover.join(", ")) : "") + (a.reason ? " (" + esc(reason(a.reason)) + ")" : "");
      case "control_error": return "Controlerul nu a putut comuta " + esc(a.entity) + ": " + esc(a.error);
      case "notify": return "Notificare: " + esc(a.new) + " · " + esc(a.detail);
      case "test_scheduled": return "Test programat pe " + esc(a.entity) + " pentru " + when(a.new);
      case "test_cancelled": return "Test anulat pe " + esc(a.entity);
      case "lead_mode": return "Preîncălzirea folosește " + (a.new === "estimated" ? "ora estimată" : "timpul fix");
      case "plant_link": return "Instalație: " + Object.keys(FIELD).filter(function (k) { return k in a; })
        .map(function (k) { return FIELD[k] + " " + esc(a[k] == null ? "automat" : a[k]); }).join(", ");
      case "session_note": return "Notă în jurnalul de încălzire: " + esc(a.note || "ștearsă");
      case "print_caption": return "Text la printare: " + esc(a.new);
      case "lead_time": return a.room === "all" ? "Preîncălzire pentru toate camerele: " + esc(a.new) + " min"
        : "Preîncălzire " + esc(a.old) + " → " + esc(a.new) + " min" + (a.source !== "room" ? " (înapoi la valoarea comună)" : "");
      default: return esc(a.action) + " " + esc(a.new || "");
    }
  }
  function modeName(m) { return m === "active" ? "Activ" : m === "shadow" ? "Simulare" : m; }

  $("#audit-toggle").addEventListener("click", function () {
    var audit = $("#audit");
    var filter = $("#log-filter");
    var wasHidden = audit.hidden;
    audit.hidden = !wasHidden;
    filter.hidden = !wasHidden;
    this.textContent = wasHidden ? "Ascunde" : "Arată";
  });

  $("#logq").addEventListener("input", function () {
    LOG_Q = this.value;
    renderAudit();
  });

  function loadRest() {
    return Promise.all([
      fetch("api/rooms").then(function (r) { return r.json(); }).then(function (rooms) {
        ROOMS = rooms;
        if (!TESTS[FILTER]) FILTER = "all";
        renderRooms();
        $("#empty").hidden = rooms.length > 0;
        $("#rooms").hidden = rooms.length === 0;
        $("#filters").hidden = rooms.length === 0;
      }),
      fetch("api/audit?limit=50").then(function (r) { return r.json(); }).then(function (rows) {
        LOGS = rows;
        Live.list($("#audit tbody"), rows.map(auditRow).join("") || '<tr><td colspan="4" class="muted">Nicio modificare încă.</td></tr>');
        renderRooms();
      })
    ]);
  }
  function auditRow(a) {
    return "<tr data-key=\"" + esc(a.ts + "|" + a.room + "|" + a.action) + "\" data-room=\"" + esc(a.room) + "\"><td class=\"a-time\">" + when(a.ts) +
      "</td><td class=\"a-room\">" + esc(a.room) + "</td><td class=\"a-change\">" + changeText(a) + "</td><td class=\"mono a-client\">" + esc(a.client) + "</td></tr>";
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
    input.maxLength = opts.maxLength || (opts.text_input ? 64 : 8);
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
          try { return JSON.parse(t).error || t; } catch (e) { return t || ("Eroare HTTP " + r.status); }
        });
      })
      .catch(function () { return "Add-on-ul nu răspunde."; });
  }

  function validPin(v) { return /^\d{4,8}$/.test(v) ? null : "PIN-ul trebuie să aibă între 4 și 8 cifre."; }

  document.addEventListener("click", function (ev) {
    var mb = ev.target.closest("button[data-more]");
    if (mb) { var mid = mb.getAttribute("data-more"); OPEN[mid] = !OPEN[mid]; return renderRooms(); }
    var lrb = ev.target.closest("button[data-lead-reset]");
    if (lrb) {
      var lrid = lrb.getAttribute("data-lead-reset");
      lrb.disabled = true;
      return sendRoom(lrid, "lead_time", { lead_minutes: null }).then(function (row) {
        replaceRoom(row);
        flash(row.name + ": preîncălzirea revine la " + row.lead_minutes + " min (valoarea comună)");
      }).catch(function (e) { renderRooms(lrid); flash(e.message); });
    }
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
        title: "PIN pentru " + rid, text: "Între 4 și 8 cifre. Telefoanele care au deblocat deja camera trebuie să introducă noul PIN.",
        input: true, okLabel: "Salvează PIN-ul", validate: validPin,
        onOk: function (v) { return postJson("api/rooms/" + encodeURIComponent(rid) + "/pin", { pin: v }); }
      });
    }
    var n = ev.target.closest("[data-nopin]");
    if (n) {
      var nid = n.getAttribute("data-nopin");
      return dialog({
        title: "Ștergi PIN-ul pentru " + nid + "?", text: "Oricine are codul QR al camerei va putea schimba temperatura.",
        okLabel: "Șterge PIN-ul", danger: true,
        onOk: function () { return postJson("api/rooms/" + encodeURIComponent(nid) + "/pin", { pin: null }); }
      });
    }
    var c = ev.target.closest("[data-code]");
    if (c) {
      var cid = c.getAttribute("data-code");
      return dialog({
        title: "Cod personalizat pentru " + cid,
        text: "Linkul camerei devine …/" + "<cod>. Între 4 și 64 de litere, cifre, - sau _. Codul printat acum nu va mai funcționa. " +
          "Codurile scurte sau ușor de ghicit (de exemplu numărul camerei) pot fi încercate de oricine, așa că setează și un PIN.",
        input: true, text_input: true, placeholder: "ex. camera204-x7k", value: c.getAttribute("data-current"),
        okLabel: "Salvează codul",
        validate: function (v) { return /^[A-Za-z0-9_-]{4,64}$/.test(v) ? null : "Folosește între 4 și 64 de litere, cifre, - sau _."; },
        onOk: function (v) { return postJson("api/rooms/" + encodeURIComponent(cid) + "/code", { code: v }); }
      });
    }
    var cap = ev.target.closest("[data-caption]");
    if (cap) {
      var capId = cap.getAttribute("data-caption"), capRoom = roomById(capId);
      return dialog({
        title: "Text la printare pentru " + (capRoom ? capRoom.name : capId),
        text: "Apare sub codul QR al camerei pe foaia printată (maxim 80 de caractere). Lasă gol ca să folosești textul comun.",
        input: true, text_input: true, maxLength: 80, placeholder: "ex. Scanează- Termostat",
        value: capRoom && capRoom.own_caption ? capRoom.print_caption : "",
        okLabel: "Salvează",
        onOk: function (v) { return postJson("api/rooms/" + encodeURIComponent(capId) + "/caption", { caption: v === "" ? null : v }); }
      });
    }
    var rd = ev.target.closest("[data-readable]");
    if (rd) {
      var rid2 = rd.getAttribute("data-readable");
      return dialog({
        title: "Cod ușor de citit pentru " + rid2 + "?",
        text: "Linkul se formează din etajul și numele camerei din Home Assistant, de exemplu …/demisol-d01-sala-sport. Codul printat acum nu va mai funcționa. Oricine știe numele camerei poate ghici linkul, așa că setează și un PIN.",
        okLabel: "Folosește codul ușor de citit",
        onOk: function () { return postJson("api/rooms/" + encodeURIComponent(rid2) + "/readable", {}); }
      });
    }
    var b = ev.target.closest("[data-rotate]");
    if (!b) return;
    var id = b.getAttribute("data-rotate");
    dialog({
      title: "Cod aleator nou pentru " + id + "?", text: "Înlocuiește codul actual (și pe cel personalizat). Codul printat nu mai funcționează imediat. Printează apoi codul nou.",
      okLabel: "Cod aleator nou", danger: true,
      onOk: function () { return postJson("api/rooms/" + encodeURIComponent(id) + "/rotate", {}); }
    });
  });
  $("#lead-all").addEventListener("click", function () {
    var cur = ROOMS.length ? ROOMS[0].default_lead_minutes : 120;
    dialog({
      title: "Preîncălzire pentru toate camerele",
      text: "Cu câte minute înainte de fiecare eveniment din calendar pornește încălzirea, în toate camerele (0–600). Înlocuiește valorile setate pe camere. Lasă gol ca să revii la 120 min.",
      input: true, text_input: true, maxLength: 3, placeholder: "120", value: String(cur),
      okLabel: "Aplică la toate camerele",
      validate: function (v) { return v === "" || (/^\d{1,3}$/.test(v) && Number(v) <= 600) ? null : "Folosește între 0 și 600 de minute întregi."; },
      onOk: function (v) { return postJson("api/lead_time_all", { lead_minutes: v === "" ? null : Number(v) }); }
    });
  });
  $("#caption-all").addEventListener("click", function () {
    var cur = ROOMS.filter(function (r) { return !r.own_caption; })[0];
    dialog({
      title: "Text la printare pentru toate camerele",
      text: "Apare sub codul QR al fiecărei camere pe foaia printată (maxim 80 de caractere). Înlocuiește textele setate pe camere. Lasă gol ca să revii la „Scanează- Termostat”.",
      input: true, text_input: true, maxLength: 80, placeholder: "Scanează- Termostat",
      value: cur ? cur.print_caption : "",
      okLabel: "Aplică la toate camerele",
      onOk: function (v) { return postJson("api/caption_all", { caption: v === "" ? null : v }); }
    });
  });
  $("#vo-all").addEventListener("click", function () {
    var allLocked = ROOMS.length && ROOMS.every(function (r) { return r.view_only; });
    dialog({
      title: allLocked ? "Permiți modificări în toate camerele?" : "Doar vizualizare în toate camerele?",
      text: allLocked ? "Oaspeții pot schimba din nou temperatura, presetul și încălzirea manuală în toate camerele."
        : "Oaspeții pot deschide în continuare paginile camerelor și văd starea, dar nu pot modifica nimic. Tu poți modifica totul de aici.",
      okLabel: allLocked ? "Permite modificări" : "Doar vizualizare peste tot", danger: !allLocked,
      onOk: function () { return postJson("api/view_only_all", { view_only: !allLocked }); }
    });
  });
  $("#pin-all").addEventListener("click", function () {
    dialog({
      title: "Același PIN pentru toate camerele", text: "Înlocuiește PIN-ul fiecărei camere. Lasă gol ca să ștergi PIN-ul peste tot.",
      input: true, okLabel: "Aplică la toate camerele",
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
  Live.every(10000, load, function () { return !$("#view-rooms").hidden; });
})();
