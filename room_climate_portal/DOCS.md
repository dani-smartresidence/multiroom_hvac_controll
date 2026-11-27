# Room Climate Portal

Each room gets a QR code. Scanning it opens a mobile page (Romanian by default, English on a tap,
light or dark following the phone) where the occupant sees the live temperature, changes the
setpoint within limits, and sees the room's upcoming events with the time preconditioning starts
before each one. Everything comes from Home Assistant; the add-on never keeps its own schedule.

## 1. Prepare Home Assistant (once per room)

| What | How |
| --- | --- |
| Area | One Area per room (Settings → Areas). Put the label **`qr_room`** on it. |
| Thermostat | The room's `climate` entity assigned to that Area (directly or through its device). |
| Calendar | One calendar per room in the Area, e.g. a Local Calendar `calendar.camera_204`. |
| Lead time | Set on the admin page: **Lead time: all rooms** (120 min out of the box) and, per room, the "Start … min before events" field in the **Calendar & lead time** column. Lead-time helpers in HA are no longer read. |
| Humidity (optional) | Any humidity sensor in the Area is shown automatically. |

An event description may carry one optional line:

```
target: 22          # target temperature for this event (else the "Default event target" option)
```

The calendar does not set the lead time: a `precondition: 60` line in an event is ignored. Change the
room's lead time on the admin page instead.

## 2. Configure the add-on

- **public_url**: your HA address without a path, e.g. `https://ha.voxdomini.ro`.
- **base_path**: `/camera` (default). QR codes point to `https://ha.voxdomini.ro/camera/<code>`.
- **trust_proxy_headers**: turn on when a reverse proxy sits in front (see section 3), so rate limits
  and PIN lockouts see each phone's real address.
- **min_temp / max_temp / temp_step**: limits for guests (per-room overrides in `rooms.yaml`).
- **default_language**: `ro` or `en`.
- **pin_remember_hours / pin_max_attempts / pin_lockout_minutes**: PIN behaviour (PINs are set on the admin page).
- **publish_precondition_sensors**: creates `sensor.<area_id>_next_precondition` (timestamp) with
  the attributes `target_temperature`, `event_summary`, `event_start`, `climate_entity`.

**Print text**: the line under each QR code on the print sheet. Set it for every room with **Print text: all rooms**
(default "Scanează- Termostat") or per room with **Edit** next to "Print text" in the QR code column.

Per-room overrides: copy `rooms.example.yaml` to `/addon_configs/<id>_room_climate_portal/rooms.yaml`.

## 3. Publish the pages under your HA domain (same port 443)

The add-on serves everything below `/camera` on its port 8080. Whatever answers on 443 for
`ha.voxdomini.ro` forwards `/camera/` there and everything else to HA as before.
Use the add-on's **Hostname** from its Info page (e.g. `a0d7b954-room-climate-portal`) as the upstream;
the HA Green's LAN IP with port 8080 works too.

### With the official "NGINX Home Assistant SSL proxy" add-on (works on HA Green)

1. Create `/share/nginx_proxy_default_camera.conf` (Samba or File editor add-on):

   ```nginx
   location /camera/ {
       proxy_pass http://<add-on hostname>:8080;
       proxy_http_version 1.1;
       proxy_set_header Host $host;
       proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       proxy_set_header X-Forwarded-Proto $scheme;
       proxy_buffering off;          # live updates (Server-Sent Events)
       proxy_read_timeout 1h;
   }
   ```
2. In the NGINX add-on configuration set `customize: active: true` (default pattern
   `nginx_proxy_default*.conf` picks the file up) and restart the NGINX add-on.
3. In this add-on set `trust_proxy_headers: true`.

If HA currently terminates HTTPS itself (`ssl_certificate` under `http:` in configuration.yaml with the
router forwarding 443 → 8123), switching to the NGINX add-on means: install it with your domain and the
certificate files from `/ssl`, remove the `ssl_*` lines from `http:`, add
`use_x_forwarded_for: true` and `trusted_proxies: [172.30.33.0/24]` under `http:`, restart HA,
and forward the router's 443 to the HA Green's port 443.

### With the Cloudflared add-on (Cloudflare Tunnel)

No NGINX needed. Set `trust_proxy_headers: true` in this add-on.

- **Tunnel managed in the Cloudflare dashboard** (the Cloudflared add-on has `tunnel_token` set):
  Zero Trust → Networks → Tunnels → your tunnel → Public Hostname → **Add a public hostname**:
  subdomain `ha`, domain `voxdomini.ro`, path `camera/*`, service **HTTP** `172.30.32.1:8080`.
  Make sure this entry is listed **above** the existing `ha.voxdomini.ro` entry (rules match top-down).
