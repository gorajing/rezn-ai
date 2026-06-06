"""LLM-powered composer (propose_plan) and critic (critique) using W&B Inference.

Both functions degrade gracefully: when no API key is available they return
deterministic defaults so the demo never breaks if inference is slow or unavailable.

The orchestrator calls these as plain functions; no class instantiation needed.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..tracing.weave_client import weave_op
from .schemas import CreativeBrief

_WB_INFERENCE_BASE = "https://api.inference.wandb.ai/v1"
_WB_INFERENCE_MODEL = "openai/gpt-oss-120b"
_OPENAI_FALLBACK_MODEL = "gpt-4o-mini"

_STRATEGY_DEFAULTS: dict[str, dict[str, Any]] = {
    "groove_architect": {
        "energy": 0.75,
        "section_feel": "tight pocket rhythm, drums-forward, minimal top-end",
        "part_emphasis": ["drums", "bass"],
        "density": "medium-high",
        "notes": "Lock kick and bass tightly; keep harmony sparse",
    },
    "harmony_driver": {
        "energy": 0.60,
        "section_feel": "harmonic movement, lush chords, melodic inner voices",
        "part_emphasis": ["harmony", "bass"],
        "density": "medium",
        "notes": "Rich voicings with clear root motion every 2 bars",
    },
    "texture_builder": {
        "energy": 0.50,
        "section_feel": "atmospheric layers, pads-forward, slow evolution",
        "part_emphasis": ["texture", "harmony"],
        "density": "medium-low",
        "notes": "Slow filter sweeps and detuned layers; drums minimalist",
    },
    "energy_curve": {
        "energy": 0.80,
        "section_feel": "dynamic buildup and drop, high contrast intro/climax",
        "part_emphasis": ["drums", "harmony", "texture"],
        "density": "high",
        "notes": "Strong energy arc: intro 40% → climax 100% → outro 60%",
    },
    "wildcard_mutator": {
        "energy": 0.65,
        "section_feel": "experimental polyrhythm, unexpected harmonic turns",
        "part_emphasis": ["texture", "drums"],
        "density": "variable",
        "notes": "Take creative risks; off-beat accents and modal borrowing welcome",
    },
}


def _get_client() -> tuple[Any, str] | tuple[None, None]:
    """Return (OpenAI-compatible client, model name) or (None, None) if no key."""
    try:
        from openai import OpenAI
    except ModuleNotFoundError:
        return None, None

    # Prefer W&B Inference (charges against hackathon credits)
    wandb_key = os.environ.get("WANDB_API_KEY")
    if wandb_key:
        return OpenAI(base_url=_WB_INFERENCE_BASE, api_key=wandb_key), _WB_INFERENCE_MODEL

    openai_key = os.environ.get("OPENAI_API_KEY")
    if openai_key:
        return OpenAI(api_key=openai_key), _OPENAI_FALLBACK_MODEL

    return None, None


def _parse_json(content: str) -> dict[str, Any]:
    """Extract JSON from LLM response, handling markdown fences."""
    if "```json" in content:
        content = content.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in content:
        content = content.split("```", 1)[1].split("```", 1)[0].strip()
    return json.loads(content)


@weave_op("propose_plan")
def propose_plan(brief: CreativeBrief, strategy: str) -> dict[str, Any]:
    """Propose musical parameters for one composer strategy using W&B Inference.

    The orchestrator feeds this output into the compose step alongside the brief.
    Falls back to hard-coded strategy defaults when no API key is set.

    Args:
        brief:    The creative brief (key, mode, tempo, text).
        strategy: One of groove_architect | harmony_driver | texture_builder |
                  energy_curve | wildcard_mutator.

    Returns:
        {
          "key":          str,        # may nudge brief.key (enharmonic only)
          "mode":         str,        # typically preserves brief.mode
          "tempo":        float,      # may nudge ±4 BPM for feel
          "section_feel": str,        # textual direction per section
          "energy":       float,      # 0.0–1.0 overall intensity
          "part_emphasis": list[str], # parts to make prominent
          "density":      str,        # "low"|"medium"|"medium-high"|"high"|"variable"
          "notes":        str,        # extra guidance for compose step
        }
    """
    default = _STRATEGY_DEFAULTS.get(strategy, _STRATEGY_DEFAULTS["harmony_driver"])
    base: dict[str, Any] = {"key": brief.key, "mode": brief.mode, "tempo": brief.tempo, **default}

    client, model = _get_client()
    if client is None:
        return base

    system = (
        f"You are a music production AI with the '{strategy}' creative strategy. "
        "Given a brief, output musical parameters as compact JSON. "
        "You may nudge key (enharmonic only), mode, or tempo (±4 BPM max). "
        "Output ONLY valid JSON — no markdown, no prose."
    )
    user = (
        f"Brief: {brief.text}\n"
        f"Key: {brief.key}  Mode: {brief.mode}  Tempo: {brief.tempo} BPM\n\n"
        "Respond with JSON keys: key, mode, tempo, section_feel, energy (0.0-1.0), "
        "part_emphasis (array), density, notes."
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.7,
            max_tokens=350,
        )
        params = _parse_json(resp.choices[0].message.content)
        return {**base, **params}
    except Exception:
        return base


def _rule_based_critique(arrangement: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    """Deterministic fallback when no API key is available."""
    parts = arrangement.get("parts", {})
    form = arrangement.get("form", {})
    sections = form.get("sections", [])

    expected = {"harmony", "bass", "drums", "texture"}
    completeness = len(set(parts.keys()) & expected) / len(expected)
    section_score = min(1.0, len(sections) / 4.0)

    lufs = metrics.get("lufs_i")
    audio_score = 0.7
    if lufs is not None and -18 <= lufs <= -9:
        audio_score = 1.0
    peak = metrics.get("peak_dbfs")
    if peak is not None and peak > -0.5:
        audio_score *= 0.7

    score = round(completeness * 0.4 + section_score * 0.3 + audio_score * 0.3, 4)
    reasons = [
        f"{len(set(parts.keys()) & expected)}/{len(expected)} required parts present",
        f"{len(sections)} sections",
        f"LUFS {lufs:.1f}" if lufs is not None else "audio metrics unavailable",
        "deterministic fallback (no API key set)",
    ]
    return {"critic_score": score, "reasons": reasons}


@weave_op("critique")
def critique(arrangement: dict[str, Any], metrics: dict[str, Any]) -> dict[str, Any]:
    """Evaluate an arrangement using W&B Inference.

    The orchestrator stores the returned critic_score in CandidateScore.
    Falls back to rule-based scoring when no API key is set.

    Args:
        arrangement: Output of compose_arrangement().
        metrics:     Output of measure_wav() — lufs_i, peak_dbfs, stereo_width, etc.

    Returns:
        {
          "critic_score": float,     # 0.0–1.0 (fills CandidateScore.critic_score)
          "reasons":      list[str], # 2–4 short bullet points
        }
    """
    fallback = _rule_based_critique(arrangement, metrics)

    client, model = _get_client()
    if client is None:
        return fallback

    identity = arrangement.get("identity", {})
    parts = arrangement.get("parts", {})
    form = arrangement.get("form", {})

    system = (
        "You are a professional mastering engineer and music critic. "
        "Evaluate the arrangement below and return ONLY valid JSON with exactly: "
        "{'critic_score': <float 0.0-1.0>, 'reasons': [<2-4 short strings>]}."
    )
    user = (
        f"Key: {identity.get('key')}  Mode: {identity.get('mode')}  "
        f"Tempo: {identity.get('tempo')} BPM\n"
        f"Parts: {list(parts.keys())}\n"
        f"Sections: {len(form.get('sections', []))}\n"
        f"LUFS: {metrics.get('lufs_i', 'N/A')}  "
        f"Peak: {metrics.get('peak_dbfs', 'N/A')} dBFS  "
        f"Stereo width: {metrics.get('stereo_width', 'N/A')}\n"
        "Score this arrangement."
    )

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.3,
            max_tokens=300,
        )
        result = _parse_json(resp.choices[0].message.content)
        raw_score = float(result.get("critic_score", fallback["critic_score"]))
        # Normalise: model sometimes returns 0-10 scale
        if raw_score > 1.0:
            raw_score /= 10.0
        return {
            "critic_score": round(max(0.0, min(1.0, raw_score)), 4),
            "reasons": result.get("reasons", fallback["reasons"]),
        }
    except Exception:
        return fallback
