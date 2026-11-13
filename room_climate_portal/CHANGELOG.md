# Changelog

## 0.6.3
- Admin page: a **Preset** menu next to the mode for thermostats that expose presets (away, eco, comfort, …).
- The chosen preset is part of the room settings: after events and timers the thermostat goes back to that mode
  and preset (e.g. Heat · Away). Setting a temperature on the admin page replaces the remembered preset.

## 0.6.2
- QR codes on the print sheet are exactly 4 × 4 cm (print at 100% / "Actual size").
- **Print all QR codes** opens the sheet and the print dialog at once; rooms sorted by floor and name.
- **Print shown (n)** prints only the rooms matching the current search/filter. Clicking a room's QR prints just that room.

## 0.6.1
- Fix: QR codes on the print sheet could not be scanned. The sheet shrank the code without scaling it, so
  only its top-left part was printed. Codes now scale to their box, have the standard white quiet zone and a
  white background (also in dark mode). Reprint any sheets printed before.

## 0.6.0
- QR links are now readable by default, built from the floor and the room name:
  `…/room/demisol-d01-sala-repetitii-inchinare` (accents removed, lower case, unique per room).
  QR codes printed earlier keep working until you replace that room's code. Reprint to get the new links.
- The readable code is fixed when a room is first seen, so renaming an area in HA does not break the sticker.
  **Readable code** on the admin page rebuilds it from the current name.
- Readable links can be guessed by anyone who knows the room name: the admin page flags rooms without a PIN.
  Option `readable_codes: false` goes back to random codes.

## 0.5.1
- Admin page on phones (HA app): one card per room with large − / + buttons and the mode menu up front,
  a "Details" button for thermostat, calendar, next event, QR code and PIN/code actions, a sticky search
  bar with swipeable filters, compact "Recent changes", and dialogs as bottom sheets.

## 0.5.0
- The temperature and mode set on the admin page become the room's settings. After every manual period,
  planned period and calendar event (also when an event is deleted while it runs) the thermostat goes back to them.
  Shown per room as "After events & timers: …".
- Rooms without admin settings: off or setback, as before (`hold_end_action`). New option `restore_after_events` (on).
- Changing the temperature on the admin page no longer switches an "off" thermostat on; use the mode menu.

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
