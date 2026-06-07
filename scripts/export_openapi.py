"""Export the FastAPI OpenAPI schema for frontend type generation."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("usage: export_openapi.py <output-json>", file=sys.stderr)
        return 2

    # Keep schema export hermetic: importing the API normally tries Redis first.
    os.environ.setdefault("REZN_DISABLE_REDIS", "true")

    from rezn_ai.api.main import app

    output = Path(args[0])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
