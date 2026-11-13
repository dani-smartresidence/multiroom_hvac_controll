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
      pin_locked: "Prea multe încercări. Reîncercați peste {m} min.", pin_short: "PIN-ul are între 4 și 8 cifre.",
      manual_heating: "Încălzire manuală", manual_short: "Manual", hold_on_title: "Încălzire pornită · {t} °C",
      plan_on_title: "Perioadă programată · {t} °C",
      hold_on_msg: "Se încheie automat la <b>{time}</b> · {left}", hold_on_msg_day: "Se încheie automat {day} la <b>{time}</b> · {left}",
      hold_off_title: "Pornește încălzirea", hold_off_msg: "Alegeți cât timp. Se încheie singură după {d}, dacă nu alegeți altceva.",
      hold_event_msg: "Programul camerei controlează acum încălzirea. Puteți porni și manual.",
      preset_heat: "Încălzire", preset_eco: "Eco", ok_preset_heat: "Încălzire pornită", ok_preset_eco: "Mod Eco activat",
      stop_now: "Încheie", off_at: "Încheie la", set: "Setează", or_until: "Sau până la", start: "Pornește",
      plan_period: "Programează o perioadă", from: "De la", to: "Până la", temperature: "Temperatură",
      cancel: "Renunță", schedule_it: "Programează", planned: "{day}, {start} – {end} · {t} °C", remove: "Șterge",
      left_min: "încă {m} min", left_hm: "încă {h} h {m} min", left_h: "încă {h} h",
      dur_h: "{h}\u00a0h", dur_min: "{m}\u00a0min",
      ok_started: "Încălzire pornită până la <b>{time}</b>", ok_until: "Se încheie la <b>{time}</b>",
      ok_stopped: "Încălzirea manuală s-a încheiat", ok_planned: "Perioadă programată: <b>{day} {time}</b>", ok_cancelled: "Perioada a fost ștearsă",
      hold_title_row: "Încălzire manuală", plan_title_row: "Perioadă programată", badge_on: "● Pornit",
      e_too_long: "Cel mult {h} h odată.", e_end_before_start: "Ora de sfârșit trebuie să fie după ora de început.",
      e_overlap: "Se suprapune cu o altă perioadă programată.", e_too_many: "Sunt deja prea multe perioade programate.",
      e_too_far: "Puteți programa doar în următoarele 24 de ore.", e_too_short: "Durata minimă este 5 minute.",
      e_bad_time: "Alegeți o oră validă.", e_no_active: "Încălzirea manuală nu mai este pornită.", e_hold: "Nu s-a putut salva."
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
      pin_locked: "Too many attempts. Try again in {m} min.", pin_short: "The PIN has 4 to 8 digits.",
      manual_heating: "Manual heating", manual_short: "Manual", hold_on_title: "Heating on · {t} °C",
      plan_on_title: "Planned period · {t} °C",
      hold_on_msg: "Ends automatically at <b>{time}</b> · {left}", hold_on_msg_day: "Ends automatically {day} at <b>{time}</b> · {left}",
      hold_off_title: "Start heating", hold_off_msg: "Choose for how long. It ends by itself after {d} unless you choose otherwise.",
      hold_event_msg: "The room schedule is controlling the heating now. You can still start it manually.",
      preset_heat: "Heating", preset_eco: "Eco", ok_preset_heat: "Heating on", ok_preset_eco: "Eco mode on",
      stop_now: "End now", off_at: "End at", set: "Set", or_until: "Or until", start: "Start",
      plan_period: "Plan a period", from: "From", to: "Until", temperature: "Temperature",
      cancel: "Cancel", schedule_it: "Plan it", planned: "{day}, {start} – {end} · {t} °C", remove: "Remove",
      left_min: "{m} min left", left_hm: "{h} h {m} min left", left_h: "{h} h left",
      dur_h: "{h}\u00a0h", dur_min: "{m}\u00a0min",
      ok_started: "Heating on until <b>{time}</b>", ok_until: "Ends at <b>{time}</b>",
      ok_stopped: "Manual heating ended", ok_planned: "Period planned: <b>{day} {time}</b>", ok_cancelled: "Period removed",
      hold_title_row: "Manual heating", plan_title_row: "Planned period", badge_on: "● On",
      e_too_long: "At most {h} h at a time.", e_end_before_start: "The end time must be after the start time.",
      e_overlap: "It overlaps another planned period.", e_too_many: "There are already too many planned periods.",
      e_too_far: "You can only plan within the next 24 hours.", e_too_short: "The minimum is 5 minutes.",
      e_bad_time: "Choose a valid time.", e_no_active: "Manual heating is no longer on.", e_hold: "Could not save."
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

    var canChange = c.available && room.connected;
    $("minus").disabled = !canChange || shown <= c.min;
    $("plus").disabled = !canChange || shown >= c.max;
    $("limits").textContent = t("adjustable", { min: fmtStep(c.min), max: fmtStep(c.max), step: fmtStep(c.step) });

    var chips = [];
    var onPreset = (room.guest_presets || []).filter(function (p) { return p.on; })[0];
    if (onPreset && c.hvac_mode !== "off") chips.push([t("mode"), t("preset_" + onPreset.key)]);
    else chips.push([t("mode"), t("mode_" + c.hvac_mode) !== "mode_" + c.hvac_mode ? t("mode_" + c.hvac_mode) : (c.hvac_mode || "–")]);
    if (room.humidity != null) chips.push([t("humidity"), Math.round(room.humidity) + " %"]);
    if (room.outdoor != null) chips.push([t("outside"), fmt1(room.outdoor).replace(/[,.]0$/, "") + " °C"]);
    $("chips").innerHTML = chips.map(function (ch) {
      return '<div class="chip"><div class="k">' + esc(ch[0]) + '</div><div class="v">' + esc(ch[1]) + "</div></div>";
    }).join("");

    var modes = $("modes");
    var gp = room.guest_presets || [];
    var guestModes = (c.hvac_modes || []).filter(function (m) { return m !== "off"; });  // off: admin page only
    if (gp.length) {
      modes.hidden = false;
      modes.className = "modes presets";
      modes.innerHTML = gp.map(function (p) {
        var on = p.on && c.hvac_mode !== "off";
        return '<button type="button" data-preset="' + esc(p.key) + '" class="' + p.key + (on ? " on" : "") + '"' + (usableNow() ? "" : " disabled") + ">" +
          (p.key === "heat" ? FLAME : LEAF) + "<span>" + esc(t("preset_" + p.key)) + "</span></button>";
      }).join("");
    } else if (room.allow_mode_change && guestModes.length > 1) {
      modes.hidden = false;
      modes.className = "modes";
      modes.innerHTML = guestModes.map(function (m) {
        return '<button type="button" data-mode="' + esc(m) + '" class="' + (m === c.hvac_mode ? "on" : "") + '">' + esc(t("mode_" + m)) + "</button>";
      }).join("");
    } else modes.hidden = true;

    renderHold();

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

  var FLAME = '<svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2c2 4 6 6 6 11a6 6 0 0 1-12 0c0-3 2-5 3-7 1 2 2 3 3 3 0-3-1-5 0-7z" fill="currentColor"/></svg>';
  var LEAF = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M5 19c0-8 5-13 15-14-1 10-6 15-14 15"/><path d="M5 19l7-7"/></svg>';
  function usableNow() { return room && room.climate.available && room.connected; }
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
    var now = Date.now(), html = "", lastDay = null;
    var list = upcoming().concat((room.holds || []).map(function (h) { return { hold: h, start: h.start, end: h.end }; }));
    list.sort(function (a, b) { return new Date(a.start) - new Date(b.start); });
    list.forEach(function (e) {
      var d = dayKey(new Date(e.start));
      if (d !== lastDay) { html += '<div class="day">' + esc(dayLabel(e.start)) + "</div>"; lastDay = d; }
      if (e.hold) {
        var h = e.hold;
        html += '<div class="row"><div class="rt"><div class="t">' + esc(t(h.kind === "planned" ? "plan_title_row" : "hold_title_row")) + "</div>" +
          (h.active ? '<span class="badge now">' + esc(t("badge_on")) + "</span>" : '<span class="badge man">' + esc(t("badge_sched")) + "</span>") +
          '</div><div class="m">' + esc(fmtTime(h.start) + " – " + fmtTime(h.end) + " · " + t("target_short") + " " + fmtT(h.target) + " °C") + "</div></div>";
        return;
      }
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
    var base = pending != null ? pending : (awaiting != null ? awaiting : (c.target != null ? c.target : room.default_target));
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


  // ------------------------------------------------------------ manual heating
  var planTemp = null, planOpen = false, holdBusy = false;
  function fmtT(v) { return fmt1(v).replace(/[,.]0$/, ""); }
  function hhmm(d) {
    var p = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", hour12: false, timeZone: tz() }).formatToParts(d);
    var get = function (k) { return (p.filter(function (x) { return x.type === k; })[0] || {}).value; };
    return (get("hour") === "24" ? "00" : get("hour")) + ":" + get("minute");
  }
  function fmtDur(min) {
    return min % 60 === 0 ? t("dur_h", { h: min / 60 }) : (min < 60 ? t("dur_min", { m: min }) : t("dur_h", { h: fmtStep(min / 60) }));
  }
  function leftText(ms) {
    var m = Math.max(1, Math.round(ms / 60000)), h = Math.floor(m / 60);
    m = m % 60;
    if (!h) return t("left_min", { m: m });
    return m ? t("left_hm", { h: h, m: m }) : t("left_h", { h: h });
  }
  function dayWord(iso) {
    var k = dayKey(new Date(iso));
    if (k === dayKey(new Date())) return null;
    return shortDay(iso).toLowerCase();
  }
  function activeHold() { return (room.holds || []).filter(function (h) { return h.active; })[0]; }
  function eventRunning() {
    var now = Date.now();
    return (room.events || []).some(function (e) {
      if (e.all_day) return false;
      var p = new Date(e.precondition_start || e.start).getTime();
      return now >= p && now < new Date(e.end).getTime();
    });
  }

  function renderHold() {
    var c = room.climate, h = activeHold(), now = Date.now();
    var usable = c.available && room.connected;
    $("hold-ic").classList.toggle("on", !!h);
    $("hold-on").hidden = !h;
    $("hold-off").hidden = !!h;
    if (h) {
      $("hold-title").textContent = t(h.kind === "planned" ? "plan_on_title" : "hold_on_title", { t: fmtT(c.target != null ? c.target : h.target) });
      var dw = dayWord(h.end);
      $("hold-msg").innerHTML = t(dw ? "hold_on_msg_day" : "hold_on_msg", { time: fmtTime(h.end), day: esc(dw || ""), left: esc(leftText(new Date(h.end) - now)) });
      var inp = $("hold-until");
      if (document.activeElement !== inp && inp.getAttribute("data-for") !== h.end) { inp.value = hhmm(new Date(h.end)); inp.setAttribute("data-for", h.end); }
    } else {
      var d = room.hold_default_minutes || 120;
      $("hold-title").textContent = t("hold_off_title");
      $("hold-msg").textContent = eventRunning() && c.hvac_mode !== "off" ? t("hold_event_msg") : t("hold_off_msg", { d: fmtDur(d) });
      var opts = [60, d, d * 2].filter(function (v, i, a) { return a.indexOf(v) === i && v <= (room.hold_max_hours || 12) * 60; });
      opts.sort(function (a, b) { return a - b; });
      var key = opts.join(",") + "|" + lang;
      var box = $("hold-durations");
      if (box.getAttribute("data-key") !== key) {
        box.innerHTML = opts.map(function (m) {
          return '<button type="button" data-act="start" data-min="' + m + '"' + (m === d ? ' class="pri"' : "") + ">" + esc(fmtDur(m)) + "</button>";
        }).join("");
        box.setAttribute("data-key", key);
      }
      var su = $("hold-start-until");
      if (!su.value) su.value = hhmm(new Date(now + d * 60000));
    }
    document.querySelectorAll("#hold button[data-act]").forEach(function (b) { b.disabled = !usable || holdBusy; });

    var planned = (room.holds || []).filter(function (x) { return !x.active; });
    $("plans").innerHTML = planned.map(function (p) {
      return '<div class="plan"><span>' + t("planned", { day: esc(shortDay(p.start)), start: "<b>" + fmtTime(p.start) + "</b>", end: "<b>" + fmtTime(p.end) + "</b>", t: fmtT(p.target) }) +
        '</span><button type="button" data-cancel="' + esc(p.id) + '" aria-label="' + esc(t("remove")) + '">×</button></div>';
    }).join("");
    $("plan-toggle").hidden = planOpen || planned.length >= 4;
    $("plan-form").hidden = !planOpen;
    if (planOpen) $("plan-temp").textContent = fmt1(planTemp) + " °C";
  }

  function holdError(res) {
    if (res.status === 429) return t("err_rate");
    if (res.status === 0) return t("err_offline");
    var code = res.body && res.body.error;
    if (code && I18N.ro["e_" + code]) return t("e_" + code, { h: room.hold_max_hours || 12 });
    return t("e_hold");
  }

  function holdPost(body, okMsg) {
    holdBusy = true;
    renderHold();
    return post("/hold", body).then(function (res) {
      holdBusy = false;
      if (res.ok) {
        onRoom(res.body.room);
        if (okMsg) showToast(okMsg(res.body.room));
      } else {
        if (res.status === 401) return load();
        if (res.status === 404) return showInvalid();
        if (body.action !== "plan") showToast(esc(holdError(res)), false, true);
        renderHold();
      }
      return res;
    });
  }

  function endMsg(key) {
    return function (r) {
      var h = (r.holds || []).filter(function (x) { return x.active; })[0];
      return h ? t(key, { time: fmtTime(h.end) }) : "";
    };
  }

  $("hold").addEventListener("click", function (ev) {
    var b = ev.target.closest("button[data-act]");
    if (b && !b.disabled) {
      var act = b.getAttribute("data-act"), min = parseInt(b.getAttribute("data-min"), 10);
      if (act === "start") holdPost({ action: "start", minutes: min }, endMsg("ok_started"));
      else if (act === "start-until") { if ($("hold-start-until").value) holdPost({ action: "start", until: $("hold-start-until").value }, endMsg("ok_started")); }
      else if (act === "extend") holdPost({ action: "extend", minutes: min }, endMsg("ok_until"));
      else if (act === "until") { if ($("hold-until").value) holdPost({ action: "until", until: $("hold-until").value }, endMsg("ok_until")); }
      else if (act === "stop") holdPost({ action: "stop" }, function () { return t("ok_stopped"); });
      return;
    }
    var x = ev.target.closest("button[data-cancel]");
    if (x) holdPost({ action: "cancel", id: x.getAttribute("data-cancel") }, function () { return t("ok_cancelled"); });
  });

  $("plan-toggle").addEventListener("click", function () {
    var from = Date.now() + 5 * 60000;
    (room.holds || []).forEach(function (h) { from = Math.max(from, new Date(h.end).getTime()); });
    var start = new Date(Math.ceil(from / 3600000) * 3600000);
    $("plan-start").value = hhmm(start);
    $("plan-end").value = hhmm(new Date(start.getTime() + (room.hold_default_minutes || 120) * 60000));
    planTemp = room.default_target != null ? room.default_target : 21;
    $("plan-err").textContent = "";
    planOpen = true;
    renderHold();
  });
  $("plan-cancel").addEventListener("click", function () { planOpen = false; renderHold(); });
  function planStep(dir) {
    var c = room.climate, st = c.step || 0.5;
    planTemp = Math.min(c.max, Math.max(c.min, Math.round((planTemp + dir * st) / st) * st));
    renderHold();
  }
  $("plan-minus").addEventListener("click", function () { planStep(-1); });
  $("plan-plus").addEventListener("click", function () { planStep(1); });
  $("plan-form").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var start = $("plan-start").value, end = $("plan-end").value;
    if (!start || !end) { $("plan-err").textContent = t("e_bad_time"); return; }
    holdPost({ action: "plan", start: start, until: end, temperature: planTemp }, function (r) {
      var p = (r.holds || []).filter(function (x) { return !x.active && hhmm(new Date(x.start)) === start; })[0];
      return t("ok_planned", { day: p ? esc(shortDay(p.start)) : "", time: start });
    }).then(function (res) {
      if (res && res.ok) { planOpen = false; renderHold(); }
      else if (res && res.status !== 401 && res.status !== 404) $("plan-err").textContent = holdError(res);
    });
  });

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
    var pb = ev.target.closest("button[data-preset]");
    if (pb && !pb.disabled) {
      var key = pb.getAttribute("data-preset");
      pb.disabled = true;
      return post("/preset", { preset: key }).then(function (res) {
        if (res.ok) { onRoom(res.body.room); showToast(esc(t("ok_preset_" + key))); }
        else if (res.status === 401) load();
        else showToast(esc(res.status === 429 ? t("err_rate") : t("err_generic")), false, true);
        if (room) renderControl();
      });
    }
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
