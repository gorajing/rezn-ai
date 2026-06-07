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

from ..music.brief_parser import parse_musical_brief
from ..music.theory import PITCH_CLASSES, normalize_key
from ..config import inference_required
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

def _fallback_plan(strategy: str, *, nudges: "RefinementNudges | None" = None) -> PlanProposal:
    from .refinement_nudges import RefinementNudges, nudges_from_guidance

    n = nudges or RefinementNudges()
    return PlanProposal(
        strategy=strategy,
        seed_jitter=n.seed_jitter,
        tempo_delta=n.tempo_delta,
        mode=None,
        intent=n.intent if n.has_nudges else f"deterministic {strategy} variation",
        source="fallback+guidance" if n.has_nudges else "fallback",
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


def _guidance_block(guidance: list[str] | None) -> str:
    """Render the producer's prior taste signals as a prompt section, or ''."""
    if not guidance:
        return ""
    lines = "\n".join(f"- {g}" for g in guidance[:5])
    return (
        "\nThe producer's prior curation on similar briefs (honor it where it fits "
        f"the strategy persona):\n{lines}\n"
    )


def _llm_propose_plan(
    brief: CreativeBrief, strategy: str, guidance: list[str] | None = None
) -> PlanProposal:
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
        f"{_guidance_block(guidance)}"
        "Give this candidate a distinct angle that fits the strategy persona."
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.9,
        max_tokens=600,  # headroom so the JSON object is never truncated
    )
    return _coerce_plan(strategy, _parse_json_object(response.choices[0].message.content or ""))


@weave_op("propose_plan")
def propose_plan(
    brief: CreativeBrief,
    strategy: str,
    *,
    guidance: list[str] | None = None,
    nudges: "RefinementNudges | None" = None,
) -> PlanProposal:
    """Propose creative nudges for a candidate (W&B Inference, deterministic fallback).

    ``guidance`` carries the producer's prior taste signals (recalled from Agent
    Memory). It only shapes the live LLM prompt; the deterministic fallback ignores
    it, so reproducibility and the test suite are unchanged.

    When ``nudges`` is supplied (refinement path), the deterministic fallback applies
    those bounded adjustments even without an LLM; live inference still runs when enabled.
    """
    from .refinement_nudges import RefinementNudges, nudges_from_guidance

    det_nudges = nudges or nudges_from_guidance(guidance)
    fallback = _fallback_plan(strategy, nudges=det_nudges)
    if not inference_enabled():
        if inference_required():
            raise RuntimeError(
                "Live inference is required (REZN_PRODUCTION or REZN_INFERENCE_REQUIRED) "
                "but REZN_ENABLE_INFERENCE is off or no API key is configured."
            )
        return fallback
    try:
        return _llm_propose_plan(brief, strategy, guidance)
    except Exception as exc:
        if inference_required():
            raise RuntimeError(f"Live inference failed for propose_plan: {exc}") from exc
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
        max_tokens=500,  # headroom so the JSON object is never truncated
    )
    return _coerce_critique(_parse_json_object(response.choices[0].message.content or ""))


@weave_op("critique_candidate")
def critique(arrangement: dict, metrics: dict, brief: CreativeBrief) -> CritiqueResult:
    """Score a finished candidate (W&B Inference, deterministic fallback)."""
    fallback = _fallback_critique(arrangement, metrics)
    if not inference_enabled():
        if inference_required():
            raise RuntimeError(
                "Live inference is required (REZN_PRODUCTION or REZN_INFERENCE_REQUIRED) "
                "but REZN_ENABLE_INFERENCE is off or no API key is configured."
            )
        return fallback
    try:
        return _llm_critique(arrangement, metrics, brief)
    except Exception as exc:
        if inference_required():
            raise RuntimeError(f"Live inference failed for critique: {exc}") from exc
        return CritiqueResult(
            critic_score=fallback.critic_score,
            reasons=fallback.reasons + (f"llm_error:{type(exc).__name__}",),
            source=f"fallback:{type(exc).__name__}",
        )


