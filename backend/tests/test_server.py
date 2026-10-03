from __future__ import annotations

import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows launcher")
@pytest.mark.parametrize("reload_arguments", [[], ["-Reload"]])
def test_launcher_rejects_occupied_port_without_starting_application(reload_arguments):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        result = subprocess.run([
            shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "scripts/run.ps1"),
            "-Port", str(occupied.getsockname()[1]), *reload_arguments,
        ], cwd=ROOT, capture_output=True, text=True, timeout=15)
    output = result.stdout + result.stderr
    assert result.returncode == 3, output
    assert "10048" in output or "10013" in output, output
    assert "Application startup" not in output, output
    assert "Application shutdown" not in output, output


@pytest.mark.parametrize("reload_arguments", [[], ["--reload"]])
def test_server_rejects_port_with_reuse_address(reload_arguments):
    with socket.socket() as occupied:
        occupied.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        occupied.bind(("127.0.0.1", 0))
        occupied.listen()
        result = subprocess.run([
            sys.executable, str(ROOT / "backend/run_server.py"), "--port", str(occupied.getsockname()[1]), *reload_arguments,
        ], cwd=ROOT, capture_output=True, text=True, timeout=5)
    output = result.stdout + result.stderr
    assert result.returncode == 3, output
    assert "Cannot listen" in output, output
    assert "Application startup" not in output, output
    assert "Application shutdown" not in output, output


def test_ctrl_c_exits_after_disconnected_request(tmp_path):
    started = tmp_path / "request-started"
    cancelled = tmp_path / "request-cancelled"
    fixture = tmp_path / "shutdown_fixture.py"
    fixture.write_text(f'''
import asyncio
import runpy
import signal
import sys
from pathlib import Path
sys.path.insert(0, {str(ROOT / "backend")!r})
from app.main import app
from fastapi.routing import APIRoute

async def stalled_request():
    Path({str(started)!r}).touch()
    try:
        await asyncio.Event().wait()
    finally:
        Path({str(cancelled)!r}).touch()

async def interrupt():
    asyncio.get_running_loop().call_later(0.1, signal.raise_signal, signal.SIGINT)
    return {{"stopping": True}}

app.router.routes.insert(0, APIRoute("/_test/stall", stalled_request, methods=["GET"]))
app.router.routes.insert(0, APIRoute("/_test/interrupt", interrupt, methods=["GET"]))
runpy.run_path({str(ROOT / "backend/run_server.py")!r}, run_name="__main__")
''', encoding="utf-8")
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    process = subprocess.Popen([sys.executable, str(fixture), "--port", str(port)], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                connection = socket.create_connection(("127.0.0.1", port), timeout=0.2)
                break
            except OSError:
                assert process.poll() is None, process.communicate()[0]
                assert time.monotonic() < deadline, "Server failed to start"
                time.sleep(0.05)
        with connection:
            connection.sendall(b"GET /_test/stall HTTP/1.1\r\nHost: localhost\r\n\r\n")
            while not started.exists():
                assert time.monotonic() < deadline, "Request never started"
                time.sleep(0.05)
        # The browser connection is gone, but its request handler is still waiting.
        assert not cancelled.exists()
        with urlopen(f"http://127.0.0.1:{port}/_test/interrupt", timeout=2) as response:
            assert response.status == 200
        shutdown_started = time.monotonic()
        output, _ = process.communicate(timeout=9)
        assert process.returncode == 0, output
        assert time.monotonic() - shutdown_started < 8, output
        assert cancelled.exists(), output
        assert "Application shutdown complete" in output, output
        assert "Finished server process" in output, output
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


def test_failed_application_startup_returns_error(tmp_path):
    fixture = tmp_path / "startup_failure_fixture.py"
    fixture.write_text(f'''
import runpy
import sys
from types import ModuleType

async def app(scope, receive, send):
    await receive()
    await send({{"type": "lifespan.startup.failed", "message": "Startup failed for test"}})

module = ModuleType("app.main")
module.app = app
sys.modules["app.main"] = module
sys.path.insert(0, {str(ROOT / "backend")!r})
runpy.run_path({str(ROOT / "backend/run_server.py")!r}, run_name="__main__")
''', encoding="utf-8")
    result = subprocess.run([sys.executable, str(fixture), "--port", "0"], cwd=ROOT, capture_output=True, text=True, timeout=5)
    output = result.stdout + result.stderr
    assert result.returncode == 3, output
    assert "Startup failed for test" in output, output
