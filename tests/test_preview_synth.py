from rezn_ai.eval.audio_metrics import measure_wav
from rezn_ai.eval.mix_checks import evaluate_metrics
from rezn_ai.render.preview_synth import render_arrangement, write_preview_wav

# Small, fast arrangement: a short pitched part plus one drum hit at 120 bpm.
TINY_ARRANGEMENT = {
    "schema": "rezn-ai.arrangement.v1",
    "identity": {"title": "t", "key": "A", "mode": "minor", "tempo": 120.0, "seed": 1},
    "form": {"beats_per_bar": 4, "total_beats": 4.0, "sections": []},
    "parts": {
        "harmony": [
            {"part": "harmony", "pitch": 57, "start": 0.0, "duration": 2.0, "velocity": 90},
            {"part": "harmony", "pitch": 60, "start": 0.0, "duration": 2.0, "velocity": 90},
        ],
        "drums": [
            {"part": "drums", "pitch": 36, "start": 0.0, "duration": 0.5, "velocity": 110},
            {"part": "drums", "pitch": 38, "start": 1.0, "duration": 0.5, "velocity": 100},
        ],
    },
}


def test_render_is_deterministic():
    a = render_arrangement(TINY_ARRANGEMENT, sample_rate=8_000)
    b = render_arrangement(TINY_ARRANGEMENT, sample_rate=8_000)
    assert a[0].tobytes() == b[0].tobytes()
    assert a[1].tobytes() == b[1].tobytes()


def test_preview_wav_is_valid_stereo_audio(tmp_path):
    out = write_preview_wav(TINY_ARRANGEMENT, tmp_path / "preview.wav", sample_rate=8_000)
    metrics = measure_wav(out)

    assert metrics["channels"] == 2
    assert metrics["sample_width_bytes"] == 2
    assert metrics["duration_seconds"] > 0.0
    # not silent and below clipping ceiling
    assert metrics["rms"] > 0.001
    assert metrics["peak"] <= 0.999

    checks = evaluate_metrics(metrics, min_duration_seconds=0.0)
    assert checks["checks"]["not_silent"] is True
    assert checks["checks"]["peak_ok"] is True
    assert checks["checks"]["stereo"] is True
