"""Print local Weave connection status without exposing secrets."""

from __future__ import annotations

import json

from rezn_ai.tracing.weave_client import default_env_path, initialize_weave, load_project_env


if __name__ == "__main__":
    loaded = load_project_env()
    status = initialize_weave()
    print(json.dumps({
        **status.__dict__,
        "env_file": str(default_env_path()),
        "env_loaded_keys": sorted(loaded),
    }, indent=2, sort_keys=True))
