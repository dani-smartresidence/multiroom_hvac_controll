"""Entry point: python3 -m portal"""
from __future__ import annotations

import asyncio
import logging
import os
import signal

import aiohttp
from aiohttp import web

from .config import HAConnection, Options, Paths
from .core import Portal
from .ha import HAClient
from .web import build_admin_app, build_guest_app

GUEST_PORT = int(os.environ.get("PORTAL_GUEST_PORT", "8080"))
ADMIN_PORT = int(os.environ.get("PORTAL_ADMIN_PORT", "8099"))


async def main() -> None:
    logging.basicConfig(
        level=os.environ.get("PORTAL_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    paths = Paths()
    options = Options.load(paths.options)
    conn = HAConnection.from_env()

    async with aiohttp.ClientSession() as session:
        ha = HAClient(conn, session)
        portal = Portal(options, paths, ha)

        runners = []
        for app, port in ((build_guest_app(portal), GUEST_PORT), (build_admin_app(portal), ADMIN_PORT)):
            runner = web.AppRunner(app, access_log=None)
            await runner.setup()
            await web.TCPSite(runner, "0.0.0.0", port).start()
            runners.append(runner)
        logging.getLogger("portal").info(
            "Guest pages on :%d, admin on :%d, public URL %s", GUEST_PORT, ADMIN_PORT, options.public_url
        )

        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)

        tasks = [asyncio.create_task(ha.run_forever()), asyncio.create_task(portal.schedule_loop()), asyncio.create_task(portal.hold_loop())]
        await stop.wait()
        await ha.stop()
        for t in tasks:
            t.cancel()
        for runner in runners:
            await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
