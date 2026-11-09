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

- **public_url**: your HA address without a path, e.g. `https://ha.voxdomini.ro`.
- **base_path**: `/camera` (default). QR codes point to `https://ha.voxdomini.ro/camera/<code>`.
- **trust_proxy_headers**: turn on when a reverse proxy sits in front (see section 3), so rate limits
  and PIN lockouts see each phone's real address.
- **min_temp / max_temp / temp_step**: limits for guests (per-room overrides in `rooms.yaml`).
- **default_language**: `ro` or `en`.
- **pin_remember_hours / pin_max_attempts / pin_lockout_minutes**: PIN behaviour (PINs are set on the admin page).
- **publish_precondition_sensors**: creates `sensor.<area_id>_next_precondition` (timestamp) with
  the attributes `target_temperature`, `event_summary`, `event_start`, `climate_entity`.

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

## 6. Custom codes

By default each room gets a random 22-character code. **Custom code** on the admin page lets you choose it,
e.g. `sala-102` → `https://camera.voxdomini.ro/camera/sala-102`. Codes must be unique and use 4-64 letters,
digits, `-` or `_`. A short or guessable code (like the room number) can be tried by anyone, so give such
rooms a PIN. **New random code** replaces a custom code with a random one. Either change stops the old printed code.

## 7. Print the QR codes

Open **Room QR** in the HA sidebar. It lists every room with what was found (and what is missing),
the live temperatures, the next event and its QR code. **Print all QR codes** gives an A4 sheet;
**New code** replaces one room's code (the old sticker stops working immediately, open pages close).

## Security

- Each code is a 128-bit random-looking token (HMAC of a secret in `/data`); room numbers are never in the URL.
- Optional per-room PIN, stored as a salted PBKDF2 hash; the unlock cookie is HttpOnly, SameSite=Strict, scoped to `/camera/`.
- A code only reaches its own room's thermostat, and only `set_temperature` (plus HVAC mode if allowed).
- Setpoints are clamped server-side; one change per room every 3 s and 60 per hour per phone.
- Every change is logged (room, old → new, time, pseudonymous phone id) and shown on the admin page.
- Guest pages send strict CSP, `no-referrer` and no third-party code.
