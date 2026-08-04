# Copyright 2024 Heinrich Krupp
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Dream-inspired memory consolidation system.

This module implements autonomous memory consolidation inspired by human cognitive
processes during sleep cycles, featuring exponential decay scoring, creative
association discovery, semantic compression, and controlled forgetting.
"""

from .associations import CreativeAssociationEngine
from .base import ConsolidationBase
from .belief import derive_confidence, should_promote, should_supersede
from .belief_service import BeliefService
from .clustering import SemanticClusteringEngine
from .compression import SemanticCompressionEngine
from .consolidator import DreamInspiredConsolidator
from .decay import ExponentialDecayCalculator
from .forgetting import ControlledForgettingEngine
from .health import ConsolidationHealthMonitor, HealthAlert, HealthMetric, HealthStatus
from .scheduler import ConsolidationScheduler

__all__ = [
    "BeliefService",
    "ConsolidationBase",
    "ConsolidationHealthMonitor",
    "ConsolidationScheduler",
    "ControlledForgettingEngine",
    "CreativeAssociationEngine",
    "DreamInspiredConsolidator",
    "ExponentialDecayCalculator",
    "HealthAlert",
    "HealthMetric",
    "HealthStatus",
    "SemanticClusteringEngine",
    "SemanticCompressionEngine",
    "derive_confidence",
    "should_promote",
    "should_supersede",
]
