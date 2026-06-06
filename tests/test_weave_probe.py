from rezn_ai.weave_probe import score_lufs_probe


def test_score_lufs_probe_passes_close_measurement() -> None:
    result = score_lufs_probe(-12.0, -12.6)
    assert result["pass"] is True
    assert result["distance"] == 0.6


def test_score_lufs_probe_fails_distant_measurement() -> None:
    result = score_lufs_probe(-12.0, -18.5)
    assert result["pass"] is False
    assert result["distance"] == 6.5