# --------------------------------------------------------------------------- #
# Phase 2: LLM critic panel + judge (REZN_DEEP_MODE; deterministic fallback)
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class CriticInput:
    """Compact per-candidate view the panel reasons over. Decouples this module from
    the conductor's Candidate model so the panel agents stay unit-testable."""

    candidate_id: str
    strategy: str
    technical_score: float
    features: dict


@dataclass(frozen=True)
class LensVerdict:
    """One lens critic's ranking of all candidates through its single lens."""

    lens: str
    ranking: tuple[str, ...]  # candidate_ids, best -> worst
    favorite: str             # candidate_id ("" when there are no candidates)
    rationale: str
    source: str               # "wandb_inference" | "fallback" | "fallback:<Reason>"


@dataclass(frozen=True)
class JudgeDecision:
    """The judge's aggregate ranking over the lens verdicts + technical scores."""

    ranking: tuple[str, ...]
    winner: str
    rationale: str
    confidence: float  # 0..1
    source: str


# Canonical lens -> scoring-feature groups (single source of truth; the conductor's
# deterministic panel uses these too). Disjoint groups so the lenses genuinely disagree.
LENS_FEATURE_GROUPS: dict[str, tuple[str, ...]] = {
    "groove": ("groove_density", "part_balance"),
    "harmony": ("harmonic_variety", "voice_leading", "resolution", "register_range"),
    "mix": ("dynamic_shape", "audio_health"),
}


def lens_feature_score(features: dict, lens: str) -> float:
    """Deterministic lens score = mean of the lens's feature subset (0..1)."""
    keys = LENS_FEATURE_GROUPS.get(lens, ())
    vals = [_clamp(float(features.get(k, 0.0))) for k in keys]
    return round(sum(vals) / len(vals), 4) if vals else 0.0


def _fallback_lens_verdict(lens: str, candidates: list[CriticInput]) -> LensVerdict:
    ordered = sorted(candidates, key=lambda c: lens_feature_score(c.features, lens), reverse=True)
    ranking = tuple(c.candidate_id for c in ordered)
    fav = ordered[0] if ordered else None
    rationale = (
        f"{lens} favors {fav.strategy} ({lens_feature_score(fav.features, lens):.2f})"
        if fav else "no candidates"
    )
    return LensVerdict(lens, ranking, fav.candidate_id if fav else "", rationale, "fallback")


def _dedupe_ranking(raw_ranking, fallback_ranking: tuple[str, ...]) -> tuple[str, ...]:
    """Coerce a model ranking into the contract: each valid candidate exactly once,
    best->worst. Drops unknown/duplicate ids; appends any the model omitted so no
    candidate is lost."""
    valid = set(fallback_ranking)
    ranking: list[str] = []
    for c in raw_ranking or []:
        cid = str(c)
        if cid in valid and cid not in ranking:
            ranking.append(cid)
    for cid in fallback_ranking:
        if cid not in ranking:
            ranking.append(cid)
    return tuple(ranking)


def _coerce_lens_verdict(lens: str, raw: dict, fallback: LensVerdict) -> LensVerdict:
    ranking = _dedupe_ranking(raw.get("ranking", []), fallback.ranking)
    favorite = ranking[0] if ranking else ""  # the favorite is the top of the ranking
    rationale = str(raw.get("rationale", ""))[:240] or fallback.rationale
    return LensVerdict(lens, ranking, favorite, rationale, "wandb_inference")


def _llm_lens_verdict(lens: str, candidates: list[CriticInput]) -> LensVerdict:
    client, model = _inference_client()
    rows = "\n".join(
        f"- {c.candidate_id} [{c.strategy}] "
        + str({k: round(float(c.features.get(k, 0.0)), 2) for k in LENS_FEATURE_GROUPS.get(lens, ())})
        for c in candidates
    )
    system = (
        f"You are the {lens.upper()} critic on a music panel; judge ONLY through your lens. "
        "Respond with a compact JSON object only: ranking (array of candidate_id best->worst), "
        "favorite (candidate_id), rationale (<=30 words)."
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Candidates:\n{rows}\nRank them by your lens."},
        ],
        temperature=0.4,
        max_tokens=400,
    )
    return _coerce_lens_verdict(
        lens,
        _parse_json_object(response.choices[0].message.content or ""),
        _fallback_lens_verdict(lens, candidates),
    )