- **Tunnel managed by the add-on itself** (no `tunnel_token`): the add-on cannot add a path rule on the
  HA hostname. Use a subdomain instead, in the Cloudflared add-on options:
  `additional_hosts: [{hostname: camera.voxdomini.ro, service: "http://172.30.32.1:8080"}]`,
  and set this add-on's `public_url` to `https://camera.voxdomini.ro`.

`172.30.32.1` is the HA host as seen from add-ons, where port 8080 of this add-on is published.
If `cloudflared` runs on another computer (not as an HA add-on), use the HA machine's LAN IP instead, e.g. `http://192.168.1.50:8080`.

### With Nabu Casa remote access

Not possible: the Nabu Casa URL only reaches HA itself. Use one of the options above.

## 4. PIN (optional)

On the admin page each room has **Set PIN / Change PIN / Remove PIN**, and **PIN for all rooms** sets
(or removes, when left empty) the same PIN everywhere. With a PIN, the phone asks for it once and
remembers it for `pin_remember_hours`; changing the PIN logs every phone out of that room.
After `pin_max_attempts` wrong tries a phone is locked out for `pin_lockout_minutes`, and a room
accepts at most 50 wrong tries per hour in total.

## 5. Start preconditioning at the shown time

Import the blueprint `blueprints/automation/room_precondition.yaml` from this repository and create one
automation per room (precondition sensor + thermostat). It fires at exactly the time the page shows,
so page and heating never disagree.

## 6. Manual heating and planned periods

Rooms without a calendar event can still be heated from the room page:

- **Start heating** for 1 h, 2 h or 4 h, or **until** a chosen hour. Changing the temperature with − / +
  also starts manual heating (and switches a thermostat that is off back on).
- By default manual heating **turns itself off after 2 hours** (`hold_default_minutes`). While it runs the
  guest can add +30 min / +1 h, set another end hour, or turn it off now. One period is at most
  `hold_max_hours` (12 h).
- **Plan a period**: from–until hours within the next 24 h, with its own temperature (up to 4 per room).
  It turns on and off by itself and shows on the Program page.
- At the end the thermostat goes back to the **room settings from the admin page** (see below). If a
  calendar event is preconditioning or running in that room at that moment, nothing is changed, so the
  event keeps its heating.

### Room settings (admin page)

The temperature and mode you set for a room on the admin page are remembered as that room's settings.
Whenever a manual period, a planned period or a calendar event ends (or an event is deleted while it runs),
the thermostat goes back to them, e.g. *Off*, or *Heat 18 °C*. Rooms you never set there are turned off
(`hold_end_action: off`) or set to `setback_temp` (`hold_end_action: setback`). Turn
`restore_after_events` off if your own automations already handle the end of events.

Periods are stored in `/data/holds.json` and survive restarts and updates.

## 7. Custom codes

By default each room's link is built from its floor and name, e.g. Area *D01 - Sala sport* on floor
*Demisol* → `https://camera.voxdomini.ro/room/demisol-d01-sala-sport` (accents removed, lower case; a
number is added if two rooms would get the same link). The code is fixed when the room is first seen, so
renaming the area later does not break the printed QR code; **Readable code** rebuilds it from the current
name. Readable links are easy to guess, so give those rooms a PIN, or set `readable_codes: false` to use a
random 22-character code instead. **Custom code** on the admin page lets you choose it,
e.g. `sala-102` → `https://camera.voxdomini.ro/camera/sala-102`. Codes must be unique and use 4-64 letters,
digits, `-` or `_`. A short or guessable code (like the room number) can be tried by anyone, so give such
rooms a PIN. **New random code** replaces a custom code with a random one. Either change stops the old printed code.

## 8. Print the QR codes

Open **Room QR** in the HA sidebar. It lists every room with what was found (and what is missing),
the live temperatures, the next event and its QR code. **Print all QR codes** gives an A4 sheet;
**New code** replaces one room's code (the old sticker stops working immediately, open pages close).

## 9. Heating plant and heating log

The **Plant** tab of the admin page shows each boiler with the circuit it uses (open or closed, preset,
heat request) and a table that links every room to the circuit that heats it, its valve (a switch on the
manifold, if it has one) and its temperature sensor. Values marked *guess* come from the room's Area: a
`*_relay` switch becomes the valve, the Area's temperature sensor the sensor. Pick a value to keep it,
pick "–" to go back to the guess. **Heating** sets whether a room follows calendar events, only needs frost
protection, or is not heated at all.

Boilers are created on first start and saved in `/data/topology.json`. Only the first circuit of each
boiler is used: `climate.sala_plen1`, `climate.parter1`, `climate.etaj1` and `climate.demisol1`. The add-on
shows each circuit under its name in HA (a name you set in the entity registry wins).
A circuit counts as open while its preset is `Winter` or its `heat_request` is above 0.

The add-on records the room temperatures, the outdoor temperature (`outdoor_sensor`), every circuit and
every valve in `/data/heating.db` (SQLite): a row per change, at least one every 10 minutes. Rows older
than 120 days are averaged to 15 minutes. The **Heating log** tab lists the runs measured from it:

