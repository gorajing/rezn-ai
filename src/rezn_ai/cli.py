"""Command-line interface for the rezn-ai workflow."""

from __future__ import annotations

import argparse
from pathlib import Path

from . import config
from .eval.audio_metrics import measure_wav
from .eval.mix_checks import evaluate_metrics
from .agents.orchestrator import orchestrate_batch, refine_batch
from .agents.schemas import CreativeBrief, HumanFeedback
from .music.composition import compose_arrangement
from .music.midi import export_midi_parts
from .project import create_run, require_run_dir
from .provenance import read_json, record_artifact, record_event, write_json
from .render.preview_synth import preview_path_for_candidate, write_preview_wav


def _cmd_init_run(args: argparse.Namespace) -> int:
    run_dir = create_run(Path(args.root), args.title)
    print(run_dir)
    return 0


def _cmd_compose(args: argparse.Namespace) -> int:
    run_dir = require_run_dir(Path(args.run_dir))
    arrangement = compose_arrangement(
        title=args.title or run_dir.name,
        key=args.key,
        mode=args.mode,
        tempo=args.tempo,
        seed=args.seed,
    )
    arrangement_path = run_dir / config.ARRANGEMENT_NAME
    write_json(arrangement_path, arrangement)
    record_artifact(run_dir / config.MANIFEST_NAME, "arrangement", arrangement_path, "json")
    record_event(
        run_dir / config.MANIFEST_NAME,
        "composition.generated",
        {"key": args.key, "mode": args.mode, "tempo": args.tempo, "seed": args.seed},
    )
    print(arrangement_path)
    return 0


def _cmd_export_midi(args: argparse.Namespace) -> int:
    run_dir = require_run_dir(Path(args.run_dir))
    arrangement = read_json(run_dir / config.ARRANGEMENT_NAME)
    midi_dir = run_dir / config.DEFAULT_MIDI_DIR
    exported = export_midi_parts(arrangement, midi_dir)
    record_event(run_dir / config.MANIFEST_NAME, "midi.exported", {"files": exported})
    for part, path in exported.items():
        record_artifact(run_dir / config.MANIFEST_NAME, f"midi.{part}", Path(path), "midi")
    print(midi_dir)
    return 0


def _cmd_batch(args: argparse.Namespace) -> int:
    brief = CreativeBrief(
        text=args.brief,
        key=args.key,
        mode=args.mode,
        tempo=args.tempo,
        candidate_count=args.count,
    )
    summary = orchestrate_batch(
        brief,
        Path(args.root) / config.DEFAULT_RUNS_DIR,
        run_title=args.title,
        base_seed=args.seed,
    )
    print(f"batch {summary['batch_id']} -> {summary['candidate_count']} candidates")
    for row in summary["ranking"]:
        print(f"  #{row['rank']} {row['candidate_id']}  score={row['technical_score']}")
    return 0


def _cmd_refine(args: argparse.Namespace) -> int:
    batch_json = Path(args.batch_json).resolve()
    prev_summary = read_json(batch_json)
    runs_root = batch_json.parent.parent
    feedback = [HumanFeedback(cid, "approve", args.note) for cid in args.approve]
    feedback += [HumanFeedback(cid, "reject", args.note) for cid in args.reject]
    summary = refine_batch(prev_summary, feedback, runs_root, run_title=args.title)
    print(
        f"refine {summary['batch_id']} (parent {summary['parent_batch_id']}) "
        f"-> {summary['candidate_count']} candidates"
    )
    for line in summary["rationale"]:
        print(f"  {line}")
    for row in summary["ranking"]:
        print(f"  #{row['rank']} {row['candidate_id']}  score={row['technical_score']}")
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    run_dir = require_run_dir(Path(args.run_dir))
    arrangement = read_json(run_dir / config.ARRANGEMENT_NAME)
    preview_path = preview_path_for_candidate(run_dir)
    write_preview_wav(arrangement, preview_path)
    record_artifact(run_dir / config.MANIFEST_NAME, "preview_audio", preview_path, "wav")
    record_event(
        run_dir / config.MANIFEST_NAME,
        "preview.rendered",
        {"path": str(preview_path), "renderer": "rezn_ai.render.preview_synth"},
    )
    print(preview_path)
    return 0


