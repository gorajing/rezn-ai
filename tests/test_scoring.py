from rezn_ai.eval.scoring import technical_score

VALID_CHECKS = {"checks": {"not_silent": True, "peak_ok": True, "duration_ok": True}}


def _arrangement(roots_by_bar, key="C"):
    """Build a minimal arrangement whose harmony roots are the given pitches."""
    harmony = []
    for bar, pitch in enumerate(roots_by_bar):
        start = float(bar * 4)
        # a chord: root + two upper voices (root is the lowest pitch)
        harmony.extend(
            {"part": "harmony", "pitch": p, "start": start, "duration": 4.0, "velocity": 80}
            for p in (pitch, pitch + 4, pitch + 7)
        )
    return {
        "identity": {"key": key, "mode": "major", "tempo": 120.0, "seed": 1},
        "form": {"sections": [{"name": "a"}]},
        "parts": {
            "harmony": harmony,
            "bass": [{"part": "bass", "pitch": 36, "start": 0.0, "duration": 1.0, "velocity": 80}],
            "drums": [{"part": "drums", "pitch": 36, "start": 0.0, "duration": 0.5, "velocity": 100}],
            "texture": [{"part": "texture", "pitch": 72, "start": 0.0, "duration": 0.5, "velocity": 60}],
        },
    }


def test_score_in_unit_range_and_complete():
    arr = _arrangement([60, 65, 67, 60])
    result = technical_score(arr, {}, VALID_CHECKS)
    assert 0.0 <= result["technical_score"] <= 1.0
    assert result["completeness"] == 1.0
    assert result["validity_gate"] == 1.0
    assert {"groove_density", "part_balance", "dynamic_shape", "audio_health"} <= set(result["features"])
    assert "feature_weights" in result and "score_summary" in result


def test_scorer_discriminates_between_progressions():
    # Static one-chord loop vs a varied, resolving progression.
    static = technical_score(_arrangement([60, 60, 60, 60]), {}, VALID_CHECKS)
    varied = technical_score(_arrangement([60, 65, 67, 62, 64, 60]), {}, VALID_CHECKS)
    assert varied["technical_score"] != static["technical_score"]
    assert varied["technical_score"] > static["technical_score"]


def test_invalid_audio_is_gated_down():
    arr = _arrangement([60, 65, 67, 60])
    good = technical_score(arr, {}, VALID_CHECKS)
    silent = technical_score(arr, {}, {"checks": {"not_silent": False, "peak_ok": True, "duration_ok": True}})
    assert silent["validity_gate"] == 0.4
    assert silent["technical_score"] < good["technical_score"]


def test_rendered_audio_metrics_affect_score():
    arr = _arrangement([60, 65, 67, 60])
    weak = technical_score(arr, {"peak": 0.2, "rms": 0.01}, VALID_CHECKS)
    healthy = technical_score(arr, {"peak": 0.89, "rms": 0.16}, VALID_CHECKS)
    assert healthy["features"]["audio_health"] > weak["features"]["audio_health"]
    assert healthy["technical_score"] > weak["technical_score"]


def test_part_balance_comes_from_generated_notes():
    balanced = technical_score(_arrangement([60, 65, 67, 60]), {"peak": 0.89, "rms": 0.16}, VALID_CHECKS)
    sparse = _arrangement([60, 65, 67, 60])
    sparse["parts"]["bass"] = []
    sparse_result = technical_score(sparse, {"peak": 0.89, "rms": 0.16}, VALID_CHECKS)
    assert balanced["features"]["part_balance"] > sparse_result["features"]["part_balance"]
    assert balanced["technical_score"] > sparse_result["technical_score"]
