"""Whitebox unit tests for internal utility functions.

Tests cover:
- Config parsing: safe_get_int_env, safe_get_bool_env, safe_get_optional_int_env
- Path handling: validate_and_create_path, get_base_directory
- Hash utilities: generate_content_hash
- Logging: _sanitize_log_value from compat.py
- System detection: SystemInfo, accelerator detection, optimal settings
- Document processing: create_memory_from_chunk tag merging
- Storage shared utilities: _tags_to_string, _string_to_tags, _safe_json_loads
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mcp_memory_service.compat import _sanitize_log_value
from mcp_memory_service.utils.hashing import generate_content_hash

# ---------------------------------------------------------------------------
# _sanitize_log_value tests
# ---------------------------------------------------------------------------


class TestSanitizeLogValue:
    """Tests for log value sanitization (log injection prevention)."""

    def test_plain_string(self):
        assert _sanitize_log_value("hello") == "hello"

    def test_newline_replaced(self):
        assert _sanitize_log_value("line1\nline2") == "line1\\nline2"

    def test_carriage_return_replaced(self):
        assert _sanitize_log_value("line1\rline2") == "line1\\rline2"

    def test_escape_char_replaced(self):
        assert _sanitize_log_value("\x1b[31mred\x1b[0m") == "\\x1b[31mred\\x1b[0m"

    def test_none_value(self):
        assert _sanitize_log_value(None) == "None"

    def test_integer_value(self):
        assert _sanitize_log_value(42) == "42"

    def test_list_value(self):
        result = _sanitize_log_value(["a", "b"])
        assert "a" in result and "b" in result
        assert "\n" not in result

    def test_dict_value(self):
        result = _sanitize_log_value({"key": "value"})
        assert "key" in result
        assert "\n" not in result

    def test_mixed_control_chars(self):
        result = _sanitize_log_value("a\nb\rc\x1bd")
        assert "\\n" in result
        assert "\\r" in result
        assert "\\x1b" in result

    def test_empty_string(self):
        assert _sanitize_log_value("") == ""

    def test_only_newlines(self):
        assert _sanitize_log_value("\n\n\n") == "\\n\\n\\n"


# ---------------------------------------------------------------------------
# generate_content_hash tests
# ---------------------------------------------------------------------------


class TestGenerateContentHash:
    """Tests for content hash generation."""

    def test_deterministic(self):
        assert generate_content_hash("test") == generate_content_hash("test")

    def test_case_insensitive(self):
        assert generate_content_hash("Hello") == generate_content_hash("hello")

    def test_whitespace_stripped(self):
        assert generate_content_hash("  hello  ") == generate_content_hash("hello")

    def test_different_content_different_hash(self):
        assert generate_content_hash("hello") != generate_content_hash("world")

    def test_empty_string(self):
        h = generate_content_hash("")
        assert len(h) == 64

    def test_returns_hex(self):
        h = generate_content_hash("test")
        assert all(c in "0123456789abcdef" for c in h)

    def test_unicode(self):
        h = generate_content_hash("café ☕")
        assert len(h) == 64

    def test_large_content(self):
        h = generate_content_hash("x" * 10000)
        assert len(h) == 64


# ---------------------------------------------------------------------------
# Config parsing tests
# ---------------------------------------------------------------------------


class TestSafeGetIntEnv:
    """Tests for safe_get_int_env config function."""

    def test_valid_integer(self, monkeypatch):
        from mcp_memory_service.config.base import safe_get_int_env

        monkeypatch.setenv("TEST_INT_VAR", "42")
        assert safe_get_int_env("TEST_INT_VAR", default=10) == 42

    def test_default_when_unset(self, monkeypatch):
        from mcp_memory_service.config.base import safe_get_int_env

        monkeypatch.delenv("TEST_INT_VAR_MISSING", raising=False)
        assert safe_get_int_env("TEST_INT_VAR_MISSING", default=10) == 10

    def test_invalid_value_returns_default(self, monkeypatch):
        from mcp_memory_service.config.base import safe_get_int_env

        monkeypatch.setenv("TEST_INT_VAR", "not_a_number")
        assert safe_get_int_env("TEST_INT_VAR", default=10) == 10

    def test_min_value_constraint(self, monkeypatch):
        from mcp_memory_service.config.base import safe_get_int_env

        monkeypatch.setenv("TEST_INT_VAR", "5")
        assert safe_get_int_env("TEST_INT_VAR", default=10, min_value=8) == 10

    def test_max_value_constraint(self, monkeypatch):
        from mcp_memory_service.config.base import safe_get_int_env

        monkeypatch.setenv("TEST_INT_VAR", "100")
        assert safe_get_int_env("TEST_INT_VAR", default=10, max_value=50) == 10

    def test_within_constraints(self, monkeypatch):
        from mcp_memory_service.config.base import safe_get_int_env

        monkeypatch.setenv("TEST_INT_VAR", "25")
        assert safe_get_int_env("TEST_INT_VAR", default=10, min_value=1, max_value=50) == 25


class TestSafeGetBoolEnv:
    """Tests for safe_get_bool_env config function."""

    @pytest.mark.parametrize("value", ["true", "1", "yes", "on", "enabled", "TRUE", "Yes"])
    def test_truthy_values(self, monkeypatch, value):
        from mcp_memory_service.config.base import safe_get_bool_env

        monkeypatch.setenv("TEST_BOOL_VAR", value)
        assert safe_get_bool_env("TEST_BOOL_VAR", default=False) is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "off", "disabled", "FALSE", "No"])
    def test_falsy_values(self, monkeypatch, value):
        from mcp_memory_service.config.base import safe_get_bool_env

        monkeypatch.setenv("TEST_BOOL_VAR", value)
        assert safe_get_bool_env("TEST_BOOL_VAR", default=True) is False

    def test_default_when_unset(self, monkeypatch):
        from mcp_memory_service.config.base import safe_get_bool_env

        monkeypatch.delenv("TEST_BOOL_VAR_MISSING", raising=False)
        assert safe_get_bool_env("TEST_BOOL_VAR_MISSING", default=True) is True

    def test_invalid_value_returns_default(self, monkeypatch):
        from mcp_memory_service.config.base import safe_get_bool_env

        monkeypatch.setenv("TEST_BOOL_VAR", "maybe")
        assert safe_get_bool_env("TEST_BOOL_VAR", default=True) is True


class TestSafeGetOptionalIntEnv:
    """Tests for safe_get_optional_int_env config function."""

    def test_valid_integer(self, monkeypatch):
        from mcp_memory_service.config.base import safe_get_optional_int_env

        monkeypatch.setenv("TEST_OPT_INT", "42")
        assert safe_get_optional_int_env("TEST_OPT_INT", default=None) == 42

    def test_none_values(self, monkeypatch):
        from mcp_memory_service.config.base import safe_get_optional_int_env

        for val in ["none", "null", "unlimited"]:
            monkeypatch.setenv("TEST_OPT_INT", val)
            assert safe_get_optional_int_env("TEST_OPT_INT", default=10) is None

    def test_empty_string_returns_default(self, monkeypatch):
        from mcp_memory_service.config.base import safe_get_optional_int_env

        monkeypatch.setenv("TEST_OPT_INT", "")
        # Empty string is falsy → returns default
        assert safe_get_optional_int_env("TEST_OPT_INT", default=10) == 10

    def test_default_when_unset(self, monkeypatch):
        from mcp_memory_service.config.base import safe_get_optional_int_env

        monkeypatch.delenv("TEST_OPT_INT_MISSING", raising=False)
        assert safe_get_optional_int_env("TEST_OPT_INT_MISSING", default=5) == 5


# ---------------------------------------------------------------------------
# Path validation tests
# ---------------------------------------------------------------------------


class TestValidateAndCreatePath:
    """Tests for validate_and_create_path function."""

    def test_creates_directory(self, tmp_path):
        from mcp_memory_service.config.base import validate_and_create_path

        new_path = tmp_path / "newdir" / "subdir"
        result = validate_and_create_path(str(new_path))
        assert Path(result).exists()
        assert Path(result).is_dir()

    def test_existing_directory(self, tmp_path):
        from mcp_memory_service.config.base import validate_and_create_path

        result = validate_and_create_path(str(tmp_path))
        assert Path(result).exists()

    def test_permission_error_on_invalid_path(self, monkeypatch):
        from mcp_memory_service.config.base import validate_and_create_path

        # Mock os.makedirs to fail to simulate permission error
        with patch("mcp_memory_service.config.base.os.makedirs", side_effect=PermissionError("denied")):
            with pytest.raises((PermissionError, OSError)):
                validate_and_create_path("/some/path/that/will/fail")


class TestGetBaseDirectory:
    """Tests for get_base_directory function."""

    def test_env_var_override(self, monkeypatch, tmp_path):
        from mcp_memory_service.config.base import get_base_directory

        monkeypatch.setenv("MCP_MEMORY_BASE_DIR", str(tmp_path))
        result = get_base_directory()
        assert result == str(tmp_path)


# ---------------------------------------------------------------------------
# System detection tests
# ---------------------------------------------------------------------------


class TestSystemInfo:
    """Tests for SystemInfo class."""

    def test_init_sets_attributes(self):
        from mcp_memory_service.utils.system_detection import SystemInfo

        info = SystemInfo()
        assert hasattr(info, "os_name")
        assert hasattr(info, "os_version")
        assert hasattr(info, "architecture")
        assert hasattr(info, "python_version")
        assert hasattr(info, "cpu_count")
        assert hasattr(info, "memory_gb")
        assert hasattr(info, "accelerator")
        assert hasattr(info, "is_rosetta")
        assert hasattr(info, "is_virtual_env")

    def test_to_dict(self):
        from mcp_memory_service.utils.system_detection import SystemInfo

        info = SystemInfo()
        d = info.to_dict()
        assert "os" in d
        assert "architecture" in d
        assert "python_version" in d
        assert "cpu_count" in d
        assert "memory_gb" in d
        assert "accelerator" in d

    def test_str_returns_json(self):
        import json as json_mod

        from mcp_memory_service.utils.system_detection import SystemInfo

        info = SystemInfo()
        s = str(info)
        parsed = json_mod.loads(s)
        assert "os" in parsed

    def test_detect_architecture(self):
        from mcp_memory_service.utils.system_detection import Architecture, SystemInfo

        info = SystemInfo()
        assert info._detect_architecture() in [
            Architecture.X86_64,
            Architecture.ARM64,
            Architecture.UNKNOWN,
        ]

    def test_get_optimal_batch_size(self):
        from mcp_memory_service.utils.system_detection import SystemInfo

        info = SystemInfo()
        batch_size = info.get_optimal_batch_size()
        assert isinstance(batch_size, int)
        assert batch_size > 0

    def test_get_optimal_model(self):
        from mcp_memory_service.utils.system_detection import SystemInfo

        info = SystemInfo()
        model = info.get_optimal_model()
        assert isinstance(model, str)
        assert len(model) > 0

    def test_get_optimal_thread_count(self):
        from mcp_memory_service.utils.system_detection import SystemInfo

        info = SystemInfo()
        threads = info.get_optimal_thread_count()
        assert isinstance(threads, int)
        assert threads >= 1


class TestSystemDetectionFunctions:
    """Tests for module-level system detection functions."""

    def test_get_system_info_singleton(self):
        from mcp_memory_service.utils.system_detection import (
            get_system_info,
        )

        info1 = get_system_info()
        info2 = get_system_info()
        assert info1 is info2  # Singleton

    def test_get_torch_device(self):
        from mcp_memory_service.utils.system_detection import get_torch_device

        device = get_torch_device()
        assert device in ["cuda", "mps", "cpu"]

    def test_get_optimal_embedding_settings(self):
        from mcp_memory_service.utils.system_detection import (
            get_optimal_embedding_settings,
        )

        settings = get_optimal_embedding_settings()
        assert "model_name" in settings
        assert "batch_size" in settings
        assert "device" in settings
        assert "threads" in settings


class TestAcceleratorDetection:
    """Tests for accelerator detection methods."""

    def test_check_cuda_available_returns_bool(self):
        from mcp_memory_service.utils.system_detection import SystemInfo

        info = SystemInfo()
        result = info._check_cuda_available()
        assert isinstance(result, bool)

    def test_check_mps_available_returns_bool(self):
        from mcp_memory_service.utils.system_detection import SystemInfo

        info = SystemInfo()
        result = info._check_mps_available()
        assert isinstance(result, bool)

    def test_check_directml_available_returns_bool(self):
        from mcp_memory_service.utils.system_detection import SystemInfo

        info = SystemInfo()
        result = info._check_directml_available()
        assert isinstance(result, bool)

    def test_detect_accelerator_valid_value(self):
        from mcp_memory_service.utils.system_detection import (
            AcceleratorType,
            SystemInfo,
        )

        info = SystemInfo()
        assert info.accelerator in [
            AcceleratorType.NONE,
            AcceleratorType.CUDA,
            AcceleratorType.MPS,
            AcceleratorType.CPU,
            AcceleratorType.DIRECTML,
            AcceleratorType.ROCm,
        ]


# ---------------------------------------------------------------------------
# Document processing tests
# ---------------------------------------------------------------------------


class TestDocumentProcessing:
    """Tests for document_processing.py functions."""

    def test_create_memory_from_chunk_basic(self):
        from mcp_memory_service.utils.document_processing import (
            create_memory_from_chunk,
        )
        from mcp_memory_service.utils.hashing import generate_content_hash

        chunk = MagicMock()
        chunk.content = "Test chunk content"
        chunk.metadata = {}

        memory = create_memory_from_chunk(
            chunk=chunk,
            base_tags=["document"],
        )
        assert memory.content == "Test chunk content"
        assert memory.content_hash == generate_content_hash("Test chunk content")
        assert "document" in memory.tags
        assert memory.memory_type == "document"

    def test_create_memory_from_chunk_with_context_tags(self):
        from mcp_memory_service.utils.document_processing import (
            create_memory_from_chunk,
        )

        chunk = MagicMock()
        chunk.content = "Content"
        chunk.metadata = {}

        memory = create_memory_from_chunk(
            chunk=chunk,
            base_tags=["doc"],
            context_tags={"source_dir": "docs", "file_type": "md"},
        )
        tags = memory.tags
        assert "source_dir:docs" in tags
        assert "file_type:md" in tags

    def test_create_memory_from_chunk_with_chunk_metadata_tags_str(self):
        from mcp_memory_service.utils.document_processing import (
            create_memory_from_chunk,
        )

        chunk = MagicMock()
        chunk.content = "Content"
        chunk.metadata = {"tags": "tag1,tag2,tag3"}

        memory = create_memory_from_chunk(
            chunk=chunk,
            base_tags=["doc"],
        )
        assert "tag1" in memory.tags
        assert "tag2" in memory.tags
        assert "tag3" in memory.tags

    def test_create_memory_from_chunk_with_chunk_metadata_tags_list(self):
        from mcp_memory_service.utils.document_processing import (
            create_memory_from_chunk,
        )

        chunk = MagicMock()
        chunk.content = "Content"
        chunk.metadata = {"tags": ["list_tag1", "list_tag2"]}

        memory = create_memory_from_chunk(
            chunk=chunk,
            base_tags=["doc"],
        )
        assert "list_tag1" in memory.tags
        assert "list_tag2" in memory.tags

    def test_create_memory_from_chunk_with_extra_metadata(self):
        from mcp_memory_service.utils.document_processing import (
            create_memory_from_chunk,
        )

        chunk = MagicMock()
        chunk.content = "Content"
        chunk.metadata = {"existing": "value"}

        memory = create_memory_from_chunk(
            chunk=chunk,
            base_tags=["doc"],
            extra_metadata={"extra_key": "extra_value"},
        )
        assert memory.metadata.get("existing") == "value"
        assert memory.metadata.get("extra_key") == "extra_value"

    def test_create_memory_from_chunk_none_metadata(self):
        from mcp_memory_service.utils.document_processing import (
            create_memory_from_chunk,
        )

        chunk = MagicMock()
        chunk.content = "Content"
        chunk.metadata = None

        # Should handle None metadata gracefully
        memory = create_memory_from_chunk(
            chunk=chunk,
            base_tags=["doc"],
        )
        assert memory.content == "Content"

    def test_create_memory_from_chunk_custom_memory_type(self):
        from mcp_memory_service.utils.document_processing import (
            create_memory_from_chunk,
        )

        chunk = MagicMock()
        chunk.content = "Content"
        chunk.metadata = {}

        memory = create_memory_from_chunk(
            chunk=chunk,
            base_tags=["doc"],
            memory_type="decision",
        )
        assert memory.memory_type == "decision"

    def test_create_memory_from_chunk_deduplicates_tags(self):
        from mcp_memory_service.utils.document_processing import (
            create_memory_from_chunk,
        )

        chunk = MagicMock()
        chunk.content = "Content"
        chunk.metadata = {"tags": ["duplicate", "duplicate", "unique"]}

        memory = create_memory_from_chunk(
            chunk=chunk,
            base_tags=["duplicate", "base"],
        )
        # Tags should be deduplicated
        assert memory.tags.count("duplicate") == 1