def _cmd_analyze(args: argparse.Namespace) -> int:
    run_dir = require_run_dir(Path(args.run_dir))
    metrics = measure_wav(Path(args.audio_path))
    metrics_path = run_dir / "audio_metrics.json"
    write_json(metrics_path, metrics)
    record_artifact(run_dir / config.MANIFEST_NAME, "audio_metrics", metrics_path, "json")
    record_event(run_dir / config.MANIFEST_NAME, "audio.analyzed", {"audio_path": args.audio_path})
    print(metrics_path)
    return 0


def _cmd_finalize(args: argparse.Namespace) -> int:
    run_dir = require_run_dir(Path(args.run_dir))
    audio_path = Path(args.audio_path)
    metrics = measure_wav(audio_path)
    checks = evaluate_metrics(metrics, min_duration_seconds=args.min_duration)
    final = {
        "schema": "rezn-ai.final.v1",
        "run_id": run_dir.name,
        "selected_audio": str(audio_path),
        "metrics": metrics,
        "release_checks": checks,
    }
    final_path = run_dir / "final_manifest.json"
    write_json(final_path, final)
    record_artifact(run_dir / config.MANIFEST_NAME, "final_manifest", final_path, "json")
    record_event(
        run_dir / config.MANIFEST_NAME,
        "run.finalized",
        {"audio_path": str(audio_path), "passed": checks["passed"]},
    )
    print(final_path)
    return 0 if checks["passed"] else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rezn-ai", description="Create original music with provenance.")
    sub = parser.add_subparsers(dest="command", required=True)

    init_run = sub.add_parser("init-run", help="create a run folder and initial manifest")
    init_run.add_argument("--root", default=".", help="project root")
    init_run.add_argument("--title", required=True, help="run title")
    init_run.set_defaults(func=_cmd_init_run)

    compose = sub.add_parser("compose", help="generate arrangement JSON for a run")
    compose.add_argument("run_dir")
    compose.add_argument("--title", default=None)
    compose.add_argument("--key", required=True)
    compose.add_argument("--mode", default="minor", choices=("major", "minor"))
    compose.add_argument("--tempo", type=float, required=True)
    compose.add_argument("--seed", type=int, required=True)
    compose.set_defaults(func=_cmd_compose)

    export_midi = sub.add_parser("export-midi", help="export MIDI parts for a run")
    export_midi.add_argument("run_dir")
    export_midi.set_defaults(func=_cmd_export_midi)

    render = sub.add_parser("render", help="render deterministic preview audio for a run")
    render.add_argument("run_dir")
    render.set_defaults(func=_cmd_render)

    batch = sub.add_parser("batch", help="run a Weave-traced multi-candidate batch from one brief")
    batch.add_argument("--brief", default="clean-room dark melodic electronic")
    batch.add_argument("--title", default=None, help="batch run folder name")
    batch.add_argument("--key", default="D#")
    batch.add_argument("--mode", default="minor", choices=("major", "minor"))
    batch.add_argument("--tempo", type=float, default=128.0)
    batch.add_argument("--count", type=int, default=4, help="number of candidates")
    batch.add_argument("--seed", type=int, default=77, help="base seed")
    batch.add_argument("--root", default=".", help="project root")
    batch.set_defaults(func=_cmd_batch)

    refine = sub.add_parser(
        "refine",
        help="run a feedback-driven refinement batch from a prior batch.json",
    )
    refine.add_argument("batch_json", help="path to a prior batch's batch.json")
    refine.add_argument("--approve", nargs="*", default=[], metavar="CAND_ID", help="candidate ids to approve")
    refine.add_argument("--reject", nargs="*", default=[], metavar="CAND_ID", help="candidate ids to reject")
    refine.add_argument("--title", default=None, help="child batch folder name")
    refine.add_argument("--note", default="", help="optional feedback note")
    refine.set_defaults(func=_cmd_refine)

    analyze = sub.add_parser("analyze", help="measure a rendered WAV")
    analyze.add_argument("run_dir")
    analyze.add_argument("audio_path")
    analyze.set_defaults(func=_cmd_analyze)

    finalize = sub.add_parser("finalize", help="write final manifest for a selected render")
    finalize.add_argument("run_dir")
    finalize.add_argument("audio_path")
    finalize.add_argument("--min-duration", type=float, default=60.0)
    finalize.set_defaults(func=_cmd_finalize)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

