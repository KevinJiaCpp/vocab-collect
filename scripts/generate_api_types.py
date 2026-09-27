"""Generate frontend request types from FastAPI's OpenAPI document."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.main import app  # noqa: E402


def main() -> None:
    cli = ROOT / "frontend" / "node_modules" / "openapi-typescript" / "bin" / "cli.js"
    if not cli.exists():
        raise SystemExit("Install frontend packages with npm ci before generating API types")
    output = ROOT / "frontend" / "src" / "api.generated.ts"
    with tempfile.TemporaryDirectory() as directory:
        schema = Path(directory) / "openapi.json"
        schema.write_text(json.dumps(app.openapi()), encoding="utf-8")
        subprocess.run(["node", str(cli), str(schema), "--output", str(output)], check=True)


if __name__ == "__main__":
    main()
