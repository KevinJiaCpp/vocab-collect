from __future__ import annotations

import argparse
import logging
import socket
from pathlib import Path

import uvicorn
from uvicorn.config import STARTUP_FAILURE
from uvicorn.supervisors import ChangeReload


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Vocab Collect server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    config = uvicorn.Config(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        reload_dirs=[str(Path(__file__).resolve().parent)] if args.reload else None,
        timeout_graceful_shutdown=5,
    )
    server = uvicorn.Server(config)
    family = socket.AF_INET6 if ":" in args.host else socket.AF_INET
    try:
        # Unlike Uvicorn's binder, this avoids sharing an occupied port on Windows.
        listener = socket.create_server((args.host, args.port), family=family, backlog=config.backlog)
    except OSError as exc:
        logging.getLogger("uvicorn.error").error("Cannot listen on %s:%s: %s", args.host, args.port, exc)
        raise SystemExit(STARTUP_FAILURE) from None
    display_host = f"[{args.host}]" if family == socket.AF_INET6 else args.host
    logging.getLogger("uvicorn.error").info(
        "Uvicorn running on http://%s:%s (Press CTRL+C to quit)", display_host, listener.getsockname()[1]
    )
    try:
        with listener:
            if config.should_reload:
                ChangeReload(config, target=server.run, sockets=[listener]).run()
            else:
                server.run(sockets=[listener])
    except KeyboardInterrupt:
        pass
    if not config.should_reload and not server.started:
        raise SystemExit(STARTUP_FAILURE)


if __name__ == "__main__":
    main()
