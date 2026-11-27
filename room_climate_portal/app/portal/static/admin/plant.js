(function () {
  "use strict";
  // The Plant and Heating log views of the admin page (#plant, #sessions). Rooms stays in admin.js.
  function $(s) { return document.querySelector(s); }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function num(v, d) { return v == null ? "–" : Number(v).toFixed(d == null ? 1 : d); }
  function flash(msg) {
    var el = $("#flash");
    el.textContent = msg;
    el.hidden = false;
    clearTimeout(flash.t);
    flash.t = setTimeout(function () { el.hidden = true; }, 5000);
  }
  function post(path, body) {
    return fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (b) {
          if (!r.ok) throw new Error(b.error || "Error " + r.status);
          return b;
        });
      });
  }

  // ------------------------------------------------------------ views
  var VIEWS = ["rooms", "plant", "sessions"];
  function current() {
    var h = location.hash.replace("#", "");
    return VIEWS.indexOf(h) > 0 ? h : "rooms";
  }
  function show() {
    var v = current();
    VIEWS.forEach(function (n) { $("#view-" + n).hidden = n !== v; });
    $(".top .actions").hidden = v !== "rooms";
    document.querySelectorAll(".views a").forEach(function (a) { a.classList.toggle("on", a.getAttribute("data-view") === v); });
    if (v === "plant") loadPlant();
    if (v === "sessions") loadPlant().then(loadSessions);
  }
  window.addEventListener("hashchange", show);

  // ------------------------------------------------------------ plant
  var PLANT = null;
  var CATEGORY = { event: "From calendar events", frost: "Frost protection only", none: "Not heated" };
  function roomName(id) {
    var r = PLANT && PLANT.rooms.filter(function (x) { return x.room_id === id; })[0];
    return r ? r.name : id;
  }
  function circuitLabel(c) {
    return (c.zone != null ? "Circuit " + c.zone : c.name) + " · " + c.entity_id;
  }
  function loadPlant() {
    return fetch("api/plant").then(function (r) { return r.json(); }).then(function (p) {
      PLANT = p;
      if (current() === "plant") renderPlant();
      fillCircuitFilter();
    });
  }
  function renderPlant() {
    $("#boilers").innerHTML = PLANT.boilers.map(function (b) {
      return '<section class="boiler"><h3>' + esc(b.name) + "<span>" + b.open + " of " + b.circuits.length + " circuits open</span></h3>" +
        b.circuits.map(function (c) {
          var state = !c.available ? "unavailable" : c.open ? "Open" : "Closed";
          return '<div class="circ"><span class="dot ' + (c.open ? "on" : "") + '"></span><div><b>' + esc(circuitLabel(c)) + "</b></div>" +
            "<small>" + esc(state) + " · preset " + esc(c.preset_mode || "–") + " · heat request " + num(c.heat_request, 0) +
            " · target " + num(c.target) + " °C</small>" +
            "<small>" + (c.rooms.length ? "Heats " + c.rooms.map(function (id) { return esc(roomName(id)); }).join(", ") : "No room linked yet") + "</small></div>";
        }).join("") + "</section>";
    }).join("") || '<p class="empty">No boilers. Add them to <code>/data/topology.json</code>.</p>';

    var focused = document.activeElement && document.activeElement.closest && document.activeElement.closest("#links");
    if (focused) return;  // don't redraw under an open menu
    $("#links tbody").innerHTML = PLANT.rooms.map(linkRow).join("");
  }
  function opt(value, label, selected) {
    return '<option value="' + esc(value) + '"' + (selected ? " selected" : "") + ">" + esc(label) + "</option>";
  }
  function guessTag(r, field) { return r.guessed.indexOf(field) !== -1 ? '<span class="guess">guess</span>' : ""; }
  function select(r, field, options) {
    return '<select data-room="' + esc(r.room_id) + '" data-field="' + field + '" aria-label="' + field + " " + esc(r.name) + '">' + options + "</select>" + guessTag(r, field);
  }
  function linkRow(r) {
    var boilers = opt("", "–", !r.boiler) + PLANT.boilers.map(function (b) { return opt(b.id, b.name, b.id === r.boiler); }).join("");
    var circuits = opt("", "–", !r.circuit) + PLANT.boilers.filter(function (b) { return !r.boiler || b.id === r.boiler; })
      .map(function (b) { return b.circuits.map(function (c) { return opt(c.entity_id, (r.boiler ? "" : b.name + " · ") + circuitLabel(c), c.entity_id === r.circuit); }).join(""); }).join("");
    var valves = opt("", "No valve", !r.valve) + PLANT.candidates.valves.map(function (e) { return opt(e, e, e === r.valve); }).join("");
    var sensorList = PLANT.candidates.sensors.slice();
    if (r.temperature && sensorList.indexOf(r.temperature) === -1) sensorList.unshift(r.temperature);
    var sensors = opt("", "–", !r.temperature) + sensorList.map(function (e) { return opt(e, e, e === r.temperature); }).join("");
    var cats = Object.keys(CATEGORY).map(function (k) { return opt(k, CATEGORY[k], k === r.category); }).join("");
    var issues = (r.issues || []).map(function (i) { return '<span class="issue">' + esc(i.replace(/_/g, " ")) + "</span>"; }).join(" ");
    return "<tr><td><b>" + esc(r.name) + '</b><div class="muted">' + esc(r.subtitle) + "</div>" + issues + "</td>" +
      "<td>" + select(r, "boiler", boilers) + "</td>" +
      "<td>" + select(r, "circuit", circuits) + "</td>" +
      "<td>" + select(r, "valve", valves) + (r.valve ? '<div class="muted">' + (r.valve_open ? "open" : "closed") + "</div>" : "") + "</td>" +
      "<td>" + select(r, "temperature", sensors) + "</td>" +
      "<td>" + select(r, "category", cats) + "</td>" +
      '<td><input type="number" step="0.5" min="5" max="30" data-room="' + esc(r.room_id) + '" data-field="comfort" value="' + (r.comfort == null ? "" : r.comfort) + '" placeholder="' + num(PLANT.default_target) + '" aria-label="Comfort ' + esc(r.name) + '"> °C</td>' +
      '<td class="mono">' + (r.temp_now == null ? "–" : num(r.temp_now) + " °C") + "</td></tr>";
  }
  $("#links").addEventListener("change", function (ev) {
    var el = ev.target.closest("[data-field]");
    if (!el) return;
    var body = {};
    body[el.getAttribute("data-field")] = el.value === "" ? null : el.value;
    post("api/plant/rooms/" + encodeURIComponent(el.getAttribute("data-room")), body).then(function (p) {
      PLANT = p;
      el.blur();
      renderPlant();
    }).catch(function (e) { flash(roomName(el.getAttribute("data-room")) + ": " + e.message); loadPlant(); });
  });

  // ------------------------------------------------------------ heating log
  var TZ;
  function when(ts) { return new Date(ts * 1000).toLocaleString([], { timeZone: TZ, dateStyle: "short", timeStyle: "short" }); }
  function minutes(m) {
    if (m == null) return "–";
    m = Math.round(m);
    return m >= 60 ? Math.floor(m / 60) + " h " + (m % 60) + " min" : m + " min";
  }
  function fillCircuitFilter() {
    var sel = $("#sess-circuit");
    if (!PLANT || sel.options.length > 1) return;
    PLANT.boilers.forEach(function (b) {
      b.circuits.forEach(function (c) { sel.insertAdjacentHTML("beforeend", opt(c.entity_id, b.name + " · " + circuitLabel(c), false)); });
    });
  }
  function loadSessions() {
    var c = $("#sess-circuit").value;
    return fetch("api/sessions?limit=300" + (c ? "&circuit=" + encodeURIComponent(c) : "")).then(function (r) { return r.json(); }).then(function (rows) {
      var boilerName = {};
      (PLANT ? PLANT.boilers : []).forEach(function (b) { boilerName[b.id] = b.name; });
      $("#sess-empty").hidden = rows.length > 0;
      $("#sess-count").textContent = rows.length + " rows";
      $("#sessions tbody").innerHTML = rows.map(function (s) {
        return "<tr><td>" + when(s.start) + "</td>" +
          '<td class="kind-' + esc(s.kind) + '">' + (s.kind === "heat" ? "Heat" : "Cool") + '<div class="muted">' + esc((s.end_reason || "").replace(/_/g, " ")) + "</div></td>" +
          "<td>" + esc(boilerName[s.boiler] || s.boiler || "") + '<div class="mono muted">' + esc(s.circuit) + "</div></td>" +
          "<td>" + esc(s.room ? roomName(s.room) : "–") + "</td>" +
          "<td>" + minutes((s.end - s.start) / 60) + "</td>" +
          '<td class="mono">' + num(s.t_start) + " → " + num(s.t_end) + (s.target != null ? '<div class="muted">comfort ' + num(s.target) + "</div>" : "") + "</td>" +
          '<td class="mono">' + num(s.outdoor) + " °C</td>" +
          '<td class="mono">' + (s.n_open_max == null ? "–" : s.n_open_max + " max · " + num(s.n_open_avg) + " avg") + "</td>" +
          "<td>" + minutes(s.dead_time_min) + "</td>" +
          '<td class="mono">' + (s.rate_c_per_h == null ? "–" : num(s.rate_c_per_h, 2) + " °C/h") + "</td>" +
          "<td>" + minutes(s.reached_min) + "</td>" +
          '<td class="mono">' + (s.tau_h == null ? "–" : num(s.tau_h) + " h") + "</td>" +
          '<td class="note"><input type="text" maxlength="200" value="' + esc(s.note || "") + '" data-session="' + s.id + '" aria-label="Note"> <button type="button" class="small" data-save="' + s.id + '">Save</button></td></tr>';
      }).join("");
    });
  }
  $("#sess-circuit").addEventListener("change", loadSessions);
  $("#sess-reload").addEventListener("click", loadSessions);
  $("#sessions").addEventListener("click", function (ev) {
    var b = ev.target.closest("button[data-save]");
    if (!b) return;
    var id = b.getAttribute("data-save");
    var input = document.querySelector('#sessions input[data-session="' + id + '"]');
    post("api/sessions/" + id + "/note", { note: input.value }).then(function () { flash("Note saved"); })
      .catch(function (e) { flash(e.message); });
  });

  fetch("api/status").then(function (r) { return r.json(); }).then(function (s) { TZ = s.time_zone || undefined; }).catch(function () {});
  show();
  setInterval(function () {
    if (current() === "plant") loadPlant();
  }, 30000);
})();
