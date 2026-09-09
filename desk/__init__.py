"""Desk loop: candle -> signal -> candidate log (paper)."""

from desk.candidate_log import CandidateLog, candidate_from_signal
from desk.loop import run_loop, load_config

__all__ = ["CandidateLog", "candidate_from_signal", "run_loop", "load_config"]
