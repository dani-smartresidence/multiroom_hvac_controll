"""HTTP: the public guest server (port 8080) and the admin server (HA Ingress, 8099)."""
from __future__ import annotations

import asyncio
import html
import io
import json
import logging
import os
from pathlib import Path

import segno
from aiohttp import web

from .core import Portal, RateLimited
from .holds import HoldError
from .ha import HAError
from .pins import PIN_RE, PinLocked
from .tokens import CodeError

_LOGGER = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


def _asset_version() -> str:
    """Hash of all static files: changes with every release, so browsers and the
    HA app never keep running an old script after an update."""
    import hashlib

    h = hashlib.sha1()
    for f in sorted(STATIC.rglob("*")):
        if f.is_file():
            h.update(f.name.encode())
            h.update(f.read_bytes())
    return h.hexdigest()[:10]


ASSET_V = _asset_version()
PORTAL_KEY = web.AppKey("portal", Portal)

GUEST_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
INGRESS_IPS = {"172.30.32.2", "127.0.0.1", "::1"}


def _json(data, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})


def _revalidate_static(request: web.Request, resp) -> None:
    if "/static/" in request.path:
        resp.headers["Cache-Control"] = "no-cache"


@web.middleware
async def guest_headers(request: web.Request, handler):
    resp = await handler(request)
    _revalidate_static(request, resp)
    resp.headers.setdefault("Content-Security-Policy", GUEST_CSP)
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    return resp


def client_ip(request: web.Request, portal: Portal) -> str:
    if portal.options.trust_proxy_headers:
        fwd = request.headers.get("X-Forwarded-For", "")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.remote or "unknown"


# --------------------------------------------------------------------------- guest
TOKEN_RE = r"[A-Za-z0-9_-]{4,64}"


