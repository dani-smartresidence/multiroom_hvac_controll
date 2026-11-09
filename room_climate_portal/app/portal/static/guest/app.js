/* Room Climate Portal - guest page. No framework, no third-party code. */
(function () {
  "use strict";

  var I18N = {
    ro: {
      loading: "Se încarcă…", live: "Conectat", offline: "Reconectare…", target: "Țintă", now: "Acum",
      now_short: "Acum", heating: "Încălzire", cooling: "Răcire", idle: "Temperatură atinsă", off: "Oprit",
      fan: "Ventilație", drying: "Dezumidificare", unavailable: "Termostat indisponibil",
      adjustable: "Reglabil {min} – {max} °C · pas de {step}°",
      mode: "Mod", humidity: "Umiditate", outside: "Exterior",
      mode_heat: "Încălzire", mode_cool: "Răcire", mode_auto: "Automat", mode_heat_cool: "Automat",
      mode_off: "Oprit", mode_dry: "Uscare", mode_fan_only: "Ventilație",
      next_in_room: "Urmează în această cameră", all_events: "Toate ›", schedule: "Program",
      preconditioning: "Precondiționare", event: "Eveniment", today: "Azi", tomorrow: "Mâine",
      target_short: "țintă", now_temp: "acum", pre_line: "Precondiționare: <b>{time}</b> · {min} min înainte",
      pre_now: "Precondiționare în curs de la <b>{time}</b>", start_label: "pornire",
      badge_pre: "● Se pregătește", badge_active: "● În desfășurare", badge_sched: "Programat",
      all_day: "Toată ziua", no_events: "Niciun eveniment programat în următoarele {days} zile.",
      foot: "Din calendarul Home Assistant · următoarele {days} zile",
      set_to: "Temperatură setată la <b>{t} °C</b>", undo: "Anulează",
      err_rate: "Prea multe modificări. Încercați din nou peste câteva secunde.",
      err_generic: "Nu s-a putut modifica temperatura.", err_offline: "Fără conexiune la sistem.",
      invalid_title: "Acest cod QR nu mai este activ",
      invalid_body: "Codul acestei camere a fost înlocuit. Scanați codul QR de pe placa din interiorul camerei.",
      need_help: "Aveți nevoie de ajutor?", starting: "Sistemul pornește, reîncercăm…",
      title: "Climat cameră",
      pin_title: "Introduceți codul PIN", pin_body: "Codul PIN al camerei este necesar pentru a controla temperatura.",
      pin_submit: "Continuă", pin_wrong: "PIN greșit. Mai aveți {n} încercări.",
      pin_locked: "Prea multe încercări. Reîncercați peste {m} min.", pin_short: "PIN-ul are între 4 și 8 cifre."
    },
    en: {
      loading: "Loading…", live: "Live", offline: "Reconnecting…", target: "Target", now: "Now",
      now_short: "Now", heating: "Heating", cooling: "Cooling", idle: "At temperature", off: "Off",
      fan: "Fan", drying: "Drying", unavailable: "Thermostat unavailable",
      adjustable: "Adjustable {min} – {max} °C · steps of {step}°",
      mode: "Mode", humidity: "Humidity", outside: "Outside",
      mode_heat: "Heat", mode_cool: "Cool", mode_auto: "Auto", mode_heat_cool: "Auto",
      mode_off: "Off", mode_dry: "Dry", mode_fan_only: "Fan",
      next_in_room: "Next in this room", all_events: "All events ›", schedule: "Schedule",
      preconditioning: "Preconditioning", event: "Event", today: "Today", tomorrow: "Tomorrow",
      target_short: "target", now_temp: "now", pre_line: "Preconditioning starts <b>{time}</b> · {min} min before",
      pre_now: "Preconditioning since <b>{time}</b>", start_label: "start",
      badge_pre: "● Preconditioning", badge_active: "● In progress", badge_sched: "Scheduled",
      all_day: "All day", no_events: "No events scheduled in the next {days} days.",
      foot: "From Home Assistant calendar · next {days} days",
      set_to: "Target set to <b>{t} °C</b>", undo: "Undo",
      err_rate: "Too many changes. Please try again in a few seconds.",
      err_generic: "Could not change the temperature.", err_offline: "No connection to the system.",
      invalid_title: "This QR code is no longer active",
      invalid_body: "The code for this room was replaced. Please scan the QR code on the wall plate inside the room.",
      need_help: "Need help?", starting: "System is starting, retrying…",
      title: "Room climate",
      pin_title: "Enter the PIN", pin_body: "The room PIN is required to control the temperature.",
      pin_submit: "Continue", pin_wrong: "Wrong PIN. {n} attempts left.",
      pin_locked: "Too many attempts. Try again in {m} min.", pin_short: "The PIN has 4 to 8 digits."
    }
  };

  var MIN_GAP_MS = 3200;     // server allows one change per room every 3 s
  var DEBOUNCE_MS = 800;
  var SCHEDULE_DAYS = 7;

  var BASE = document.documentElement.getAttribute("data-base") || "";
  var token = (location.pathname.slice(BASE.length).match(/^\/([A-Za-z0-9_-]{4,64})\/?$/) || [])[1] || "";
  var api = BASE + "/api/" + token;
  var pinInfo = null;
  var room = null;
  var pending = null;        // setpoint the guest has chosen but HA has not confirmed
  var awaiting = null;       // value sent, waiting for HA to echo it
  var sendTimer = null, lastSent = 0, toastTimer = null, undoValue = null;
  var es = null;
  var lang = pickLang();

  function $(id) { return document.getElementById(id); }
  function t(key, vars) {
    var s = (I18N[lang] && I18N[lang][key]) || I18N.ro[key] || key;
    if (vars) Object.keys(vars).forEach(function (k) { s = s.split("{" + k + "}").join(vars[k]); });
    return s;
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function pickLang() {
    var saved = null;
    try { saved = localStorage.getItem("rcp-lang"); } catch (e) { /* private mode */ }
    if (saved === "ro" || saved === "en") return saved;
    var def = document.documentElement.getAttribute("data-default-lang");
    return def === "en" ? "en" : "ro";
  }
  function locale() { return lang === "ro" ? "ro-RO" : "en-GB"; }
  function fmt1(v) {
    if (v == null || isNaN(v)) return "–";
    return new Intl.NumberFormat(locale(), { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(v);
  }
  function fmtStep(v) {
    return new Intl.NumberFormat(locale(), { maximumFractionDigits: 2 }).format(v);
  }
  function tz() { return (room && room.time_zone) || undefined; }
  function fmtTime(iso) {
    return new Intl.DateTimeFormat(locale(), { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: tz() }).format(new Date(iso));
  }
  function dayKey(d) {
    return new Intl.DateTimeFormat("en-CA", { year: "numeric", month: "2-digit", day: "2-digit", timeZone: tz() }).format(d);
  }
  function dayLabel(iso) {
    var d = new Date(iso), now = new Date();
    var k = dayKey(d), today = dayKey(now), tomorrow = dayKey(new Date(now.getTime() + 86400000));
    var long = new Intl.DateTimeFormat(locale(), { weekday: "long", day: "numeric", month: "short", timeZone: tz() }).format(d);
    var prefix = k === today ? t("today") + " · " : k === tomorrow ? t("tomorrow") + " · " : "";
    return prefix + long.charAt(0).toUpperCase() + long.slice(1);
  }
  function shortDay(iso) {
    var d = new Date(iso), now = new Date();
    var k = dayKey(d);
    if (k === dayKey(now)) return t("today");
    if (k === dayKey(new Date(now.getTime() + 86400000))) return t("tomorrow");
    var s = new Intl.DateTimeFormat(locale(), { weekday: "short", timeZone: tz() }).format(d);
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  // ------------------------------------------------------------------ views
  function show(name) {
    ["loading", "control", "schedule", "invalid", "pin"].forEach(function (v) { $("view-" + v).hidden = v !== name; });
  }
  function route() {
    if (!room) return;
    show(location.hash === "#program" ? "schedule" : "control");
    window.scrollTo(0, 0);
  }
  function applyStaticText() {
    document.documentElement.lang = lang;
    document.title = (room ? room.name + " · " : "") + t("title");
    document.querySelectorAll("[data-i18n]").forEach(function (el) { el.textContent = t(el.getAttribute("data-i18n")); });
    document.querySelectorAll(".lang b").forEach(function (b) { b.classList.toggle("on", b.getAttribute("data-lang") === lang); });
  }

  // ------------------------------------------------------------------ render
  var CX = 125, CY = 127.3, R = 100, A0 = 148.2, SWEEP = 243.6;
  function pt(deg) { var r = deg * Math.PI / 180; return [CX + R * Math.cos(r), CY + R * Math.sin(r)]; }

  function renderDial(c, value) {
    var frac = (value == null || c.max <= c.min) ? 0 : Math.min(1, Math.max(0, (value - c.min) / (c.max - c.min)));
    var a = A0 + SWEEP * frac, s = pt(A0), e = pt(a);
    var arc = $("dial-arc"), knob = $("dial-knob");
    if (frac <= 0.001) { arc.setAttribute("d", ""); }
    else {
      arc.setAttribute("d", "M " + s[0].toFixed(1) + " " + s[1].toFixed(1) + " A 100 100 0 " + (SWEEP * frac > 180 ? 1 : 0) + " 1 " + e[0].toFixed(1) + " " + e[1].toFixed(1));
    }
    arc.classList.toggle("cool", c.hvac_mode === "cool");
    knob.setAttribute("cx", e[0].toFixed(1));
    knob.setAttribute("cy", e[1].toFixed(1));
    $("dial-min").textContent = fmtStep(c.min) + "°";
    $("dial-max").textContent = fmtStep(c.max) + "°";
  }

  function renderControl() {
    var c = room.climate;
    var shown = pending != null ? pending : (awaiting != null ? awaiting : c.target);
    $("room-name").textContent = room.name;
    $("room-name-2").textContent = room.name;
    $("room-sub").textContent = room.subtitle || "";
    $("target").textContent = fmt1(shown);
    $("target").parentNode.classList.toggle("pending", pending != null || awaiting != null);
    $("current").textContent = c.current == null ? "–" : fmt1(c.current) + " °C";
    renderDial(c, shown);

    var action = $("action");
    action.className = "state";
    var label;
    if (!c.available) label = t("unavailable");
    else if (c.hvac_mode === "off") label = t("off");
    else if (c.hvac_action === "heating" || c.hvac_action === "preheating") { label = t("heating"); action.classList.add("heating"); }
    else if (c.hvac_action === "cooling") { label = t("cooling"); action.classList.add("cooling"); }
    else if (c.hvac_action === "drying") label = t("drying");
    else if (c.hvac_action === "fan") label = t("fan");
    else label = t("idle");
    action.innerHTML = (action.classList.contains("heating") ? '<svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2c2 4 6 6 6 11a6 6 0 0 1-12 0c0-3 2-5 3-7 1 2 2 3 3 3 0-3-1-5 0-7z" fill="currentColor"/></svg>' : "") + esc(label);

    var canChange = c.available && room.connected && c.hvac_mode !== "off";
    $("minus").disabled = !canChange || shown <= c.min;
    $("plus").disabled = !canChange || shown >= c.max;
    $("limits").textContent = t("adjustable", { min: fmtStep(c.min), max: fmtStep(c.max), step: fmtStep(c.step) });

    var chips = [];
    chips.push([t("mode"), t("mode_" + c.hvac_mode) !== "mode_" + c.hvac_mode ? t("mode_" + c.hvac_mode) : (c.hvac_mode || "–")]);
    if (room.humidity != null) chips.push([t("humidity"), Math.round(room.humidity) + " %"]);
    if (room.outdoor != null) chips.push([t("outside"), fmt1(room.outdoor).replace(/[,.]0$/, "") + " °C"]);
    $("chips").innerHTML = chips.map(function (ch) {
      return '<div class="chip"><div class="k">' + esc(ch[0]) + '</div><div class="v">' + esc(ch[1]) + "</div></div>";
    }).join("");

    var modes = $("modes");
    if (room.allow_mode_change && c.hvac_modes.length) {
      modes.hidden = false;
      modes.innerHTML = c.hvac_modes.map(function (m) {
        return '<button type="button" data-mode="' + esc(m) + '" class="' + (m === c.hvac_mode ? "on" : "") + '">' + esc(t("mode_" + m)) + "</button>";
      }).join("");
    } else modes.hidden = true;

    var next = upcoming()[0];
    $("next-event").innerHTML = next ? '<div class="card">' + nextCard(next) + "</div>"
      : '<div class="card empty">' + esc(t("no_events", { days: SCHEDULE_DAYS })) + "</div>";
    $("all-link").hidden = !room.events.length;
  }

  function upcoming() {
    var now = Date.now();
    return (room.events || []).filter(function (e) { return new Date(e.end).getTime() > now; });
  }

  function evState(e, now) {
    var s = new Date(e.start).getTime(), p = e.precondition_start ? new Date(e.precondition_start).getTime() : s;
    if (now >= s) return "active";
    if (now >= p) return "pre";
    return "sched";
  }

  var CLOCK = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke-width="2" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>';

  function preLine(e, now) {
    if (e.all_day || !e.precondition_start) return "";
    var st = evState(e, now);
    if (st === "active") return "";
    if (st === "pre") return '<div class="pre now">' + CLOCK + "<span>" + t("pre_now", { time: fmtTime(e.precondition_start) }) + "</span></div>";
    return '<div class="pre">' + CLOCK + "<span>" + t("pre_line", { time: fmtTime(e.precondition_start), min: e.lead_minutes }) + "</span></div>";
  }

  function timeRange(e) {
    return e.all_day ? t("all_day") : fmtTime(e.start) + " – " + fmtTime(e.end);
  }

  function nextCard(e) {
    var now = Date.now();
    return '<div class="ev"><div class="time"><b>' + (e.all_day ? "–" : fmtTime(e.start)) + "</b><span>" + esc(shortDay(e.start)) + '</span></div><div class="body"><div class="t">' +
      esc(e.summary) + '</div><div class="m">' + esc(timeRange(e)) + " · " + t("target_short") + " " + fmt1(e.target).replace(/[,.]0$/, "") + " °C</div></div></div>" + preLine(e, now);
  }

  function renderSchedule() {
    var now = Date.now(), list = upcoming(), html = "", lastDay = null;
    list.forEach(function (e) {
      var d = dayKey(new Date(e.start));
      if (d !== lastDay) { html += '<div class="day">' + esc(dayLabel(e.start)) + "</div>"; lastDay = d; }
      var st = evState(e, now);
      var badge = st === "pre" ? '<span class="badge now">' + esc(t("badge_pre")) + "</span>"
        : st === "active" ? '<span class="badge act">' + esc(t("badge_active")) + "</span>"
        : '<span class="badge sch">' + esc(t("badge_sched")) + "</span>";
      var meta = timeRange(e) + " · " + t("target_short") + " " + fmt1(e.target).replace(/[,.]0$/, "") + " °C";
      if (st !== "sched" && room.climate.current != null) meta += " · " + t("now_temp") + " " + fmt1(room.climate.current) + " °C";
      html += '<div class="row"><div class="rt"><div class="t">' + esc(e.summary) + "</div>" + badge + '</div><div class="m">' + esc(meta) + "</div>";
      if (st !== "sched" && !e.all_day && e.precondition_start) {
        var p = new Date(e.precondition_start).getTime(), s = new Date(e.start).getTime(), en = new Date(e.end).getTime();
        var span = Math.max(1, en - p), pw = ((s - p) / span) * 100, nw = Math.min(100, Math.max(0, ((now - p) / span) * 100));
        html += '<div class="track"><div class="p" data-w="' + pw.toFixed(1) + '"></div><div class="e" data-l="' + pw.toFixed(1) +
          '"></div><div class="n" data-l="' + nw.toFixed(1) + '"></div></div><div class="ticks"><span>' +
          fmtTime(e.precondition_start) + " " + esc(t("start_label")) + "</span><span>" + fmtTime(e.start) + "</span><span>" + fmtTime(e.end) + "</span></div>";
      } else {
        html += preLine(e, now);
      }
      html += "</div>";
    });
    var listEl = $("schedule-list");
    listEl.innerHTML = html || '<div class="row empty">' + esc(t("no_events", { days: SCHEDULE_DAYS })) + "</div>";
    // CSP forbids inline style attributes; position the bars through the CSSOM instead.
    listEl.querySelectorAll("[data-w]").forEach(function (el) { el.style.left = "0"; el.style.width = el.getAttribute("data-w") + "%"; });
    listEl.querySelectorAll("[data-l]").forEach(function (el) { el.style.left = el.getAttribute("data-l") + "%"; });
    $("schedule-foot").textContent = t("foot", { days: SCHEDULE_DAYS });
  }

  function renderLive() {
    ["live", "live-2"].forEach(function (id) {
      var el = $(id);
      el.classList.toggle("off", !room.connected);
      el.querySelector("span").textContent = room.connected ? t("live") : t("offline");
    });
  }

  function render() {
    if (!room) return;
    SCHEDULE_DAYS = room.schedule_days || SCHEDULE_DAYS;
    applyStaticText();
    renderControl();
    renderSchedule();
    renderLive();
  }

  // ------------------------------------------------------------------ actions
  function step(dir) {
    var c = room.climate;
    var base = pending != null ? pending : (awaiting != null ? awaiting : (c.target != null ? c.target : c.min));
    var next = Math.round((base + dir * c.step) / c.step) * c.step;
    next = Math.min(c.max, Math.max(c.min, Math.round(next * 100) / 100));
    if (undoValue == null) undoValue = c.target;
    pending = next;
    renderControl();
    schedule();
  }

  function schedule() {
    clearTimeout(sendTimer);
    var wait = Math.max(DEBOUNCE_MS, lastSent + MIN_GAP_MS - Date.now());
    sendTimer = setTimeout(send, wait);
  }

  function send() {
    if (pending == null) return;
    var value = pending;
    lastSent = Date.now();
    post("/setpoint", { temperature: value }).then(function (res) {
      if (res.ok) {
        awaiting = res.body.temperature;
        if (room && room.climate.target === awaiting) awaiting = null;  // HA already echoed it
        if (pending === value) pending = null;
        showToast(t("set_to", { t: fmt1(awaiting) }), undoValue != null && undoValue !== awaiting);
        setTimeout(function () { if (awaiting != null) { awaiting = null; renderControl(); } }, 10000);
      } else {
        pending = null; awaiting = null; undoValue = null;
        showToast(esc(res.status === 429 ? t("err_rate") : (res.status === 0 ? t("err_offline") : t("err_generic"))), false, true);
        if (res.status === 404) return showInvalid();
        if (res.status === 401) return load();
      }
      renderControl();
    });
  }

  function post(path, body) {
    return fetch(api + path, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      credentials: "same-origin", cache: "no-store"
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (b) { return { ok: r.ok, status: r.status, body: b }; });
    }).catch(function () { return { ok: false, status: 0, body: {} }; });
  }

  function showToast(html, withUndo, isError) {
    var el = $("toast");
    $("toast-text").innerHTML = html;
    $("toast-undo").hidden = !withUndo;
    el.classList.toggle("err", !!isError);
    el.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.hidden = true; undoValue = null; }, 5000);
  }

  function undo() {
    if (undoValue == null) return;
    pending = undoValue;
    undoValue = null;
    $("toast").hidden = true;
    renderControl();
    schedule();
  }

  function showInvalid(helpText) {
    if (es) { es.close(); es = null; }
    room = null;
    applyStaticText();
    $("help-text").textContent = helpText || "";
    show("invalid");
  }

  // ------------------------------------------------------------------ data
  function onRoom(r) {
    var first = !room;
    room = r;
    if (awaiting != null && r.climate.target === awaiting) awaiting = null;
    render();
    if (first) route();
  }

  function load() {
    if (!token) return showInvalid();
    fetch(api, { cache: "no-store", credentials: "same-origin" }).then(function (r) {
      if (r.status === 404) return r.json().catch(function () { return {}; }).then(function (b) { showInvalid(b.help_text); });
      if (r.status === 401) return r.json().catch(function () { return {}; }).then(showPin);
      if (r.status === 503) { $("view-loading").querySelector("p").textContent = t("starting"); return setTimeout(load, 5000); }
      if (!r.ok) throw new Error("http " + r.status);
      return r.json().then(function (data) { onRoom(data); connect(); });
    }).catch(function () { setTimeout(load, 5000); });
  }

  function connect() {
    if (es) es.close();
    es = new EventSource(api + "/stream");
    es.onopen = function () { $("banner").hidden = true; };
    es.onmessage = function (ev) {
      var msg; try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.type === "room") onRoom(msg.room);
      else if (msg.type === "revoked" || msg.type === "reauth") { if (es) { es.close(); es = null; } load(); }
    };
    es.onerror = function () {
      if (!room) return;
      room.connected = false;
      renderLive();
      if (es && es.readyState === EventSource.CLOSED) { es = null; setTimeout(load, 3000); }
    };
  }

  // ------------------------------------------------------------------ PIN
  function showPin(info) {
    if (es) { es.close(); es = null; }
    room = null;
    pinInfo = info || {};
    applyStaticText();
    $("pin-room").textContent = pinInfo.name || "";
    $("pin-sub").textContent = pinInfo.subtitle || "";
    $("pin-help-text").textContent = pinInfo.help_text || "";
    $("pin-err").textContent = "";
    $("pin-input").value = "";
    show("pin");
    setTimeout(function () { $("pin-input").focus(); }, 50);
  }

  function submitPin(ev) {
    ev.preventDefault();
    var pin = $("pin-input").value.replace(/\D/g, "");
    if (pin.length < 4 || pin.length > 8) { $("pin-err").textContent = t("pin_short"); return; }
    $("pin-submit").disabled = true;
    post("/pin", { pin: pin }).then(function (res) {
      $("pin-submit").disabled = false;
      $("pin-input").value = "";
      if (res.ok) { $("pin-err").textContent = ""; show("loading"); return load(); }
      if (res.status === 429) $("pin-err").textContent = t("pin_locked", { m: Math.max(1, Math.ceil((res.body.retry_after || 60) / 60)) });
      else if (res.status === 403) $("pin-err").textContent = t("pin_wrong", { n: res.body.attempts_left });
      else if (res.status === 404) showInvalid(res.body.help_text);
      else $("pin-err").textContent = t("err_offline");
      $("pin-input").focus();
    });
  }

  // ------------------------------------------------------------------ wire up
  $("plus").addEventListener("click", function () { step(1); });
  $("minus").addEventListener("click", function () { step(-1); });
  $("toast-undo").addEventListener("click", undo);
  function toggleLang() {
    lang = lang === "ro" ? "en" : "ro";
    try { localStorage.setItem("rcp-lang", lang); } catch (e) { /* ignore */ }
    if (room) render(); else applyStaticText();
  }
  $("lang-btn").addEventListener("click", toggleLang);
  $("lang-btn-2").addEventListener("click", toggleLang);
  $("pin-form").addEventListener("submit", submitPin);
  $("modes").addEventListener("click", function (ev) {
    var b = ev.target.closest("button[data-mode]");
    if (!b) return;
    post("/mode", { hvac_mode: b.getAttribute("data-mode") }).then(function (res) {
      if (!res.ok) showToast(esc(res.status === 429 ? t("err_rate") : t("err_generic")), false, true);
    });
  });
  window.addEventListener("hashchange", route);
  setInterval(function () { if (room) { renderControl(); renderSchedule(); } }, 30000);
  document.addEventListener("visibilitychange", function () { if (!document.hidden && room && !es) load(); });

  applyStaticText();
  load();
})();
