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
| Lead time | A `sensor` / `input_number` (minutes) in the Area, labelled **`precondition_lead`** or with `precondition` in its entity id, e.g. `input_number.camera_204_precondition_minutes`. Missing → the default from the options (45 min). |
| Humidity (optional) | Any humidity sensor in the Area is shown automatically. |

Event descriptions may carry two optional lines:

```
target: 22          # target temperature for this event (else the "Default event target" option)
precondition: 60    # lead time for this event only, in minutes
```

## 2. Configure the add-on

- **public_url**: the address phones use for the guest port, printed into every QR code.
  On site Wi-Fi only: `http://<HA IP>:8080`. From the internet: put port 8080 behind your reverse
  proxy or Cloudflare Tunnel with HTTPS and use that address (e.g. `https://climate.example.ro`).
  Only expose port 8080; the admin page is never reachable from it.
- **min_temp / max_temp / temp_step**: limits for guests (per-room overrides in `rooms.yaml`).
- **default_language**: `ro` or `en`.
- **publish_precondition_sensors**: creates `sensor.<area_id>_next_precondition` (timestamp) with
  the attributes `target_temperature`, `event_summary`, `event_start`, `climate_entity`.

Per-room overrides: copy `rooms.example.yaml` to `/addon_configs/<id>_room_climate_portal/rooms.yaml`.

## 3. Start preconditioning at the shown time

Import the blueprint `blueprints/automation/room_precondition.yaml` from this repository and create one
automation per room (precondition sensor + thermostat). It fires at exactly the time the page shows,
so page and heating never disagree.

## 4. Print the QR codes

Open **Room QR** in the HA sidebar. It lists every room with what was found (and what is missing),
the live temperatures, the next event and its QR code. **Print all QR codes** gives an A4 sheet;
**New code** replaces one room's code (the old sticker stops working immediately, open pages close).

## Security

- Each code is a 128-bit random-looking token (HMAC of a secret in `/data`); room numbers are never in the URL.
- A code only reaches its own room's thermostat, and only `set_temperature` (plus HVAC mode if allowed).
- Setpoints are clamped server-side; one change per room every 3 s and 60 per hour per phone.
- Every change is logged (room, old → new, time, pseudonymous phone id) and shown on the admin page.
- Guest pages send strict CSP, `no-referrer` and no third-party code.
