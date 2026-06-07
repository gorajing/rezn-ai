"""Guard: the test suite must run hermetically regardless of the dev's shell/.env.

conftest force-clears the W&B network/inference credentials so a populated
shell environment (a developer who exports WANDB_API_KEY) can never leak a live
wandb.ai connection or real inference into the suite. Regression guard for the
setdefault -> forced-clear fix.
"""

from __future__ import annotations

import os


def test_wandb_network_creds_are_cleared():
    # Force-cleared in conftest (not setdefault), so an inherited shell key cannot
    # turn the hermetic suite into a live wandb.ai session.
    assert os.environ.get("WANDB_API_KEY") == ""
    assert os.environ.get("WANDB_INFERENCE_API_KEY") == ""


def test_weave_project_override_is_dropped_to_the_default():
    # A developer's custom WEAVE_PROJECT must not steer test traces; the code
    # default (rezn-ai/rezn-ai) applies instead.
    from rezn_ai.tracing.weave_client import DEFAULT_WEAVE_PROJECT, default_project_name

    assert default_project_name() == DEFAULT_WEAVE_PROJECT