def build_guest_app(portal: Portal) -> web.Application:
    """Guest server. Every path lives under options.base_path (default /camera), so a
    reverse proxy in front of HA can route https://ha.example.ro/camera/... here."""
    app = web.Application(middlewares=[guest_headers], client_max_size=4096)
    app[PORTAL_KEY] = portal
    routes = web.RouteTableDef()
    base = portal.options.base_path
    index_html = (STATIC / "guest" / "index.html").read_text(encoding="utf-8")
    cookie_path = (base or "") + "/"

    def page() -> web.Response:
        body = (
            index_html.replace("__DEFAULT_LANG__", portal.options.default_language)
            .replace("__BASE__", base)
            .replace("__V__", ASSET_V)
        )
        return web.Response(text=body, content_type="text/html", headers={"Cache-Control": "no-store"})

    def error(exc, payload: dict, **kw):
        return exc(text=json.dumps(payload, ensure_ascii=False), content_type="application/json", **kw)

    def resolve(request: web.Request) -> str:
        if not portal.ready:
            raise error(web.HTTPServiceUnavailable, {"error": "starting"}, headers={"Retry-After": "5"})
        room_id = portal.room_for_token(request.match_info["token"])
        if room_id is None:
            raise error(web.HTTPNotFound, {"error": "invalid_code", "help_text": portal.options.help_text})
        return room_id

    def cookie_name(room_id: str) -> str:
        return "rcp_" + portal.tokens.sign("cookie:" + room_id)[:12]

    def authorize(request: web.Request) -> str:
        room_id = resolve(request)
        if not portal.pins.session_valid(room_id, request.cookies.get(cookie_name(room_id))):
            room = portal.rooms[room_id]
            raise error(
                web.HTTPUnauthorized,
                {"error": "pin_required", "name": room.name, "subtitle": room.subtitle,
                 "default_language": portal.options.default_language, "help_text": portal.options.help_text},
            )
        return room_id

    def is_https(request: web.Request) -> bool:
        if request.secure:
            return True
        if portal.options.trust_proxy_headers:
            return request.headers.get("X-Forwarded-Proto", "").lower() == "https"
        return False

    @routes.get("/")
    async def root(_request):
        return page()

    @routes.get("/healthz")
    async def health(_request):
        return _json({"ok": True, "ha_connected": portal.ha.connected.is_set(), "rooms": len(portal.rooms)})

    if base:
        @routes.get(base)
        @routes.get(base + "/")
        async def base_root(_request):
            return page()

        @routes.get(base + "/healthz")
        async def base_health(request):
            return await health(request)

    @routes.get(base + "/{token:" + TOKEN_RE + "}")
    async def room_page(_request):
        return page()

    api = base + "/api/{token:" + TOKEN_RE + "}"

    @routes.get(api)
    async def room_state(request):
        return _json(portal.snapshot(authorize(request)))

    @routes.post(api + "/pin")
    async def pin(request):
        room_id = resolve(request)
        data = await _body(request)
        client = portal.tokens.client_id(client_ip(request, portal))
        try:
            ok, left = portal.pins.verify(room_id, str(data.get("pin", "")), client)
        except PinLocked as err:
            portal.audit.write(room=room_id, action="pin_locked", client=client)
            return _json({"error": "locked", "retry_after": err.retry_after}, 429)
        if not ok:
            portal.audit.write(room=room_id, action="pin_wrong", client=client)
            return _json({"error": "wrong_pin", "attempts_left": left}, 403)
        resp = _json({"ok": True})
        if portal.pins.enabled(room_id):
            resp.set_cookie(
                cookie_name(room_id), portal.pins.make_session(room_id),
                max_age=portal.pins.remember_s, path=cookie_path, httponly=True,
                samesite="Strict", secure=is_https(request),
            )
        return resp

    @routes.get(api + "/stream")
    async def room_stream(request):
        room_id = authorize(request)
        resp = web.StreamResponse(
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-store",
                "X-Accel-Buffering": "no",
            }
        )
        await resp.prepare(request)
        q = portal.watch(room_id)
        try:
            await resp.write(_sse({"type": "room", "room": portal.snapshot(room_id)}))
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=25)
                except asyncio.TimeoutError:
                    await resp.write(b": keepalive\n\n")
                    continue
                if msg.get("type") == "connection":
                    msg = {"type": "room", "room": portal.snapshot(room_id)}
                await resp.write(_sse(msg))
                if msg.get("type") in ("revoked", "reauth"):
                    break
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            portal.unwatch(room_id, q)
        return resp

    async def _body(request) -> dict:
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            raise error(web.HTTPBadRequest, {"error": "bad_json"})
        if not isinstance(data, dict):
            raise error(web.HTTPBadRequest, {"error": "bad_json"})
        return data

    @routes.post(api + "/setpoint")
    async def setpoint(request):
        room_id = authorize(request)
        data = await _body(request)
        try:
            value = float(data.get("temperature"))
        except (TypeError, ValueError):
            return _json({"error": "bad_value"}, 400)
        if value != value or abs(value) > 100:  # NaN / absurd
            return _json({"error": "bad_value"}, 400)
        client = portal.tokens.client_id(client_ip(request, portal))
        try:
            applied = await portal.set_temperature(room_id, value, client)
        except RateLimited as err:
            return _json({"error": "rate_limited", "scope": str(err)}, 429)
        except HAError as err:
            _LOGGER.warning("set_temperature failed for %s: %s", room_id, err)
            return _json({"error": "ha_error", "message": err.message}, 502)
        return _json({"ok": True, "temperature": applied})

    @routes.post(api + "/mode")
    async def mode(request):
        room_id = authorize(request)
        data = await _body(request)
        client = portal.tokens.client_id(client_ip(request, portal))
        try:
            applied = await portal.set_mode(room_id, str(data.get("hvac_mode", "")), client)
        except PermissionError:
            return _json({"error": "not_allowed"}, 403)
        except ValueError:
            return _json({"error": "bad_value"}, 400)
        except RateLimited as err:
            return _json({"error": "rate_limited", "scope": str(err)}, 429)
        except HAError as err:
            return _json({"error": "ha_error", "message": err.message}, 502)
        return _json({"ok": True, "hvac_mode": applied})

    @routes.post(api + "/hold")
    async def hold(request):
        room_id = authorize(request)
        data = await _body(request)
        client = portal.tokens.client_id(client_ip(request, portal))
        try:
            snap = await portal.hold_action(room_id, data, client)
        except HoldError as err:
            return _json({"error": str(err) or "bad_value"}, 400)
        except (TypeError, ValueError):
            return _json({"error": "bad_value"}, 400)
        except RateLimited as err:
            return _json({"error": "rate_limited", "scope": str(err)}, 429)
        except HAError as err:
            _LOGGER.warning("manual heating failed for %s: %s", room_id, err)
            return _json({"error": "ha_error", "message": err.message}, 502)
        return _json({"ok": True, "room": snap})

    app.add_routes(routes)
    app.router.add_static(base + "/static/", STATIC / "guest", show_index=False)
    return app


