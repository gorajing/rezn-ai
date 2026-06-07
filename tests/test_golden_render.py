"""Golden byte-identity gate for the default render.

The frozen default arrangement must render to the exact same WAV bytes before and
after the SoundProfile refactor. This is the safety lynchpin: kit=kernel (and any
other "default profile" path) must reproduce today's audio byte-for-byte. If this
test fails, the refactor changed the default sound — investigate, do not re-baseline.
"""

import hashlib
import json
import pathlib

from rezn_ai.render.preview_synth import write_preview_wav

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "golden_arrangement.json"
EXPECTED_SHA256 = "9767552592f3f7ea58910682f3ff5719c3f91d6d626b36b249de60d071b125cc"


def test_default_render_is_byte_identical(tmp_path):
    arrangement = json.loads(FIXTURE.read_text())
    out = tmp_path / "golden.wav"
    write_preview_wav(arrangement, out, sample_rate=44100)
    actual = hashlib.sha256(out.read_bytes()).hexdigest()
    assert actual == EXPECTED_SHA256, (
        "Default render changed — the SoundProfile refactor must keep the kernel "
        "path byte-identical."
    )
