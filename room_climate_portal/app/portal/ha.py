"""Single websocket connection to Home Assistant, shared by every open room page."""
from __future__ import annotations

import asyncio
import itertools
import json
import logging
from typing import Any, Awaitable, Callable

import aiohttp

from .config import HAConnection

_LOGGER = logging.getLogger(__name__)

EventHandler = Callable[[dict], Awaitable[None] | None]


class HAError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class HAClient:
    def __init__(self, conn: HAConnection, session: aiohttp.ClientSession):
        self._conn = conn
        self._session = session
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future] = {}
        self._subs: dict[int, EventHandler] = {}
        self.connected = asyncio.Event()
        self.on_connect: Callable[[], Awaitable[None]] | None = None
        self.on_disconnect: Callable[[], Awaitable[None] | None] | None = None
        self._stopping = False

    # ---------------------------------------------------------------- lifecycle
    async def run_forever(self) -> None:
        delay = 1.0
        while not self._stopping:
            try:
                await self._run_once()
                delay = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as err:  # noqa: BLE001 - reconnect on anything
                _LOGGER.warning("HA connection lost: %s", err)
            finally:
                await self._teardown()
            if self._stopping:
                break
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)

    async def stop(self) -> None:
        self._stopping = True
        if self._ws is not None:
            await self._ws.close()

    async def _run_once(self) -> None:
        _LOGGER.info("Connecting to Home Assistant at %s", self._conn.ws_url)
        self._ws = await self._session.ws_connect(self._conn.ws_url, heartbeat=30, max_msg_size=0)
        msg = await self._ws.receive_json()
        if msg.get("type") != "auth_required":
            raise HAError("protocol", f"unexpected first message {msg}")
        await self._ws.send_json({"type": "auth", "access_token": self._conn.token})
        msg = await self._ws.receive_json()
        if msg.get("type") != "auth_ok":
            raise HAError("auth", msg.get("message", "authentication failed"))
        _LOGGER.info("Authenticated with Home Assistant %s", msg.get("ha_version"))

        reader = asyncio.create_task(self._reader())
        self.connected.set()
        try:
            if self.on_connect:
                await self.on_connect()
            await reader
        finally:
            reader.cancel()

    async def _teardown(self) -> None:
        was_connected = self.connected.is_set()
        self.connected.clear()
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(HAError("disconnected", "connection to HA lost"))
        self._pending.clear()
        self._subs.clear()
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        if was_connected and self.on_disconnect:
            res = self.on_disconnect()
            if asyncio.iscoroutine(res):
                await res

    async def _reader(self) -> None:
        assert self._ws is not None
        async for raw in self._ws:
            if raw.type != aiohttp.WSMsgType.TEXT:
                if raw.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
                continue
            payload = json.loads(raw.data)
            for msg in payload if isinstance(payload, list) else [payload]:
                await self._dispatch(msg)
        raise HAError("closed", "websocket closed")

    async def _dispatch(self, msg: dict) -> None:
        mid = msg.get("id")
        mtype = msg.get("type")
        if mtype == "event" and mid in self._subs:
            try:
                res = self._subs[mid](msg["event"])
                if asyncio.iscoroutine(res):
                    await res
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Error handling HA event")
            return
        if mtype == "result" and mid in self._pending:
            fut = self._pending.pop(mid)
            if fut.done():
                return
            if msg.get("success"):
                fut.set_result(msg.get("result"))
            else:
                err = msg.get("error") or {}
                fut.set_exception(HAError(err.get("code", "unknown"), err.get("message", "")))

    # ---------------------------------------------------------------- commands
    async def call(self, payload: dict, timeout: float = 30) -> Any:
        if self._ws is None or not self.connected.is_set():
            raise HAError("disconnected", "not connected to HA")
        mid = next(self._ids)
        fut = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await self._ws.send_json({"id": mid, **payload})
        try:
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(mid, None)

    async def subscribe_events(self, event_type: str, handler: EventHandler) -> int:
        mid = next(self._ids)
        # Register before sending so no event slips between result and registration.
        self._subs[mid] = handler
        fut = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        assert self._ws is not None
        await self._ws.send_json({"id": mid, "type": "subscribe_events", "event_type": event_type})
        try:
            await asyncio.wait_for(fut, 30)
        except Exception:
            self._subs.pop(mid, None)
            raise
        return mid

    async def call_service(
        self,
        domain: str,
        service: str,
        data: dict | None = None,
        entity_id: str | None = None,
        return_response: bool = False,
    ) -> Any:
        payload: dict = {
            "type": "call_service",
            "domain": domain,
            "service": service,
            "service_data": data or {},
        }
        if entity_id:
            payload["target"] = {"entity_id": entity_id}
        if return_response:
            payload["return_response"] = True
        result = await self.call(payload)
        if return_response:
            return (result or {}).get("response")
        return result

    async def set_state(self, entity_id: str, state: str, attributes: dict) -> None:
        """Publish a helper state through the REST API (POST /api/states)."""
        url = f"{self._conn.rest_url}/states/{entity_id}"
        headers = {"Authorization": f"Bearer {self._conn.token}"}
        async with self._session.post(
            url, json={"state": state, "attributes": attributes}, headers=headers
        ) as resp:
            if resp.status >= 400:
                raise HAError("rest", f"{resp.status} {await resp.text()}")
