# Changelog

## 0.16.0
- **Early stop**: heating stops before an event ends, as long as the room loses at most `coast_drop` °C (from its τ).
- **Dynamic setback**: before an event within `setback_horizon_hours`, rooms are kept above the lowest temperature
  from which preheating fits in `max_preheat_hours`; otherwise only frost protection.
- **On track / late** while preheating, with one notification per late event.
- **Forecast** (`weather_entity`): estimates and setback floors use the forecast of each preheat window.
- **Estimated start on the room pages**: one switch makes preconditioning use each room's estimated lead.
- **HA sensors** `sensor.heating_<circuit>_next_start` and `sensor.heating_<circuit>_decision`.
- **Notifications** (`notify_service`, else persistent notifications): late preheating, a circuit that did not switch,
  a stopped test, offline room sensors.
- **Tests A then B** scheduled from the Heating control card; runs during a test are noted "Test A" / "Test B".
- **Charts**: last 24 h per circuit and per run in the Heating log.
- **Watchdog blueprint**: fallback automations when the heartbeat is missing after a Home Assistant restart.
- New options: `coast_drop`, `max_coast_minutes`, `max_preheat_hours`, `setback_horizon_hours`, `late_margin_minutes`,
  `weather_entity`, `notify_service`.

## 0.15.0
- **Heating control** on the Plant tab, one card per boiler, **Shadow** (default, shows what it would do) or
  **Active** (switches the circuit: preset Winter / Summer). A circuit opens for the preheat window from the
  start estimate, while an event runs in one of its rooms (hysteresis around the target) and for frost protection;
  at most one switch every `min_switch_minutes`. Room valves follow their room.
- **Takeover automations** per boiler: Active turns them off, Shadow turns them back on. If one is turned on
  while the boiler is Active, the add-on goes back to Shadow instead of fighting it.
- **Heartbeat** `sensor.heating_controller_heartbeat` every minute, and the **watchdog blueprint**
  `heating_watchdog.yaml`: no heartbeat for 15 minutes turns the takeover automations back on and notifies.
- New options: `frost_temp` (10 °C), `hysteresis` (0.3 °C), `min_switch_minutes` (10).
- Admin API: `GET /api/control`, `POST /api/control/boilers/{boiler}`.

## 0.14.0
- Only the **first circuit of each boiler** is used, under the entity ids renamed in HA: `climate.zone1` →
  `climate.sala_plen1`, `climate.zone2` → `climate.parter1`, `climate.etaj_1` → `climate.etaj1`,
  `climate.ariston_b4bfe94a5d38_1` → `climate.demisol1`.
- On start, `/data/topology.json` drops the second and third circuits seeded by 0.12 and moves room links to the new ids.
  Logged samples, heating runs and estimates in `/data/heating.db` move to the new ids too.
- Circuits are shown under their name in HA (a name set in the entity registry wins) in the Plant tab and the start
  estimates.

## 0.13.0
- **Start estimates** at the top of the Plant tab, one row per circuit. Each row shows the room that needs heat
  first, its next event and the estimated start, with the calculation spelled out: dead time, heating rate, share
  of the boiler when other circuits heat at the same time, and margin. It also shows the room temperature now and
  predicted at the start, how many runs the estimate rests on, and the fixed lead time used today for comparison.
  Rooms with events but no circuit are listed.
- The model is learned from the heat runs (dead time and rate per room, rate scaled to one circuit alone on its
  boiler, following the outdoor temperature once there is enough spread) and the cool runs (τ). Without runs it
  uses 40 min and 1.5 °C/h.
- **Estimates vs what happened** on the Heating log tab: the last estimate before each event's estimated start,
  then when the circuit really opened, the room temperature at the event start and when the target was reached.
  Stored in the `estimates` table of `/data/heating.db`.
- Admin API: `GET /api/estimates`, `GET /api/estimates/history`.
- Shown only: preconditioning still uses the fixed lead time.

## 0.12.0
- **Plant tab** on the admin page: the boilers with their circuits live (open/closed, preset, heat request), and a
  table linking each room to its boiler circuit, valve and temperature sensor, with a heating choice (calendar events,
  frost protection only, not heated) and a comfort temperature. Unset values are guessed from the room's Area.
  Saved in `/data/topology.json`; changes appear in Recent changes.
- **Heating log**: room and outdoor temperatures, circuits and valves are recorded in `/data/heating.db` (SQLite,
  on change and at least every 10 minutes, kept 120 days, then as 15-minute averages). Each heating run of a circuit
  is measured per room (dead time, heating rate, time to comfort, open circuits on the boiler, outdoor temperature),
  and each cooling run of 2 h or more gives the room's time constant τ. The **Heating log** tab lists the runs and
  takes a note per run.
