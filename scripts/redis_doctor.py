"""Verify Redis connectivity and the three conductor data structures.

Works against local Redis or a Redis Cloud database. The password is never printed.

Run it with your .env loaded:

    uv run --env-file .env python scripts/redis_doctor.py

Exit code is 0 when Redis answers PING, 1 otherwise — handy for CI / setup checks.
"""

from __future__ import annotations

import json
import sys

try:  # convenience: auto-load .env when run directly without --env-file
    from dotenv import load_dotenv

    load_dotenv()
except ModuleNotFoundError:  # pragma: no cover
    pass

from rezn_ai.storage.redis_store import RedisStore, redact_url, redis_url_from_env


def main() -> int:
    url = redis_url_from_env()
    report: dict[str, object] = {"endpoint": redact_url(url)}
    try:
        store = RedisStore(redis_url=url)
        report.update(store.doctor_status())
    except Exception as exc:  # connection / auth / TLS errors
        report.update({"redis_ping": False, "error": str(exc)})

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report.get("redis_ping") else 1


if __name__ == "__main__":
    sys.exit(main())
