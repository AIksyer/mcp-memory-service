"""Reasoning module — entity extraction, linking, inference, NLI, temporal edges, mutability, multi-strategy search, and ranked search."""

from .entities import Entity, EntityExtractor
from .entity_linker import EntityLinker
from .multi_strategy import multi_strategy_search, rrf_fuse
from .mutability import classify_mutability, contradiction_action
from .nli import NLIClassifier, NLIResult, detect_contradictions_nli
from .ranked_search import (
    RankedSearchWeights,
    apply_ranked_rerank,
    compute_ranked_score,
)
from .temporal import (
    TemporalEdge,
    classify_temporal_relationship,
    filter_temporal_edges,
    store_temporal_association,
)

__all__ = [
    "Entity",
    "EntityExtractor",
    "EntityLinker",
    "NLIClassifier",
    "NLIResult",
    "RankedSearchWeights",
    "TemporalEdge",
    "apply_ranked_rerank",
    "classify_mutability",
    "classify_temporal_relationship",
    "compute_ranked_score",
    "contradiction_action",
    "detect_contradictions_nli",
    "filter_temporal_edges",
    "multi_strategy_search",
    "rrf_fuse",
    "store_temporal_association",
]