- Admin API: `GET /api/plant`, `POST /api/plant/rooms/{room}`, `GET /api/sessions`, `POST /api/sessions/{id}/note`,
  `GET /api/samples`.
- No change to preconditioning, holds or the room pages.

## 0.11.0
- **Lead time 120 min for all rooms** out of the box. New admin button **Lead time: all rooms** sets one value for
  every room (it replaces any single-room value); the per-room field still overrides it. Lead-time helpers in HA and
  the `default_lead_minutes` / `lead_time_label` options are no longer used.
- **Print text** under each QR code is now yours to set: **Print text: all rooms** (default "Scanează- Termostat")
  or per room with **Edit** in the QR code column. Saved in `/data/room_settings.json`.

## 0.10.0
- **Lead time per room on the admin page.** The "Calendar & lead time" column has a "Start … min before events"
  field (0 to 600 min) and a Reset button. Preconditioning, the room page and `sensor.<room>_next_precondition`
  use it right away; it is saved in `/data/room_settings.json` and logged in Recent changes.
- Calendar events no longer set the lead time: a `precondition:` line in an event description is ignored.
  Rooms without an admin value keep using their lead-time entity, then the `default_lead_minutes` option (45 min).
- A room without a lead-time entity is no longer flagged as an issue.

## 0.9.4
- The heating glow, flame and "Încălzire" label (room page and admin) now appear only while the thermostat
  reports `hvac_action: heating`. Heat mode, the Încălzire preset or a running timer alone no longer show it.

## 0.9.3
- Starting manual heating from the room page (1 h / 2 h / 4 h or "Sau până la … Pornește") now also switches the
  thermostat to the Încălzire preset (`home`), and to Heat if it was off, not only the timer. Planned periods do the same
  and then set their own temperature.

## 0.9.2
- The heating look (warm glow, flame, "Încălzire" label, admin badge) is shown whenever Încălzire / manual heating
  is on, even if the thermostat reports its valve as idle at that moment.

## 0.9.1
- Thermostats that don't report whether they are heating (no `hvac_action`, common on TRVs): the room page no longer
  says "Temperatură atinsă". Heating (and the warm glow, also on the admin page) is shown while Încălzire/manual heating
  is on or the room is below target; with Eco active it says "Eco", otherwise "Pornit".
- If the thermostat reports no room temperature, a temperature sensor in the same area is used for "Acum"
  (or set `temperature:` per room in rooms.yaml).

## 0.9.0
- **View only** per room (switch in the PIN column of the admin page) and **View only: all rooms** at the top.
  Guests still see the room page (temperature, heating, events) but every control is hidden and the server
  refuses any change from the room page. The admin page can still change everything. New filter "View only".

## 0.8.1
- Visual "heating on" effect. Room page: the thermostat card glows warm, the dial arc pulses and the flame flickers
  while the thermostat is heating. Admin page: heating rooms get an orange stripe and tint, a flickering flame next to
  the name and an orange "Heating" badge; on phones the room card glows. Animations stop if the phone asks for reduced motion.

## 0.8.0
- Admin page: two clear columns. **Thermostat now** (read-only live state: mode, preset, target, room temperature,
  heating/idle, guest manual heating, effective range and whether the thermostat itself limits it) and
  **Room settings** (the controls: saved settings, applied now and restored after events). It also says when the
  thermostat currently differs from the saved settings.
- Changing one room setting no longer copies the live state into the others (e.g. during guest heating).
- Default `min_temp` is now 16 °C. Existing installs keep their saved value: change `min_temp` in the add-on Configuration.

## 0.7.1
- When manual heating ends (timer or **Încheie**), the thermostat switches to the **Eco** preset (`away`).
  Rooms whose thermostat has no such preset go back to their admin-page settings, as before.
  Option `manual_end: room_settings` keeps the old behaviour everywhere. Calendar events still end with the room settings.

## 0.7.0
- Room page: guests can no longer turn a thermostat off. Instead of the mode buttons there are two preset buttons:
  **Încălzire** (the thermostat's `home` preset, starts manual heating with its timer) and **Eco** (`away` preset,
  ends manual heating). Both switch an "off" thermostat on. Presets are set with `guest_preset_heat` / `guest_preset_eco`.
- Turning a thermostat off is only possible from the admin page (also when `allow_mode_change` is on).
- Manual heating texts say "ends" instead of "turns off": at the end the room goes back to its admin-page settings.

## 0.6.4
- Admin page (desktop): the title bar with the buttons, the search/filters and the table header stay at the top while scrolling.

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