| Run | What is measured per room |
| --- | --- |
| Heat (circuit opens until it closes, at most 8 h) | start temperature, dead time until +0.2 °C, heating rate in °C/h, time to the comfort temperature, outdoor temperature, how many circuits of the boiler were open |
| Cool (circuit closed for 2 h or more) | time constant τ in hours: how fast the room loses heat to the outside |

Add a note to a run to mark a test, for example "Test A, one circuit". Nothing in this version switches
heating on or off: preconditioning still uses the lead time.

## 10. Start estimates (shown only)

The **Plant** tab opens with one row per circuit that has a linked room with a timed event coming up.
The row shows the room that needs heat first, when the circuit should open for it, and how that time is
calculated:

```
lead = dead time + (target − room temperature at the start) ÷ heating rate + 15 min margin
```

- **Dead time and heating rate** come from the room's heat runs in the Heating log. If the room has none,
  the runs of other rooms on the same circuit are used. Without any runs, the defaults are 40 min and 1.5 °C/h.
  The badge says how many runs were used.
- **Shared boiler**: when other circuits of the same boiler heat at the same time, the boiler's power is shared
  (2 circuits: 67 % each, 3 circuits: 50 %), so the start moves earlier.
- **Outdoor temperature**: with 5 runs or more spread over at least 4 °C of outdoor temperature, the rate also
  follows the outdoor temperature.
- **Cooling until the start**: once the room has a τ from a cool run, the estimate predicts how far the room
  cools before the circuit opens.
- **Target**: the event's `target:` line, else the room's comfort temperature from the Plant tab, else
  `default_target_temp`.
- **Lead time now**: the fixed lead time that preconditioning really uses, for comparison.

The **Heating log** tab ends with **Estimates vs what happened**: the last estimate made before each event's
estimated start, then, once the event is over, when the circuit really opened, the room temperature when the
event started and when the room reached its target. Nothing switches heating on its own in this version.

## 11. Heating control (switching the circuits)

The **Heating control** section of the Plant tab has one card per boiler, each in one of two modes:

- **Shadow** (default): the add-on decides every minute what it would do with the circuit and shows it
  ("Would open: preheat for Sala Mare"). Nothing is sent to HA.
- **Active**: the add-on switches the circuit (preset `Winter` to open, `Summer` to close) and the valves
  (switches) of the rooms on it.

A circuit opens for:

| Reason | When |
| --- | --- |
| Preheat | From the estimated start (section 10) until the event, until the room reaches its target |
| Event | While an event runs in a room on the circuit: below target − `hysteresis` it opens, above target + `hysteresis` it closes. A room without a sensor heats for the whole event. |
| Frost | Any heated room below `frost_temp` (default 10 °C), until it is 1 °C warmer |

It closes otherwise, and switches at most once every `min_switch_minutes` (default 10; frost protection
does not wait). A room valve is open only while its own room needs heat.

### Before you set a boiler to Active

1. **Takeover automations.** Under *Choose automations*, tick every HA automation that switches this
   circuit. For Sala Plen today: *Sala Mare - termostat Zone1*, *Sala Mare - termostat oprit, Zone1 pe Summer*,
   *HVAC sala plen - smart start/resume*. *Climate - Winter at night, Summer in the morning* switches all four
   boilers: taking it over stops its night heating for the boilers left in Shadow as well. Active turns these
   automations off; Shadow turns them back on.
2. **Watchdog.** Create one automation from the blueprint `blueprints/automation/heating_watchdog.yaml`
   (import it from the repository). The add-on publishes `sensor.heating_controller_heartbeat` every minute; if it
   is older than 15 minutes, the watchdog turns the taken-over automations back on and shows a notification.
   When the add-on runs again and sees one of its takeover automations on, it sets that boiler back to Shadow:
   set it to Active again from the Plant tab once all is well.
3. **Parter valves.** The relays `switch.p0X_…_relay` are also switched by the generic thermostats
   `climate.p0X_…_thermostat`. Turn those thermostats off before setting Parter to Active, or they will fight.

Every switch the add-on makes is in Recent changes ("Controller: … → Winter (preheat, …)").

## Security

- Each code is a 128-bit random-looking token (HMAC of a secret in `/data`); room numbers are never in the URL.
- Optional per-room PIN, stored as a salted PBKDF2 hash; the unlock cookie is HttpOnly, SameSite=Strict, scoped to `/camera/`.
- A code only reaches its own room's thermostat, and only `set_temperature` (plus HVAC mode if allowed).
- Setpoints are clamped server-side; one change per room every 3 s and 60 per hour per phone.
- Every change is logged (room, old → new, time, pseudonymous phone id) and shown on the admin page.
- Guest pages send strict CSP, `no-referrer` and no third-party code.