@weave_op("lens_critique")
def lens_critique(lens: str, candidates: list[CriticInput]) -> LensVerdict:
    """One panel critic ranking all candidates through one lens. Deep mode -> LLM,
    otherwise a deterministic feature-average. Mirrors ``critique``'s gating + graceful
    fallback: a slow/failing call degrades to the deterministic verdict and records why."""
    from ..config import deep_mode_enabled

    fallback = _fallback_lens_verdict(lens, candidates)
    if not candidates or not deep_mode_enabled():
        return fallback
    try:
        return _llm_lens_verdict(lens, candidates)
    except Exception as exc:
        if inference_required():
            raise RuntimeError(f"Live inference failed for {lens} critic: {exc}") from exc
        return LensVerdict(
            lens, fallback.ranking, fallback.favorite,
            f"{fallback.rationale} (llm_error:{type(exc).__name__})",
            f"fallback:{type(exc).__name__}",
        )


def _fallback_judge(candidates: list[CriticInput]) -> JudgeDecision:
    ordered = sorted(candidates, key=lambda c: c.technical_score, reverse=True)
    ranking = tuple(c.candidate_id for c in ordered)
    win = ordered[0] if ordered else None
    rationale = (
        f"top technical score {win.technical_score:.2f} ({win.strategy})" if win else "no candidates"
    )
    return JudgeDecision(ranking, win.candidate_id if win else "", rationale, 1.0 if win else 0.0, "fallback")


def _coerce_judge(raw: dict, fallback: JudgeDecision) -> JudgeDecision:
    ranking = _dedupe_ranking(raw.get("ranking", []), fallback.ranking)
    winner = ranking[0] if ranking else ""  # the winner is the top of the ranking
    rationale = str(raw.get("rationale", ""))[:240] or fallback.rationale
    confidence = _clamp(float(raw.get("confidence", 0.5)))
    return JudgeDecision(ranking, winner, rationale, round(confidence, 4), "wandb_inference")


def _llm_judge(candidates: list[CriticInput], verdicts: list[LensVerdict]) -> JudgeDecision:
    client, model = _inference_client()
    model = os.getenv("REZN_JUDGE_MODEL") or model  # D5: optional stronger judge
    panel = "\n".join(
        f"- {v.lens}: ranked {list(v.ranking)} (favorite {v.favorite}; {v.rationale})" for v in verdicts
    )
    scores = "\n".join(
        f"- {c.candidate_id} [{c.strategy}] technical={c.technical_score:.2f}" for c in candidates
    )
    system = (
        "You are the head judge of a music panel. Aggregate the lens critics' verdicts and the "
        "technical scores into a final ranking. Respond with a compact JSON object only: ranking "
        "(array of candidate_id best->worst), winner (candidate_id), rationale (<=40 words), "
        "confidence (0..1)."
    )
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": f"Technical scores:\n{scores}\n\nPanel:\n{panel}\n\nDecide."},
        ],
        temperature=0.3,
        max_tokens=400,
    )
    return _coerce_judge(
        _parse_json_object(response.choices[0].message.content or ""), _fallback_judge(candidates)
    )


@weave_op("judge_panel")
def judge_panel(candidates: list[CriticInput], verdicts: list[LensVerdict]) -> JudgeDecision:
    """Aggregate the lens verdicts + technical scores into a reasoned ranking. Deep mode ->
    LLM, otherwise deterministic technical-score order (the current behavior)."""
    from ..config import deep_mode_enabled

    fallback = _fallback_judge(candidates)
    if not candidates or not deep_mode_enabled():
        return fallback
    try:
        return _llm_judge(candidates, verdicts)
    except Exception as exc:
        if inference_required():
            raise RuntimeError(f"Live inference failed for judge: {exc}") from exc
        return JudgeDecision(
            fallback.ranking, fallback.winner,
            f"{fallback.rationale} (llm_error:{type(exc).__name__})",
            fallback.confidence, f"fallback:{type(exc).__name__}",
        )


