"""Optional W&B Inference enrichment layer with deterministic fallback.

These are the seams the Weave / W&B-Inference workstream plugs into. Each function
tries a W&B Inference call when credentials are present, and otherwise returns a
deterministic fallback so the batch loop never depends on the network or on
credits. Both paths are Weave-traced.

Design contract (why the broad ``except`` below is correct here): the LLM is a
*best-effort enrichment* on top of a deterministic core. A slow or failing
inference call must never sink a live demo, so any failure degrades to the
deterministic fallback and records *why* in the ``source`` field rather than
raising. The deterministic fallback is the single source of truth for
reproducibility and is what the test suite exercises.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass

from ..tracing.weave_client import weave_op
from .schemas import CreativeBrief

# W&B Inference endpoint + default model (WeaveHacks sponsor stack).
WANDB_INFERENCE_BASE_URL = "https://api.inference.wandb.ai/v1"
DEFAULT_INFERENCE_MODEL = "openai/gpt-oss-120b"
# Direct-OpenAI fallback model, used only when no W&B key is present.
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"

# Per-strategy creative personas used to steer the LLM prompt (credit: Vijay's
# strategy defaults). These shape *prompting* only; the deterministic fallback
# ignores them, so they never affect reproducibility.
STRATEGY_PERSONAS: dict[str, str] = {
    "groove_architect": "tight pocket rhythm, drums-forward, minimal top-end; lock kick and bass",
    "harmony_driver": "lush chords and melodic inner voices; clear root motion every couple of bars",
    "texture_builder": "atmospheric layers, pads-forward, slow evolution; drums minimalist",
    "energy_curve": "dynamic arc with strong buildup and drop, high intro/climax contrast",
    "wildcard_mutator": "experimental polyrhythm, unexpected harmonic turns, modal borrowing",
}


@dataclass(frozen=True)
class PlanProposal:
    """Musical-parameter nudges for one candidate.

    ``seed_jitter`` / ``tempo_delta`` / ``mode`` are applied on top of the brief
    by the orchestrator. The deterministic fallback uses zero nudges so it
    reproduces the original plan exactly. ``source`` records where the values
    came from so a judge can see, in the trace, whether inference was used.
    """

    strategy: str
    seed_jitter: int
    tempo_delta: float
    mode: str | None
    intent: str
    source: str  # "wandb_inference" | "fallback" | "fallback:<Reason>"


@dataclass(frozen=True)
class CritiqueResult:
    """LLM (or fallback) critic opinion in 0..1 plus short human-readable reasons."""

    critic_score: float
    reasons: tuple[str, ...]
    source: str


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def inference_enabled() -> bool:
    """True only when inference is explicitly opted in *and* a key is present.

    Deterministic fallback is the default on purpose. The W&B key in ``.env`` is
    there for Weave *tracing*; its mere presence must not silently flip the whole
    pipeline into non-deterministic, credit-spending LLM mode. Set
    ``REZN_ENABLE_INFERENCE=1`` to go live (e.g. for the demo or to test prompts).
    """
    if os.getenv("REZN_ENABLE_INFERENCE", "").strip().lower() not in ("1", "true", "yes"):
        return False
    return bool(
        os.getenv("WANDB_INFERENCE_API_KEY")
        or os.getenv("WANDB_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )


def _inference_client():
    """Return ``(client, model)``. Prefer W&B Inference (sponsor credits); fall
    back to direct OpenAI only when no W&B key is present."""
    from openai import OpenAI  # optional at runtime; imported lazily

    wandb_key = os.getenv("WANDB_INFERENCE_API_KEY") or os.getenv("WANDB_API_KEY")
    if wandb_key:
        project = os.getenv("WEAVE_PROJECT", "rezn-ai/rezn-ai")
        client = OpenAI(base_url=WANDB_INFERENCE_BASE_URL, api_key=wandb_key, project=project)
        return client, os.getenv("WANDB_INFERENCE_MODEL", DEFAULT_INFERENCE_MODEL)
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"]), DEFAULT_OPENAI_MODEL


def _parse_json_object(content: str) -> dict:
    """Extract the first JSON object from a model response."""
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in model response")
    return json.loads(content[start : end + 1])


# --------------------------------------------------------------------------- #
# propose_plan: pre-composition creative nudges
# --------------------------------------------------------------------------- #

def _fallback_plan(strategy: str) -> PlanProposal:
    return PlanProposal(
        strategy=strategy,
        seed_jitter=0,
        tempo_delta=0.0,
        mode=None,
        intent=f"deterministic {strategy} variation",
        source="fallback",
    )


def _coerce_plan(strategy: str, raw: dict) -> PlanProposal:
    mode = raw.get("mode")
    if mode not in ("major", "minor"):
        mode = None
    return PlanProposal(
        strategy=strategy,
        seed_jitter=int(raw.get("seed_jitter", 0)) % 9973,
        tempo_delta=_clamp(float(raw.get("tempo_delta", 0.0)), -12.0, 12.0),
        mode=mode,
        intent=str(raw.get("intent", f"{strategy} variation"))[:200],
        source="wandb_inference",
    )


def _llm_propose_plan(brief: CreativeBrief, strategy: str) -> PlanProposal:
    client, model = _inference_client()
    persona = STRATEGY_PERSONAS.get(strategy, strategy)
    system = (
        "You are a music director shaping ONE candidate in a batch. "
        "Respond with a compact JSON object only, no prose. "
        "Fields: seed_jitter (int 0-9000, how far to explore from the base idea), "
        "tempo_delta (float -12..12 BPM), mode ('major'|'minor'|null to keep the brief), "
        "intent (<=20 words describing this candidate's creative angle)."
    )
    user = (
        f"Brief: {brief.text}\nKey: {brief.key}\nMode: {brief.mode}\n"
        f"Tempo: {brief.tempo} BPM\nStrategy persona ({strategy}): {persona}\n"
        "Give this candidate a distinct angle that fits the strategy persona."
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.9,
    )
    return _coerce_plan(strategy, _parse_json_object(response.choices[0].message.content or ""))


@weave_op("propose_plan")
def propose_plan(brief: CreativeBrief, strategy: str) -> PlanProposal:
    """Propose creative nudges for a candidate (W&B Inference, deterministic fallback)."""
    fallback = _fallback_plan(strategy)
    if not inference_enabled():
        return fallback
    try:
        return _llm_propose_plan(brief, strategy)
    except Exception as exc:  # best-effort enrichment; degrade to deterministic plan
        return PlanProposal(**{**asdict(fallback), "source": f"fallback:{type(exc).__name__}"})


# --------------------------------------------------------------------------- #
# critique: post-composition critic opinion (fills CandidateScore.critic_score)
# --------------------------------------------------------------------------- #

def _fallback_critique(arrangement: dict, metrics: dict) -> CritiqueResult:
    """Deterministic critic proxy from note density and audio warmth.

    Distinct from ``technical_score`` on purpose: it gives the critic axis a
    little independent signal so the field is meaningful even with no LLM, and
    is fully reproducible.
    """
    parts = arrangement.get("parts", {})
    note_count = sum(len(notes) for notes in parts.values())
    density = _clamp(note_count / 400.0)
    rms = float(metrics.get("rms", 0.0))
    warmth = _clamp(rms / 0.2)
    score = round(0.5 * density + 0.5 * warmth, 4)
    return CritiqueResult(
        critic_score=score,
        reasons=(f"note density {density:.2f}", f"audio warmth {warmth:.2f}"),
        source="fallback",
    )


def _coerce_critique(raw: dict) -> CritiqueResult:
    score = _clamp(float(raw.get("critic_score", raw.get("score", 0.0))))
    reasons_raw = raw.get("reasons", [])
    if isinstance(reasons_raw, str):
        reasons = (reasons_raw[:200],)
    else:
        reasons = tuple(str(r)[:200] for r in list(reasons_raw)[:5])
    return CritiqueResult(round(score, 4), reasons or ("no reasons given",), "wandb_inference")


def _llm_critique(arrangement: dict, metrics: dict, brief: CreativeBrief) -> CritiqueResult:
    client, model = _inference_client()
    identity = arrangement.get("identity", {})
    parts = arrangement.get("parts", {})
    part_summary = {name: len(notes) for name, notes in parts.items()}
    system = (
        "You are a discerning music critic scoring ONE candidate against a brief. "
        "Respond with a compact JSON object only: critic_score (float 0..1) and "
        "reasons (array of <=5 short strings). Judge brief fit and musicality."
    )
    user = (
        f"Brief: {brief.text}\nKey/Mode: {identity.get('key')} {identity.get('mode')}\n"
        f"Tempo: {identity.get('tempo')} BPM\nPart note counts: {part_summary}\n"
        f"Audio: peak={metrics.get('peak')}, rms={metrics.get('rms')}, "
        f"duration={metrics.get('duration_seconds')}s"
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.3,
    )
    return _coerce_critique(_parse_json_object(response.choices[0].message.content or ""))


@weave_op("critique_candidate")
def critique(arrangement: dict, metrics: dict, brief: CreativeBrief) -> CritiqueResult:
    """Score a finished candidate (W&B Inference, deterministic fallback)."""
    fallback = _fallback_critique(arrangement, metrics)
    if not inference_enabled():
        return fallback
    try:
        return _llm_critique(arrangement, metrics, brief)
    except Exception as exc:  # best-effort enrichment; degrade to deterministic critic
        return CritiqueResult(
            critic_score=fallback.critic_score,
            reasons=fallback.reasons + (f"llm_error:{type(exc).__name__}",),
            source=f"fallback:{type(exc).__name__}",
        )
