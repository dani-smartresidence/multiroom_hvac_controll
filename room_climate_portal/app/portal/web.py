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
from .ha import HAError

_LOGGER = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
PORTAL_KEY = web.AppKey("portal", Portal)

GUEST_CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; font-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)
INGRESS_IPS = {"172.30.32.2", "127.0.0.1", "::1"}


def _json(data, status: int = 200) -> web.Response:
    return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})


@web.middleware
async def guest_headers(request: web.Request, handler):
    resp = await handler(request)
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
def build_guest_app(portal: Portal) -> web.Application:
    app = web.Application(middlewares=[guest_headers], client_max_size=4096)
    app[PORTAL_KEY] = portal
    routes = web.RouteTableDef()
    index_html = (STATIC / "guest" / "index.html").read_text(encoding="utf-8")

    def page() -> web.Response:
        body = index_html.replace("__DEFAULT_LANG__", portal.options.default_language)
        return web.Response(text=body, content_type="text/html", headers={"Cache-Control": "no-store"})

    def resolve(request: web.Request) -> str:
        if not portal.ready:
            raise web.HTTPServiceUnavailable(
                text=json.dumps({"error": "starting"}), content_type="application/json",
                headers={"Retry-After": "5"},
            )
        room_id = portal.room_for_token(request.match_info["token"])
        if room_id is None:
            raise web.HTTPNotFound(
                text=json.dumps({"error": "invalid_code", "help_text": portal.options.help_text}),
                content_type="application/json",
            )
        return room_id

    @routes.get("/")
    async def root(_request):
        return page()

    @routes.get("/r/{token}")
    async def room_page(_request):
        return page()

    @routes.get("/healthz")
    async def health(_request):
        return _json({"ok": True, "ha_connected": portal.ha.connected.is_set(), "rooms": len(portal.rooms)})

    @routes.get("/api/r/{token}")
    async def room_state(request):
        return _json(portal.snapshot(resolve(request)))

    @routes.get("/api/r/{token}/stream")
    async def room_stream(request):
        room_id = resolve(request)
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
        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            portal.unwatch(room_id, q)
        return resp

    async def _body(request) -> dict:
        try:
            data = await request.json()
        except Exception:  # noqa: BLE001
            raise web.HTTPBadRequest(text='{"error":"bad_json"}', content_type="application/json")
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(text='{"error":"bad_json"}', content_type="application/json")
        return data

    @routes.post("/api/r/{token}/setpoint")
    async def setpoint(request):
        room_id = resolve(request)
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

    @routes.post("/api/r/{token}/mode")
    async def mode(request):
        room_id = resolve(request)
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

    app.add_routes(routes)
    app.router.add_static("/static/", STATIC / "guest", show_index=False)
    return app


def _sse(message: dict) -> bytes:
    return f"data: {json.dumps(message, ensure_ascii=False)}\n\n".encode()


# --------------------------------------------------------------------------- admin
@web.middleware
async def ingress_only(request: web.Request, handler):
    if os.environ.get("PORTAL_ADMIN_OPEN") != "1" and request.remote not in INGRESS_IPS:
        raise web.HTTPForbidden(text="Admin is only reachable through Home Assistant.")
    resp = await handler(request)
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
            "lead_minutes": snap["lead_minutes"],
            "next_event": next((e for e in snap["events"] if not e["all_day"]), None),
            "open_pages": portal.watcher_count(rid),
        }

    def get_room(request) -> str:
        rid = request.match_info["room_id"]
        if rid not in portal.rooms:
            raise web.HTTPNotFound()
        return rid

    @routes.get("/")
    async def index(_request):
        return web.FileResponse(STATIC / "admin" / "index.html")

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