# --------------------------------------------------------------------------- #
# interpret_brief: read the whole prompt -> musical parameters (the "understanding")
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class BriefInterpretation:
    """What the system understood from the prompt. Traced so it's visible in Weave."""

    key: str
    mode: str
    tempo: float
    energy: float  # 0..1, 0.5 is neutral
    intent: str
    source: str  # "wandb_inference" | "fallback" | "fallback:<Reason>"


def _coerce_interpretation(raw: dict, fb: dict) -> BriefInterpretation:
    key = normalize_key(str(raw.get("key", fb["key"])))
    if key not in PITCH_CLASSES:
        key = fb["key"]
    mode = raw.get("mode")
    if mode not in ("major", "minor"):
        mode = fb["mode"]
    try:
        tempo = max(60.0, min(190.0, float(raw.get("tempo", fb["tempo"]))))
    except (TypeError, ValueError):
        tempo = fb["tempo"]
    try:
        energy = max(0.0, min(1.0, float(raw.get("energy", fb["energy"]))))
    except (TypeError, ValueError):
        energy = fb["energy"]
    intent = str(raw.get("intent", "")).strip()[:200] or "interpreted from brief"
    return BriefInterpretation(key, mode, tempo, energy, intent, "wandb_inference")


def _llm_interpret(prompt: str, fb: dict) -> BriefInterpretation:
    client, model = _inference_client()
    system = (
        "You translate a music creative brief into concrete parameters. Respond with "
        "a compact JSON object only: key (e.g. 'F#','C'), mode ('major'|'minor'), "
        "tempo (BPM integer), energy (0..1), intent (<=15 words capturing the vibe). "
        "Honor any explicit key or BPM in the brief; infer the rest from genre, mood, "
        "instruments, and references."
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": f"Brief: {prompt}"}],
        temperature=0.4,
        max_tokens=300,
    )
    return _coerce_interpretation(_parse_json_object(response.choices[0].message.content or ""), fb)


@weave_op("interpret_brief")
def interpret_brief(
    prompt: str, *, default_mode: str = "minor", default_tempo: float = 120.0
) -> BriefInterpretation:
    """Read the whole prompt into musical parameters (W&B Inference, deterministic fallback)."""
    fb = parse_musical_brief(prompt, default_mode=default_mode, default_tempo=default_tempo)
    fallback = BriefInterpretation(
        key=str(fb["key"]),
        mode=str(fb["mode"]),
        tempo=float(fb["tempo"]),
        energy=float(fb["energy"]),
        intent="keyword interpretation",
        source="fallback",
    )
    if not inference_enabled():
        if inference_required():
            raise RuntimeError(
                "Live inference is required (REZN_PRODUCTION or REZN_INFERENCE_REQUIRED) "
                "but REZN_ENABLE_INFERENCE is off or no API key is configured."
            )
        return fallback
    try:
        return _llm_interpret(prompt, fb)
    except Exception as exc:
        if inference_required():
            raise RuntimeError(f"Live inference failed for interpret_brief: {exc}") from exc
        return BriefInterpretation(**{**asdict(fallback), "source": f"fallback:{type(exc).__name__}"})


# --------------------------------------------------------------------------- #
# reflect_on_feedback: the reflector in the actor→critic→reflector loop
# --------------------------------------------------------------------------- #
#
# After a batch is curated, this agent reads the previous songs (their scores and
# critic reasons) together with the producer's approvals / rejections / notes, and
# synthesizes concrete production directives for the *next* batch: what to keep,
# what to change. Those directives are threaded into the composer agents' prompts,
# so refinement makes meaningful, feedback-driven changes instead of blind reseeds.

@dataclass(frozen=True)
class Reflection:
    """A concrete revision plan derived from prior songs + human feedback."""

    keep: tuple[str, ...]
    change: tuple[str, ...]
    intent: str
    source: str  # "wandb_inference" | "fallback" | "fallback:<Reason>"

    def as_guidance(self) -> list[str]:
        """Flatten into short prompt directives for the composer agents."""
        out = [f"Keep: {k}" for k in self.keep] + [f"Change: {c}" for c in self.change]
        return out[:6]


