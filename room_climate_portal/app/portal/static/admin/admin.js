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

  // In-page dialog. Browser prompt()/confirm() are blocked inside the HA Ingress
  // panel and the HA mobile app, so nothing here relies on them.
  function dialog(opts) {
    var d = $("#dlg");
    $("#dlg-title").textContent = opts.title;
    $("#dlg-text").textContent = opts.text || "";
    $("#dlg-err").textContent = "";
    var input = $("#dlg-input");
    input.hidden = !opts.input;
    input.value = "";
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
    var b = ev.target.closest("[data-rotate]");
    if (!b) return;
    var id = b.getAttribute("data-rotate");
    dialog({
      title: "Replace the QR code for " + id + "?", text: "The printed code stops working immediately. Print the new one afterwards.",
      okLabel: "Replace code", danger: true,
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
