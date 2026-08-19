"""Sparse point-in-time event-alpha challenger, isolated from futures V8."""

from market_lab.event_alpha_v1.core import (
    EVENT_ALPHA_VERSION,
    attach_causal_targets,
    build_cbr_events,
    build_cftc_events,
    evaluate_expanding_folds,
    expanding_prior_z,
    validate_text_fact_payload,
)

__all__ = [
    "EVENT_ALPHA_VERSION",
    "attach_causal_targets",
    "build_cbr_events",
    "build_cftc_events",
    "evaluate_expanding_folds",
    "expanding_prior_z",
    "validate_text_fact_payload",
]