def _fallback_reflection(signals: list[dict], notes: list[str]) -> Reflection:
    """Deterministic reflection: keep what was approved / scored well, change the rest."""
    keep: list[str] = []
    change: list[str] = []
    for s in signals:
        strat = s.get("strategy", "candidate")
        status = s.get("status", "generated")
        if status in ("approved", "final"):
            keep.append(f"{strat} direction the producer approved")
        elif status == "rejected":
            change.append(f"move away from the {strat} take the producer rejected")
    for note in notes:
        note = (note or "").strip()
        if note:
            change.append(note)
    if not keep and signals:
        top = max(signals, key=lambda s: float(s.get("technical_score", 0.0)))
        keep.append(f"the {top.get('strategy', 'top')} arrangement (highest score)")
    intent = "keep what was approved; address the producer's notes" if (keep or change) else "explore"
    return Reflection(tuple(keep[:4]), tuple(change[:4]), intent, "fallback")


def _llm_reflect(brief_text: str, signals: list[dict], notes: list[str]) -> Reflection:
    client, model = _inference_client()
    summary = "\n".join(
        f"- {s.get('strategy')}: status={s.get('status')}, score={s.get('technical_score')}, "
        f"critic={s.get('critic_score')} ({'; '.join(s.get('critic_reasons', [])[:3])})"
        for s in signals
    )
    note_block = "\n".join(f"- {n}" for n in notes if n) or "(no written notes)"
    system = (
        "You are a music producer's assistant deciding how to improve the NEXT batch "
        "of song candidates from the previous batch and the producer's feedback. "
        "Respond with a compact JSON object only: keep (array of <=4 short strings to "
        "preserve), change (array of <=4 short, concrete production changes to make), "
        "intent (<=15 words). Be specific and musical (groove, density, harmony, energy, "
        "register, dynamics)."
    )
    user = (
        f"Brief: {brief_text}\nPrevious candidates:\n{summary}\n"
        f"Producer notes:\n{note_block}\n"
        "What should the next batch keep and change?"
    )
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.5,
        max_tokens=600,
    )
    raw = _parse_json_object(response.choices[0].message.content or "")
    keep = tuple(str(x)[:120] for x in (raw.get("keep") or [])[:4])
    change = tuple(str(x)[:120] for x in (raw.get("change") or [])[:4])
    intent = str(raw.get("intent", "")).strip()[:200] or "refine from feedback"
    return Reflection(keep, change, intent, "wandb_inference")


@weave_op("reflect_on_feedback")
def reflect_on_feedback(
    brief_text: str, signals: list[dict], *, notes: list[str] | None = None
) -> Reflection:
    """Synthesize prior songs + human feedback into next-batch directives.

    LLM-driven when inference is enabled; otherwise a deterministic reflection that
    keeps approved strategies and turns rejections/notes into change directives.

    Reflection is *advisory*: it shapes the composer prompts but the refinement
    backbone (strategy reweighting, parent selection, threading the producer's
    notes) works without it. So unlike the per-candidate agents, a runtime LLM
    error here degrades to the deterministic reflection — which still incorporates
    the feedback — rather than failing the producer's refine action, even in
    production. A *misconfiguration* (claiming live inference while it is off) is
    still surfaced as an error.
    """
    notes = notes or []
    fallback = _fallback_reflection(signals, notes)
    if not inference_enabled():
        if inference_required():
            raise RuntimeError(
                "Live inference is required (REZN_PRODUCTION or REZN_INFERENCE_REQUIRED) "
                "but REZN_ENABLE_INFERENCE is off or no API key is configured."
            )
        return fallback
    try:
        return _llm_reflect(brief_text, signals, notes)
    except Exception as exc:  # advisory: keep the deterministic reflection (still feedback-aware)
        return Reflection(fallback.keep, fallback.change, fallback.intent, f"fallback:{type(exc).__name__}")
