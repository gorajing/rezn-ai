from pathlib import Path
import math
import wave

from rezn_ai.eval.audio_metrics import measure_wav
from rezn_ai.eval.mix_checks import evaluate_metrics


def _write_sine(path: Path, *, seconds: float = 1.0, sample_rate: int = 48_000) -> None:
    frames = int(seconds * sample_rate)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        for i in range(frames):
            sample = round(math.sin(i / sample_rate * math.tau * 440) * 10_000)
            data = int(sample).to_bytes(2, "little", signed=True)
            wav.writeframesraw(data + data)


def test_measure_wav_reports_basic_metrics(tmp_path: Path):
    path = tmp_path / "tone.wav"
    _write_sine(path)

    metrics = measure_wav(path)

    assert metrics["channels"] == 2
    assert metrics["sample_rate"] == 48_000
    assert metrics["duration_seconds"] == 1.0
    assert metrics["peak"] > 0.25
    assert metrics["rms"] > 0.1


def test_evaluate_metrics_flags_short_audio(tmp_path: Path):
    path = tmp_path / "short.wav"
    _write_sine(path, seconds=1.0)

    result = evaluate_metrics(measure_wav(path), min_duration_seconds=60.0)

    assert result["passed"] is False
    assert result["checks"]["duration_ok"] is False
    assert result["checks"]["not_silent"] is True

