"""Print local Weave connection status without exposing secrets."""

from __future__ import annotations

import json

from rezn_ai.tracing.weave_client import initialize_weave


if __name__ == "__main__":
    status = initialize_weave()
    print(json.dumps(status.__dict__, indent=2, sort_keys=True))