def _sse(message: dict) -> bytes:
    return f"data: {json.dumps(message, ensure_ascii=False)}\n\n".encode()


# --------------------------------------------------------------------------- admin
@web.middleware
async def ingress_only(request: web.Request, handler):
    if os.environ.get("PORTAL_ADMIN_OPEN") != "1" and request.remote not in INGRESS_IPS:
        raise web.HTTPForbidden(text="Admin is only reachable through Home Assistant.")
    resp = await handler(request)
    _revalidate_static(request, resp)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    return resp


def qr_svg(url: str, scale: int = 6) -> str:
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="svg", scale=scale, border=2, xmldecl=False, svgns=True)
    return buf.getvalue().decode()


def build_admin_app(portal: Portal) -> web.Application:
    app = web.Application(middlewares=[ingress_only])
    app[PORTAL_KEY] = portal
    routes = web.RouteTableDef()

    def room_row(rid: str) -> dict:
        room = portal.rooms[rid]
        snap = portal.snapshot(rid)
        return {
            **room.as_dict(),
            "url": portal.room_url(rid),
            "generation": portal.tokens.generation(rid),
            "current": snap["climate"]["current"],
            "target": snap["climate"]["target"],
            "hvac_mode": snap["climate"]["hvac_mode"],
            "hvac_modes": snap["climate"]["hvac_modes"],
            "hvac_action": snap["climate"]["hvac_action"],
            "available": snap["climate"]["available"],
            "set_min": snap["climate"]["min"],
            "set_max": snap["climate"]["max"],
            "step": snap["climate"]["step"],
            "lead_minutes": snap["lead_minutes"],
            "next_event": next((e for e in snap["events"] if not e["all_day"]), None),
            "open_pages": portal.watcher_count(rid),
            "pin_enabled": portal.pins.enabled(rid),
            "custom_code": portal.tokens.is_custom(rid),
            "hold": next((h for h in snap["holds"] if h["active"]), None),
            "planned": len([h for h in snap["holds"] if not h["active"]]),
        }

    def get_room(request) -> str:
        rid = request.match_info["room_id"]
        if rid not in portal.rooms:
            raise web.HTTPNotFound()
        return rid

    @routes.get("/")
    async def index(_request):
        body = (STATIC / "admin" / "index.html").read_text(encoding="utf-8").replace("__V__", ASSET_V)
        return web.Response(text=body, content_type="text/html", headers={"Cache-Control": "no-store"})

    @routes.get("/api/status")
    async def status(_request):
        return _json(
            {
                "ha_connected": portal.ha.connected.is_set(),
                "ready": portal.ready,
                "public_url": portal.options.public_url,
                "time_zone": str(portal.tz),
                "room_label": portal.options.room_label,
            }
        )

    @routes.get("/api/rooms")
    async def rooms(_request):
        return _json([room_row(rid) for rid in portal.rooms])

    @routes.post("/api/rooms/{room_id}/rotate")
    async def rotate(request):
        rid = get_room(request)
        portal.tokens.rotate(rid)
        portal.audit.write(room=rid, action="rotate_token", client="admin")
        # Close pages opened with the old code.
        portal.broadcast(rid, {"type": "revoked"})
        return _json(room_row(rid))

    async def read_pin(request) -> str | None:
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            raise web.HTTPBadRequest(text="bad json")
        pin = data.get("pin") if isinstance(data, dict) else None
        if pin in (None, ""):
            return None
        pin = str(pin)
        if not PIN_RE.match(pin):
            raise web.HTTPBadRequest(text=json.dumps({"error": "PIN must be 4 to 8 digits"}), content_type="application/json")
        return pin

    @routes.post("/api/rooms/{room_id}/code")
    async def set_code(request):
        rid = get_room(request)
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            raise web.HTTPBadRequest(text="bad json")
        code = data.get("code") if isinstance(data, dict) else None
        try:
            portal.tokens.set_custom(rid, code or None, portal.rooms.keys())
        except CodeError as err:
            return _json({"error": str(err)}, 400)
        portal.audit.write(room=rid, action="code_custom" if code else "rotate_token", client="admin")
        portal.broadcast(rid, {"type": "revoked"})
        return _json(room_row(rid))

    async def admin_body(request) -> dict:
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            data = None
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(text=json.dumps({"error": "bad json"}), content_type="application/json")
        return data

    @routes.post("/api/rooms/{room_id}/temperature")
    async def admin_temperature(request):
        rid = get_room(request)
        data = await admin_body(request)
        try:
            value = float(data.get("temperature"))
            if value != value or abs(value) > 100:
                raise ValueError
        except (TypeError, ValueError):
            return _json({"error": "Not a temperature"}, 400)
        try:
            await portal.set_temperature(rid, value, "admin", admin=True)
        except HAError as err:
            return _json({"error": f"Home Assistant: {err.message}"}, 502)
        await asyncio.sleep(0.3)  # let HA's state change arrive
        return _json(room_row(rid))

    @routes.post("/api/rooms/{room_id}/mode")
    async def admin_mode(request):
        rid = get_room(request)
        data = await admin_body(request)
        try:
            await portal.set_mode(rid, str(data.get("hvac_mode", "")), "admin", admin=True)
        except PermissionError:
            return _json({"error": "This room has no thermostat"}, 400)
        except ValueError:
            return _json({"error": "The thermostat does not support this mode"}, 400)
        except HAError as err:
            return _json({"error": f"Home Assistant: {err.message}"}, 502)
        await asyncio.sleep(0.3)
        return _json(room_row(rid))

    @routes.post("/api/rooms/{room_id}/pin")
    async def set_pin(request):
        rid = get_room(request)
        portal.set_pin(rid, await read_pin(request))
        return _json(room_row(rid))

    @routes.post("/api/pin_all")
    async def set_pin_all(request):
        pin = await read_pin(request)
        for rid in portal.rooms:
            portal.set_pin(rid, pin)
        return _json([room_row(rid) for rid in portal.rooms])

    @routes.post("/api/reload")
    async def reload(_request):
        await portal.rediscover()
        await portal.refresh_all_schedules()
        return _json([room_row(rid) for rid in portal.rooms])

    @routes.get("/api/audit")
    async def audit(request):
        limit = min(int(request.query.get("limit", "200")), 2000)
        return _json(portal.audit.tail(limit, request.query.get("room")))

    @routes.get("/qr/{room_id}.svg")
    async def qr(request):
        rid = get_room(request)
        return web.Response(text=qr_svg(portal.room_url(rid)), content_type="image/svg+xml")

    @routes.get("/print")
    async def print_sheet(request):
        only = request.query.get("room")
        ids = [only] if only in portal.rooms else list(portal.rooms)
        cards = []
        for rid in ids:
            room = portal.rooms[rid]
            cards.append(
                f"""<div class="card"><div class="qr">{qr_svg(portal.room_url(rid), 8)}</div>
<div class="name">{html.escape(room.name)}</div>
<div class="sub">{html.escape(room.subtitle)}</div>
<div class="hint">Scanați pentru temperatura camerei<br><span>Scan to control this room's temperature</span></div></div>"""
            )
        page = (STATIC / "admin" / "print.html").read_text(encoding="utf-8").replace("__CARDS__", "\n".join(cards))
        return web.Response(text=page, content_type="text/html")

    app.add_routes(routes)
    app.router.add_static("/static/", STATIC / "admin", show_index=False)
    return app
