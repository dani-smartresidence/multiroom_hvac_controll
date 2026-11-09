# Room Climate Portal (Home Assistant add-on)

Per-room thermostat pages opened by scanning a QR code in each room: live temperature, setpoint
control, and the room's scheduled events with the time preconditioning starts before each one.
All data comes from Home Assistant.

## Install

1. In Home Assistant: **Settings → Add-ons → Add-on store → ⋮ → Repositories**, add
   `https://github.com/dani-smartresidence/multiroom_hvac_controll` (while the repository is private,
   HA needs it public or a local copy, see below).
2. Install **Room Climate Portal**, set `public_url` in its configuration, start it.
3. Follow the add-on's Documentation tab ([DOCS.md](room_climate_portal/DOCS.md)) to label the room Areas
   and print the QR codes.

Private repository? Copy the `room_climate_portal` folder into `/addons/` on the HA host
(Samba or SSH add-on), then **Add-on store → ⋮ → Check for updates**; it appears under *Local add-ons*.

## Layout

```
repository.yaml                      HA add-on repository manifest
room_climate_portal/                 the add-on
  config.yaml, build.yaml, Dockerfile, run.sh
  app/portal/                        Python (aiohttp) service
    ha.py        websocket client to HA (one connection for all phones)
    rooms.py     Area/label discovery + rooms.yaml overrides
    schedule.py  calendar events -> precondition start times
    core.py      state cache, live fan-out, setpoint rules, published sensors
    web.py       guest server (:8080) and admin server (Ingress :8099)
    static/      guest page (RO/EN, light/dark) and admin page
blueprints/automation/room_precondition.yaml
tests/                               pytest suite + fake HA (tests/fake_ha.py)
```

## Develop

```
pip install aiohttp segno pyyaml tzdata pytest pytest-aiohttp
python -m pytest
# demo against the fake HA:
python tests/fake_ha.py 8123 &
cd room_climate_portal/app && HA_URL=http://127.0.0.1:8123 HA_TOKEN=test-token \
  PORTAL_DATA_DIR=/tmp/rcp PORTAL_CONFIG_DIR=/tmp/rcp PORTAL_ADMIN_OPEN=1 python -m portal
# guest :8080 (URLs listed on the admin page), admin :8099
```
