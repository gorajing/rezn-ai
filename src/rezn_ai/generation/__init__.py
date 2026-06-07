"""Music generation: candidate strategies and engine protocol."""

from .engine import CandidateResult, GeneratorEngine
from .rezn_engine import ReznGeneratorEngine

__all__ = ["CandidateResult", "GeneratorEngine", "ReznGeneratorEngine"]
