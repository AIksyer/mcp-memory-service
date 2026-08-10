# Copyright 2024 Heinrich Krupp
# Modifications Copyright 2026 AIksyer
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
"""Tests for sync_version and device_id fields on Memory dataclass (v4)."""

import pytest

from mcp_memory_service.models.memory import Memory
from mcp_memory_service.utils.hashing import generate_content_hash


class TestMemorySyncVersion:
    """Tests for sync_version field on Memory."""

    def test_default_sync_version_is_1(self):
        """New Memory has sync_version=1 by default."""
        mem = Memory(content="test", content_hash="abc123")
        assert mem.sync_version == 1

    def test_sync_version_can_be_set(self):
        """sync_version can be set explicitly."""
        mem = Memory(content="test", content_hash="abc123", sync_version=5)
        assert mem.sync_version == 5

    def test_to_dict_includes_sync_version_and_device_id(self):
        """to_dict() includes sync_version and device_id."""
        mem = Memory(
            content="test",
            content_hash="abc123",
            sync_version=3,
            device_id="device-001",
        )
        d = mem.to_dict()
        assert d["sync_version"] == 3
        assert d["device_id"] == "device-001"

    def test_from_dict_round_trips_sync_version_and_device_id(self):
        """from_dict() reads sync_version and device_id."""
        mem = Memory(
            content="test",
            content_hash="abc123",
            sync_version=7,
            device_id="device-002",
        )
        d = mem.to_dict()
        mem2 = Memory.from_dict(d)
        assert mem2.sync_version == 7
        assert mem2.device_id == "device-002"

    def test_from_dict_defaults_sync_version_to_1_when_missing(self):
        """from_dict() defaults sync_version=1 when not in dict."""
        d = {"content": "test", "content_hash": "abc123"}
        mem = Memory.from_dict(d)
        assert mem.sync_version == 1
        assert mem.device_id is None
