"""Generator engine backed by the clean-room orchestrator pipeline.

Implements :class:`GeneratorEngine` using ``render.preview_synth`` and
``eval.scoring.technical_score`` — the production path for the API and CLI.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..memory.taste import PlanningBias

from ..agents.llm_agents import critique, propose_plan
from ..agents.refinement_nudges import nudges_from_guidance
from ..agents.schemas import CreativeBrief as AgentBrief
from ..eval.audio_metrics import measure_wav
from ..eval.mix_checks import evaluate_metrics
from ..eval.scoring import technical_score
from ..models import CreativeBrief, new_id
from ..music.composition import compose_arrangement
from ..music.prompt_policy import build_internal_prompt, default_prompt_policy
from ..music.sound_profile import DrumKit, PromptPolicy, kit_features
from ..music.midi import export_midi_parts
from ..provenance import write_json
from ..render.preview_synth import full_band_start_seconds, write_preview_wav
from ..tracing.weave_client import current_call_id, weave_op
from .engine import CandidateResult
from .strategies import CandidateParams, plan_candidates, variant_params


class ReznGeneratorEngine:
    """GeneratorEngine using the clean-room preview synth + discriminating scorer."""

    def __init__(self, *, preview_seconds: float = 12.0, sample_rate: int = 22_050) -> None:
        self.preview_seconds = preview_seconds
        self.sample_rate = sample_rate

    @weave_op("orchestrate_composers")
    def orchestrate_batch(
        self,
        brief: CreativeBrief,
        batch_id: str,
        artifacts_root: Path,
        *,
        bias: "PlanningBias | None" = None,
    ) -> list[CandidateResult]:
        plan = plan_candidates(
            prompt=brief.prompt,
            key=brief.key,
            mode=brief.mode,
            tempo=brief.tempo,
            count=brief.candidate_count,
            bias=bias,
        )
        guidance = list(bias.suggestions) if bias is not None else None
        policies = bias.prompt_policies if bias is not None else {}
        results = [
            self._render(
                batch_id, artifacts_root, params, brief, guidance,
                prompt_policy=policies.get(params.strategy),
            )
            for params in plan
        ]
        results.sort(key=lambda r: r.technical_score, reverse=True)
        return results

    @weave_op("compose_variant")
    def generate_variant(
        self,
        brief: CreativeBrief,
        batch_id: str,
        artifacts_root: Path,
        parent: Any,
        salt: int = 0,
        *,
        guidance: list[str] | None = None,
    ) -> CandidateResult:
        parent_params = CandidateParams(
            parent.strategy, parent.seed, parent.key, parent.mode, parent.tempo
        )
        # Reflection/feedback directives shape the variant; fall back to the
        # parent's own note when no explicit guidance was supplied.
        if guidance is None and getattr(parent, "feedback", None):
            guidance = [parent.feedback]
        parent_features: dict[str, float] | None = None
        scores = getattr(parent, "scores", None)
        if isinstance(scores, dict):
            raw = scores.get("features")
            if isinstance(raw, dict):
                parent_features = {str(k): float(v) for k, v in raw.items()}

        parent_profile_id = getattr(parent, "profile_id", None) or None
        # Continue the parent's prompt arm so a variant stays on the same prompt line.
        parent_policy = getattr(parent, "prompt_policy", None) or None
        nudges = nudges_from_guidance(guidance, parent_features=parent_features)
        # When the reflector emitted change directives, micro-search a few seeds and
        # keep the highest-scoring variant — bounded hill-climb within the session.
        changing = bool(
            guidance
            and any(g.lower().startswith("change:") for g in guidance)
            and nudges.has_nudges
        )
        if changing:
            best: CandidateResult | None = None
            for offset in (0, 1, 2):
                params = variant_params(parent_params, salt + offset * 31)
                result = self._render(
                    batch_id,
                    artifacts_root,
                    params,
                    brief,
                    guidance,
                    parent_features=parent_features,
                    nudges=nudges,
                    parent_profile_id=parent_profile_id,
                    prompt_policy=parent_policy,
                )
                if best is None or result.technical_score > best.technical_score:
                    best = result
            assert best is not None
            return best

        return self._render(
            batch_id,
            artifacts_root,
            variant_params(parent_params, salt),
            brief,
            guidance,
            parent_features=parent_features,
            nudges=nudges,
            parent_profile_id=parent_profile_id,
            prompt_policy=parent_policy,
        )

    @weave_op("compose_candidate")
    def _render(
        self,
        batch_id: str,
        artifacts_root: Path,
        params: CandidateParams,
        brief: CreativeBrief,
        guidance: list[str] | None = None,
        *,
        parent_features: dict[str, float] | None = None,
        nudges: Any | None = None,
        parent_profile_id: str | None = None,
        prompt_policy: dict[str, Any] | None = None,
    ) -> CandidateResult:
        candidate_id = new_id("cand")
        candidate_dir = Path(artifacts_root) / "batches" / batch_id / candidate_id

        # Optional W&B Inference enrichment. Both calls gate internally on
        # REZN_ENABLE_INFERENCE: with it off they return deterministic fallbacks
        # (zero plan nudges, a reproducible critic score), so default behavior and
        # the test suite are unchanged; with it on, the web demo shows live agents.
        agent_brief = AgentBrief(
            text=brief.prompt,
            key=brief.key,
            mode=brief.mode,
            tempo=brief.tempo,
            candidate_count=brief.candidate_count,
        )
        det_nudges = nudges or nudges_from_guidance(guidance, parent_features=parent_features)
        proposal = propose_plan(
            agent_brief, params.strategy, guidance=guidance, nudges=det_nudges
        )
        seed = params.seed + proposal.seed_jitter
        tempo = max(60.0, min(200.0, params.tempo + proposal.tempo_delta))
        mode = proposal.mode or params.mode
        energy = max(0.0, min(1.0, float(getattr(brief, "energy", 0.5)) + det_nudges.energy_delta))

        # The candidate's INTERNAL prompt: the UI brief is only a starter; each
        # strategy augments it from its PromptPolicy (descriptors minus avoided
        # traits). The default strategy returns the brief unchanged (byte-identity).
        policy = PromptPolicy.from_dict(prompt_policy) if prompt_policy else default_prompt_policy(params.strategy)
        internal_prompt = build_internal_prompt(brief.prompt, strategy=params.strategy, policy=policy)

        arrangement = compose_arrangement(
            title=f"{batch_id}:{params.strategy}",
            key=params.key,
            mode=mode,
            tempo=tempo,
            seed=seed,
            strategy=params.strategy,
            energy=energy,
            prompt=internal_prompt,
        )
        arrangement_path = candidate_dir / "arrangement.json"
        write_json(arrangement_path, arrangement)

        # Capture the resolved SoundProfile from the arrangement (the source of
        # truth for what was rendered): pitched voices + the drum kit, plus the
        # learnable drum features. drum_kit is omitted from the arrangement JSON
        # when it equals the kernel (byte-identity), so default to the kernel here.
        voices = dict(arrangement.get("voices") or {})
        kit_data = arrangement.get("drum_kit")
        kit = DrumKit.from_dict(kit_data) if kit_data else DrumKit.kernel()
        profile_features = kit_features(kit)
        # Content-addressed profile id: deterministic + lets identical resolved
        # profiles dedup/reuse in the Redis profiles store. Excludes the id itself.
        _content = json.dumps(
            {
                "style": arrangement.get("identity", {}).get("strategy"),
                "genre": arrangement.get("identity", {}).get("genre"),
                "voices": voices,
                "drum_kit": kit.to_dict(),
                "features": profile_features,
            },
            sort_keys=True,
        )
        profile_id = "prof_" + hashlib.sha256(_content.encode("utf-8")).hexdigest()[:12]
        sound_profile_snapshot = {
            "profile_id": profile_id,
            "parent_profile_id": parent_profile_id,
            "policy_version": 0,  # set by the contrastive policy update (Workstream E)
            "style": arrangement.get("identity", {}).get("strategy"),
            "genre": arrangement.get("identity", {}).get("genre"),
            "voices": voices,
            "drum_kit": kit.to_dict(),
            "features": profile_features,
            "internal_prompt": internal_prompt,
            "prompt_policy": policy.to_dict(),
        }

        # Preview the full-band section (not the quiet intro) so the strategy's
        # drums/bass/density are audible in a short clip.
        audio_path = candidate_dir / "renders" / "preview.wav"
        write_preview_wav(
            arrangement,
            audio_path,
            sample_rate=self.sample_rate,
            max_seconds=self.preview_seconds,
            start_seconds=full_band_start_seconds(arrangement),
        )

        midi_paths = export_midi_parts(arrangement, candidate_dir / "midi")
        metrics = measure_wav(audio_path)
        # Previews are intentionally short, so the validity gate uses a small
        # duration floor rather than the release-grade 60s default.
        checks = evaluate_metrics(metrics, min_duration_seconds=max(0.1, self.preview_seconds * 0.5))
        score = technical_score(arrangement, metrics, checks)
        critic = critique(arrangement, metrics, agent_brief)

        return CandidateResult(
            candidate_id=candidate_id,
            strategy=params.strategy,
            seed=seed,
            key=params.key,
            mode=mode,
            tempo=tempo,
            technical_score=score["technical_score"],
            arrangement=arrangement,
            scores={
                **score,
                "audio": metrics,
                "checks": checks["checks"],
                "critic_score": critic.critic_score,
                "critic": {
                    "score": critic.critic_score,
                    "reasons": list(critic.reasons),
                    "source": critic.source,
                },
                "composer_plan": {
                    "strategy": params.strategy,
                    "seed_jitter": proposal.seed_jitter,
                    "tempo_delta": proposal.tempo_delta,
                    "mode": proposal.mode,
                    "intent": proposal.intent,
                    "source": proposal.source,
                },
                "refinement_nudges": {
                    "energy_delta": det_nudges.energy_delta,
                    "tempo_delta": det_nudges.tempo_delta,
                    "seed_jitter": det_nudges.seed_jitter,
                    "source": det_nudges.source,
                    "intent": det_nudges.intent,
                },
            },
            reasons=list(score["reasons"]),
            arrangement_path=arrangement_path,
            audio_path=audio_path,
            midi_paths=midi_paths,
            params=params,
            weave_call_id=current_call_id(),
            profile_id=profile_id,
            sound_profile=sound_profile_snapshot,
            internal_prompt=internal_prompt,
            prompt_policy=policy.to_dict(),
            drum_kit=kit.to_dict(),
            voices=voices,
            profile_features=profile_features,
            parent_profile_id=parent_profile_id,
        )
