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

  function row(r) {
    var issues = (r.issues || []).map(function (i) { return '<span class="issue">' + esc(i) + "</span>"; }).join(" ");
    var ev = r.next_event;
    return "<tr data-id=\"" + esc(r.id) + "\">" +
      "<td><b>" + esc(r.name) + "</b><div class=\"muted\">" + esc(r.subtitle) + "</div><div class=\"mono muted\">" + esc(r.id) + "</div>" + (issues ? "<div>" + issues + "</div>" : "") + "</td>" +
      "<td class=\"mono\">" + esc(r.climate || "–") + "<div class=\"muted\">" + esc(r.hvac_mode || "") + " · " + num(r.min_temp) + "–" + num(r.max_temp) + " °C</div></td>" +
      "<td>" + num(r.current) + " / <b>" + num(r.target) + "</b> °C</td>" +
      "<td class=\"mono\">" + esc(r.calendar || "–") + "<div>" + esc(r.lead_time || "default") + " → " + esc(r.lead_minutes) + " min</div></td>" +
      "<td>" + (ev ? esc(ev.summary) + "<div class=\"muted\">" + time(ev.start) + "</div><div class=\"muted\">precondition " + time(ev.precondition_start) + "</div>" : "<span class=\"muted\">none</span>") + "</td>" +
      "<td><a href=\"print?room=" + encodeURIComponent(r.id) + "\" target=\"_blank\" rel=\"noopener\"><img class=\"qr\" alt=\"QR\" src=\"qr/" + encodeURIComponent(r.id) + ".svg?g=" + r.generation + "\"></a>" +
      "<div class=\"url\">" + esc(r.url) + "</div><div class=\"muted\">" + r.open_pages + " open now</div></td>" +
      "<td><div>" + (r.pin_enabled ? "<b>On</b>" : "<span class=\"muted\">Off</span>") + "</div>" +
      "<div class=\"btns\"><button class=\"small\" data-pin=\"" + esc(r.id) + "\">" + (r.pin_enabled ? "Change PIN" : "Set PIN") + "</button>" +
      (r.pin_enabled ? "<button class=\"small\" data-nopin=\"" + esc(r.id) + "\">Remove PIN</button>" : "") +
      "<button class=\"small\" data-rotate=\"" + esc(r.id) + "\">New QR code</button></div></td></tr>";
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
      $("#rooms tbody").innerHTML = rooms.map(row).join("");
      $("#empty").hidden = rooms.length > 0;
      $("#rooms").hidden = rooms.length === 0;
    });
    fetch("api/audit?limit=50").then(function (r) { return r.json(); }).then(function (rows) {
      $("#audit tbody").innerHTML = rows.map(function (a) {
        var change = a.action === "set_temperature" ? num(a.old) + " → " + num(a.new) + " °C"
          : a.action === "rotate_token" ? "QR code replaced" : esc(a.action) + " " + esc(a.new || "");
        return "<tr><td>" + new Date(a.ts * 1000).toLocaleString([], { timeZone: TZ }) + "</td><td>" + esc(a.room) + "</td><td>" + change + "</td><td class=\"mono\">" + esc(a.client) + "</td></tr>";
      }).join("") || '<tr><td colspan="4" class="muted">No changes yet.</td></tr>';
    });
  }

  function askPin(label) {
    var pin = prompt(label + "\nEnter a 4-8 digit PIN (leave empty to remove the PIN):", "");
    if (pin === null) return null;
    pin = pin.trim();
    if (pin && !/^\d{4,8}$/.test(pin)) { alert("The PIN must be 4 to 8 digits."); return null; }
    return { pin: pin || null };
  }
  function postJson(url, body) {
    return fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { if (!r.ok) return r.text().then(function (t) { alert("Failed: " + t); }); });
  }

  document.addEventListener("click", function (ev) {
    var p = ev.target.closest("[data-pin]");
    if (p) {
      var v = askPin("PIN for room " + p.getAttribute("data-pin") + ".");
      if (v) postJson("api/rooms/" + encodeURIComponent(p.getAttribute("data-pin")) + "/pin", v).then(load);
      return;
    }
    var n = ev.target.closest("[data-nopin]");
    if (n) {
      if (confirm("Remove the PIN for " + n.getAttribute("data-nopin") + "? Anyone with the QR code can then change the temperature.")) {
        postJson("api/rooms/" + encodeURIComponent(n.getAttribute("data-nopin")) + "/pin", { pin: null }).then(load);
      }
      return;
    }
    var b = ev.target.closest("[data-rotate]");
    if (!b) return;
    var id = b.getAttribute("data-rotate");
    if (!confirm("Replace the QR code for " + id + "? The printed code stops working immediately.")) return;
    fetch("api/rooms/" + encodeURIComponent(id) + "/rotate", { method: "POST" }).then(load);
  });
  $("#pin-all").addEventListener("click", function () {
    var v = askPin("Same PIN for ALL rooms (replaces every room's PIN).");
    if (v) postJson("api/pin_all", v).then(load);
  });
  $("#reload").addEventListener("click", function () {
    this.disabled = true;
    var btn = this;
    fetch("api/reload", { method: "POST" }).then(function () { btn.disabled = false; load(); });
  });
  load();
  setInterval(load, 30000);
})();
