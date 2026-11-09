# Changelog

## 0.4.2
- Admin page: set each room's target temperature (− / +) and climate mode (Off, Heat, …) right in the room list.
  Staff changes have no rate limit and no auto-off timer; they are logged as "admin" in Recent changes.
  Guests still cannot change the mode unless `allow_mode_change` is on.

## 0.4.1
- Admin page: search box (room name, floor, room id, code, thermostat or calendar entity; accents ignored,
  so "sala tehnica" finds "Sala tehnică") and filters: Heating on, Manual / planned, Event in 24 h,
  PIN on, No PIN, Problems. Recent changes follow the same filter.
- Admin page shows "Manual until HH:MM" and planned periods per room, and readable manual-heating entries in Recent changes.

## 0.4.0
- Manual heating from the room page: start for 1 h / 2 h / 4 h or until a chosen hour; it turns itself off
  after 2 h by default. While on: +30 min, +1 h, turn off at another hour, or turn off now.
- Changing the temperature on the page starts manual heating (and turns on a thermostat that was off).
- Plan a period (from–until, own temperature) within the next 24 h; listed on the room page and the Program page.
- New options: `hold_default_minutes`, `hold_max_hours`, `hold_end_action` (off / setback), `setback_temp`.
  Heating is never turned off while a calendar event is preconditioning or running in that room.

## 0.3.1
- Browsers and the HA app now always load the current admin and room-page scripts after an update
  (versioned asset URLs, revalidated static files). Before, an old cached script could hide new buttons.

## 0.3.0
- Custom QR code per room: on the admin page, **Custom code** sets the room link to `<public_url>/camera/<your code>`
  (4-64 letters, digits, - or _; unique; case-insensitive check). **New random code** goes back to a random one.

## 0.2.1
- Admin page: Set PIN, PIN for all rooms, Remove PIN and New QR code now use an in-page dialog.
  Browser pop-ups are blocked inside the HA panel and the HA mobile app, so those buttons did nothing before.

## 0.2.0
- All guest pages and APIs live under `base_path` (default `/camera`), so they can be published on the
  same domain and port as HA: `https://ha.example.ro/camera/<code>`. **QR codes change format: reprint them.**
- Optional per-room PIN, set or removed on the admin page (or one PIN for all rooms), with lockout after
  wrong attempts and a remembered unlock per phone.
- Docs: routing `/camera/` through the NGINX SSL proxy add-on or a Cloudflare Tunnel.

## 0.1.0
- First version: per-room guest page opened by QR code (Romanian by default, English switch, light/dark),
  live temperature over Server-Sent Events, setpoint control with limits and rate limiting,
  room schedule from HA calendars with precondition start times, admin page in HA with QR codes,
  token rotation, printable QR sheet and audit log, `sensor.<room>_next_precondition` for automations.
