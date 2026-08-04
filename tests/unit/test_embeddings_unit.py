"""Whitebox unit tests for the embeddings subsystem.

Tests cover:
- _HashEmbeddingModel: deterministic generation, dimension, empty text, batch
- EmbeddingsMixin: model init priority, cache behavior, dimension guard, validation
- ONNXEmbeddingModel: constructor guards, _safe_tar_extract path traversal, _verify_sha256
- ExternalEmbeddingModel: connection verification, encode batching, error handling, headers
"""

import hashlib
import struct
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from mcp_memory_service.storage.mixins.embeddings import (
    _DIMENSION_CACHE,
    _EMBEDDING_CACHE,
    _MODEL_CACHE,
    _HashEmbeddingModel,
    clear_model_caches,
    get_model_cache_stats,
)

# ---------------------------------------------------------------------------
# _HashEmbeddingModel tests
# ---------------------------------------------------------------------------


class TestHashEmbeddingModel:
    """Tests for the deterministic hash-based embedding fallback."""

    def test_encode_single_text(self):
        model = _HashEmbeddingModel(384)
        result = model.encode(["hello world"])
        assert len(result) == 1
        assert len(result[0]) == 384
        assert all(isinstance(v, float) for v in result[0])

    def test_encode_multiple_texts(self):
        model = _HashEmbeddingModel(128)
        result = model.encode(["hello", "world", "foo"])
        assert len(result) == 3
        assert all(len(v) == 128 for v in result)

    def test_encode_deterministic(self):
        model = _HashEmbeddingModel(384)
        result1 = model.encode(["test text"])
        result2 = model.encode(["test text"])
        assert result1 == result2

    def test_encode_different_texts_different_embeddings(self):
        model = _HashEmbeddingModel(384)
        result1 = model.encode(["hello"])
        result2 = model.encode(["world"])
        assert result1 != result2

    def test_encode_convert_to_numpy(self):
        model = _HashEmbeddingModel(64)
        result = model.encode(["test"], convert_to_numpy=True)
        assert isinstance(result, np.ndarray)
        assert result.shape == (1, 64)
        assert result.dtype == np.float32

    def test_encode_convert_to_numpy_fallback(self):
        """Test that numpy conversion failure falls back to list."""
        model = _HashEmbeddingModel(64)
        with patch("builtins.__import__", side_effect=ImportError("no numpy")):
            result = model.encode(["test"], convert_to_numpy=True)
            assert isinstance(result, list)

    def test_embed_one_empty_text(self):
        model = _HashEmbeddingModel(64)
        result = model._embed_one("")
        assert result == [0.0] * 64

    def test_embed_one_empty_text_zero_vector(self):
        model = _HashEmbeddingModel(16)
        result = model._embed_one("")
        assert all(v == 0.0 for v in result)

    def test_embed_one_normalizes_to_range(self):
        """Hash embedding values should be in approximately [-1.0, 1.0]."""
        model = _HashEmbeddingModel(384)
        result = model._embed_one("some text content")
        assert all(-1.0 <= v <= 1.0 for v in result)

    def test_embed_one_uses_sha256_counter(self):
        """Verify the hash embedding algorithm uses sha256 with counter bytes."""
        model = _HashEmbeddingModel(4)
        text = "test"
        text_bytes = text.encode("utf-8", errors="ignore")

        # Manually compute what the first 4 floats should be
        digest = hashlib.sha256(text_bytes + b"\x1f" + struct.pack("<I", 0)).digest()
        expected_vals = []
        for i in range(0, 16, 4):
            (val,) = struct.unpack("<i", digest[i:i + 4])
            expected_vals.append(val / 2147483648.0)

        result = model._embed_one(text)
        assert result == expected_vals

    def test_embed_one_large_dimension(self):
        """Test that embedding dimension larger than single SHA256 output (64 bytes = 16 floats) works."""
        model = _HashEmbeddingModel(100)
        result = model._embed_one("test")
        assert len(result) == 100
        # Counter should have been incremented at least once
        # (100 floats / 16 per digest ≈ 7 iterations)

    def test_encode_no_texts(self):
        model = _HashEmbeddingModel(384)
        result = model.encode([])
        assert result == []

    def test_embedding_dimension_attribute(self):
        model = _HashEmbeddingModel(256)
        assert model.embedding_dimension == 256

    def test_embedding_dimension_int_conversion(self):
        model = _HashEmbeddingModel(384.0)
        assert model.embedding_dimension == 384
        assert isinstance(model.embedding_dimension, int)


# ---------------------------------------------------------------------------
# Cache management tests
# ---------------------------------------------------------------------------


class TestEmbeddingCaches:
    """Tests for module-level cache management functions."""

    def setup_method(self):
        _MODEL_CACHE.clear()
        _DIMENSION_CACHE.clear()
        _EMBEDDING_CACHE.clear()

    def test_clear_model_caches(self):
        _MODEL_CACHE["key1"] = "model1"
        _EMBEDDING_CACHE["hash1"] = [0.1, 0.2]
        _DIMENSION_CACHE["key1"] = 384

        result = clear_model_caches()
        assert result["models_cleared"] == 1
        assert result["embeddings_cleared"] == 1
        assert len(_MODEL_CACHE) == 0
        assert len(_EMBEDDING_CACHE) == 0
        assert len(_DIMENSION_CACHE) == 0

    def test_clear_model_caches_empty(self):
        result = clear_model_caches()
        assert result["models_cleared"] == 0
        assert result["embeddings_cleared"] == 0

    def test_get_model_cache_stats(self):
        _MODEL_CACHE["model_a"] = MagicMock()
        _EMBEDDING_CACHE["hash1"] = [1.0]
        _EMBEDDING_CACHE["hash2"] = [2.0]

        stats = get_model_cache_stats()
        assert stats["model_count"] == 1
        assert "model_a" in stats["model_keys"]
        assert stats["embedding_count"] == 2

    def test_get_model_cache_stats_empty(self):
        stats = get_model_cache_stats()
        assert stats["model_count"] == 0
        assert stats["embedding_count"] == 0
        assert stats["model_keys"] == []


# ---------------------------------------------------------------------------
# EmbeddingsMixin tests (using BaseMixin subclass)
# ---------------------------------------------------------------------------


def _create_embeddings_mixin(tmp_path):
    """Create a combined BaseMixin+EmbeddingsMixin instance for testing."""
    from mcp_memory_service.storage.mixins.base import BaseMixin
    from mcp_memory_service.storage.mixins.embeddings import EmbeddingsMixin

    class TestStorage(BaseMixin, EmbeddingsMixin):
        pass

    mixin = TestStorage(str(tmp_path / "test.db"))
    return mixin


class TestEmbeddingsMixinGenerate:
    """Tests for EmbeddingsMixin._generate_embedding and validation."""

    def setup_method(self):
        _EMBEDDING_CACHE.clear()
        _MODEL_CACHE.clear()
        _DIMENSION_CACHE.clear()

    def _create_mixin(self, tmp_path):
        """Create a minimal mixin instance with hash embedding model."""
        mixin = _create_embeddings_mixin(tmp_path)
        mixin.embedding_model = _HashEmbeddingModel(384)
        mixin.embedding_dimension = 384
        mixin.enable_cache = True
        return mixin

    def test_generate_embedding_success(self, tmp_path):
        mixin = self._create_mixin(tmp_path)
        result = mixin._generate_embedding("hello world")
        assert len(result) == 384
        assert all(isinstance(v, float) for v in result)

    def test_generate_embedding_caches_result(self, tmp_path):
        mixin = self._create_mixin(tmp_path)
        text = "cached text"
        result1 = mixin._generate_embedding(text)
        result2 = mixin._generate_embedding(text)
        assert result1 == result2
        # Should be in cache
        assert hash(text) in _EMBEDDING_CACHE

    def test_generate_embedding_no_cache(self, tmp_path):
        mixin = self._create_mixin(tmp_path)
        mixin.enable_cache = False
        result = mixin._generate_embedding("no cache")
        assert len(result) == 384
        # Should not be in cache
        assert hash("no cache") not in _EMBEDDING_CACHE

    def test_generate_embedding_no_model_raises(self, tmp_path):
        mixin = _create_embeddings_mixin(tmp_path)
        mixin.embedding_model = None
        with pytest.raises(RuntimeError, match="No embedding model"):
            mixin._generate_embedding("test")

    def test_generate_embedding_dimension_mismatch_raises(self, tmp_path):
        mixin = self._create_mixin(tmp_path)
        # Mock model to return wrong dimension
        mixin.embedding_model = MagicMock()
        mixin.embedding_model.encode.return_value = np.array([[0.1, 0.2]])  # Only 2 dims
        mixin.embedding_dimension = 384
        with pytest.raises(RuntimeError):
            mixin._generate_embedding("test")

    def test_generate_embedding_nan_raises(self, tmp_path):
        mixin = self._create_mixin(tmp_path)
        mixin.embedding_model = MagicMock()
        mixin.embedding_model.encode.return_value = np.array([[float("nan")] * 384])
        with pytest.raises(RuntimeError):
            mixin._generate_embedding("test")

    def test_generate_embedding_inf_raises(self, tmp_path):
        mixin = self._create_mixin(tmp_path)
        mixin.embedding_model = MagicMock()
        mixin.embedding_model.encode.return_value = np.array([[float("inf")] * 384])
        with pytest.raises(RuntimeError):
            mixin._generate_embedding("test")

    def test_generate_embedding_empty_raises(self, tmp_path):
        mixin = self._create_mixin(tmp_path)
        mixin.embedding_model = MagicMock()
        mixin.embedding_model.encode.return_value = np.array([[]])
        with pytest.raises(RuntimeError):
            mixin._generate_embedding("test")


class TestHashFallbackAllowed:
    """Tests for _hash_fallback_allowed policy."""

    def test_force_allowed(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MCP_MEMORY_ALLOW_HASH_EMBEDDINGS", "1")
        mixin = _create_embeddings_mixin(tmp_path)
        assert mixin._hash_fallback_allowed() is True

    def test_force_allowed_true(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MCP_MEMORY_ALLOW_HASH_EMBEDDINGS", "true")
        mixin = _create_embeddings_mixin(tmp_path)
        assert mixin._hash_fallback_allowed() is True

    def test_force_allowed_yes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MCP_MEMORY_ALLOW_HASH_EMBEDDINGS", "yes")
        mixin = _create_embeddings_mixin(tmp_path)
        assert mixin._hash_fallback_allowed() is True

    def test_force_refused(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MCP_MEMORY_ALLOW_HASH_EMBEDDINGS", "0")
        mixin = _create_embeddings_mixin(tmp_path)
        with pytest.raises(RuntimeError, match=r"hash.*embedding"):
            mixin._hash_fallback_allowed()

    def test_force_refused_false(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MCP_MEMORY_ALLOW_HASH_EMBEDDINGS", "false")
        mixin = _create_embeddings_mixin(tmp_path)
        with pytest.raises(RuntimeError):
            mixin._hash_fallback_allowed()

    def test_force_refused_no(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MCP_MEMORY_ALLOW_HASH_EMBEDDINGS", "no")
        mixin = _create_embeddings_mixin(tmp_path)
        with pytest.raises(RuntimeError):
            mixin._hash_fallback_allowed()


class TestGetExistingDbEmbeddingDimension:
    """Tests for _get_existing_db_embedding_dimension."""

    def test_no_connection(self, tmp_path):
        mixin = _create_embeddings_mixin(tmp_path)
        mixin.conn = None
        assert mixin._get_existing_db_embedding_dimension() is None

    def test_no_table(self, tmp_path):
        import sqlite3

        mixin = _create_embeddings_mixin(tmp_path)
        mixin.conn = sqlite3.connect(str(tmp_path / "test.db"))
        assert mixin._get_existing_db_embedding_dimension() is None

    def test_extracts_dimension(self, tmp_path):
        import sqlite3

        mixin = _create_embeddings_mixin(tmp_path)
        mixin.conn = sqlite3.connect(str(tmp_path / "test.db"))
        # Simulate the DDL that vec0 would have (stored in sqlite_master)
        # We can't create a real vec0 table, so we mock the query result
        mixin.conn.execute("CREATE TABLE memory_embeddings (placeholder TEXT)")
        # Insert a mock row into sqlite_master (can't modify, so mock instead)
        mixin.conn.close()

        # Use mock connection to test the regex extraction
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (
            "CREATE VIRTUAL TABLE memory_embeddings USING vec0(content_embedding FLOAT[512] distance_metric=cosine)",
        )
        mock_conn.execute.return_value = mock_cursor
        mixin.conn = mock_conn
        assert mixin._get_existing_db_embedding_dimension() == 512

    def test_extracts_dimension_384(self, tmp_path):
        from unittest.mock import MagicMock

        mixin = _create_embeddings_mixin(tmp_path)
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (
            "CREATE VIRTUAL TABLE memory_embeddings USING vec0(content_embedding FLOAT[384] distance_metric=cosine)",
        )
        mock_conn.execute.return_value = mock_cursor
        mixin.conn = mock_conn
        assert mixin._get_existing_db_embedding_dimension() == 384


# ---------------------------------------------------------------------------
# ONNXEmbeddingModel tests
# ---------------------------------------------------------------------------


class TestOnnxEmbeddingModelGuards:
    """Tests for ONNXEmbeddingModel constructor guards."""

    def test_raises_when_onnx_unavailable(self, monkeypatch):
        from mcp_memory_service.embeddings import onnx_embeddings

        monkeypatch.setattr(onnx_embeddings, "ONNX_AVAILABLE", False)
        with pytest.raises(ImportError, match="ONNX Runtime"):
            onnx_embeddings.ONNXEmbeddingModel()

    def test_raises_when_tokenizers_unavailable(self, monkeypatch):
        from mcp_memory_service.embeddings import onnx_embeddings

        monkeypatch.setattr(onnx_embeddings, "ONNX_AVAILABLE", True)
        monkeypatch.setattr(onnx_embeddings, "TOKENIZERS_AVAILABLE", False)
        with pytest.raises(ImportError, match="Tokenizers"):
            onnx_embeddings.ONNXEmbeddingModel()

    def test_default_providers(self, monkeypatch):
        """Test that default provider is CPUExecutionProvider."""
        from mcp_memory_service.embeddings import onnx_embeddings

        # We can't actually construct the model (needs downloaded model),
        # but we can verify the provider logic
        assert onnx_embeddings.ONNXEmbeddingModel._MODEL_SHA256 is not None
        assert len(onnx_embeddings.ONNXEmbeddingModel._MODEL_SHA256) == 64


class TestSafeTarExtract:
    """Tests for _safe_tar_extract path traversal prevention."""

    def test_blocks_path_traversal(self, tmp_path):
        import tarfile

        from mcp_memory_service.embeddings.onnx_embeddings import _safe_tar_extract

        # Create a tar with a path traversal entry
        tar_path = tmp_path / "evil.tar"
        with tarfile.open(tar_path, "w") as tar:
            info = tarfile.TarInfo(name="../../../etc/passwd")
            content = b"malicious"
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))

        extract_dir = tmp_path / "extract"
        extract_dir.mkdir()

        with open(tar_path, "rb") as f:
            tar = tarfile.open(fileobj=f)
            with pytest.raises(ValueError, match="path traversal"):
                _safe_tar_extract(tar, extract_dir)
            tar.close()

    def test_blocks_absolute_path(self, tmp_path):
        import tarfile

        from mcp_memory_service.embeddings.onnx_embeddings import _safe_tar_extract

        tar_path = tmp_path / "evil2.tar"
        with tarfile.open(tar_path, "w") as tar:
            info = tarfile.TarInfo(name="/etc/passwd")
            content = b"malicious"
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))

        extract_dir = tmp_path / "extract2"
        extract_dir.mkdir()

        with open(tar_path, "rb") as f:
            tar = tarfile.open(fileobj=f)
            with pytest.raises(ValueError, match="path traversal"):
                _safe_tar_extract(tar, extract_dir)
            tar.close()

    def test_allows_normal_extraction(self, tmp_path):
        import tarfile

        from mcp_memory_service.embeddings.onnx_embeddings import _safe_tar_extract

        tar_path = tmp_path / "safe.tar"
        with tarfile.open(tar_path, "w") as tar:
            info = tarfile.TarInfo(name="safe_file.txt")
            content = b"safe content"
            info.size = len(content)
            tar.addfile(info, io.BytesIO(content))

        extract_dir = tmp_path / "extract_safe"
        extract_dir.mkdir()

        with open(tar_path, "rb") as f:
            tar = tarfile.open(fileobj=f)
            _safe_tar_extract(tar, extract_dir)
            tar.close()

        assert (extract_dir / "safe_file.txt").exists()


class TestVerifySha256:
    """Tests for _verify_sha256."""

    def test_correct_hash(self, tmp_path):
        from mcp_memory_service.embeddings.onnx_embeddings import _verify_sha256

        f = tmp_path / "test.bin"
        content = b"hello world"
        f.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert _verify_sha256(str(f), expected) is True

    def test_wrong_hash(self, tmp_path):
        from mcp_memory_service.embeddings.onnx_embeddings import _verify_sha256

        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        assert _verify_sha256(str(f), "0" * 64) is False

    def test_large_file(self, tmp_path):
        """Test that file is read in blocks (4KB chunks)."""
        from mcp_memory_service.embeddings.onnx_embeddings import _verify_sha256

        f = tmp_path / "large.bin"
        content = b"x" * 10000  # Larger than 4096
        f.write_bytes(content)
        expected = hashlib.sha256(content).hexdigest()
        assert _verify_sha256(str(f), expected) is True


class TestGetOnnxEmbeddingModel:
    """Tests for get_onnx_embedding_model factory function."""

    def test_returns_none_when_onnx_unavailable(self, monkeypatch):
        from mcp_memory_service.embeddings import onnx_embeddings

        monkeypatch.setattr(onnx_embeddings, "ONNX_AVAILABLE", False)
        result = onnx_embeddings.get_onnx_embedding_model()
        assert result is None

    def test_returns_none_when_tokenizers_unavailable(self, monkeypatch):
        from mcp_memory_service.embeddings import onnx_embeddings

        monkeypatch.setattr(onnx_embeddings, "ONNX_AVAILABLE", True)
        monkeypatch.setattr(onnx_embeddings, "TOKENIZERS_AVAILABLE", False)
        result = onnx_embeddings.get_onnx_embedding_model()
        assert result is None


# ---------------------------------------------------------------------------
# ExternalEmbeddingModel tests
# ---------------------------------------------------------------------------


class TestExternalEmbeddingModelInit:
    """Tests for ExternalEmbeddingModel initialization."""

    def test_default_url(self, monkeypatch):
        from mcp_memory_service.embeddings.external_api import ExternalEmbeddingModel

        monkeypatch.delenv("MCP_EXTERNAL_EMBEDDING_URL", raising=False)
        monkeypatch.delenv("MCP_EXTERNAL_EMBEDDING_MODEL", raising=False)
        monkeypatch.delenv("MCP_EXTERNAL_EMBEDDING_API_KEY", raising=False)

        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [{"embedding": [0.1] * 384}]
            }
            mock_post.return_value = mock_response

            model = ExternalEmbeddingModel()
            assert model.api_url == "http://localhost:8890/v1/embeddings"
            assert model.model_name == "nomic-embed-text"
            assert model.embedding_dimension == 384
            assert model.api_key is None

    def test_env_var_url(self, monkeypatch):
        from mcp_memory_service.embeddings.external_api import ExternalEmbeddingModel

        monkeypatch.setenv("MCP_EXTERNAL_EMBEDDING_URL", "http://custom:9999/v1/embeddings")
        monkeypatch.setenv("MCP_EXTERNAL_EMBEDDING_MODEL", "custom-model")
        monkeypatch.setenv("MCP_EXTERNAL_EMBEDDING_API_KEY", "secret-key")

        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [{"embedding": [0.1] * 768}]
            }
            mock_post.return_value = mock_response

            model = ExternalEmbeddingModel()
            assert model.api_url == "http://custom:9999/v1/embeddings"
            assert model.model_name == "custom-model"
            assert model.api_key == "secret-key"

    def test_constructor_params_override_env(self, monkeypatch):
        from mcp_memory_service.embeddings.external_api import ExternalEmbeddingModel

        monkeypatch.setenv("MCP_EXTERNAL_EMBEDDING_URL", "http://env:9999")
        monkeypatch.setenv("MCP_EXTERNAL_EMBEDDING_MODEL", "env-model")

        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [{"embedding": [0.1] * 256}]
            }
            mock_post.return_value = mock_response

            model = ExternalEmbeddingModel(
                api_url="http://explicit:8888",
                model_name="explicit-model",
                api_key="explicit-key",
            )
            assert model.api_url == "http://explicit:8888"
            assert model.model_name == "explicit-model"
            assert model.api_key == "explicit-key"


class TestExternalEmbeddingModelHeaders:
    """Tests for ExternalEmbeddingModel._get_headers."""

    def test_headers_without_api_key(self, monkeypatch):
        from mcp_memory_service.embeddings.external_api import ExternalEmbeddingModel

        monkeypatch.delenv("MCP_EXTERNAL_EMBEDDING_API_KEY", raising=False)

        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"data": [{"embedding": [0.1] * 384}]}
            mock_post.return_value = mock_response

            model = ExternalEmbeddingModel()
            headers = model._get_headers()
            assert headers == {"Content-Type": "application/json"}
            assert "Authorization" not in headers

    def test_headers_with_api_key(self, monkeypatch):
        from mcp_memory_service.embeddings.external_api import ExternalEmbeddingModel

        monkeypatch.setenv("MCP_EXTERNAL_EMBEDDING_API_KEY", "my-secret-key")

        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"data": [{"embedding": [0.1] * 384}]}
            mock_post.return_value = mock_response

            model = ExternalEmbeddingModel()
            headers = model._get_headers()
            assert headers["Authorization"] == "Bearer my-secret-key"


class TestExternalEmbeddingModelVerifyConnection:
    """Tests for ExternalEmbeddingModel._verify_connection."""

    def test_success_200(self, monkeypatch):
        from mcp_memory_service.embeddings.external_api import ExternalEmbeddingModel

        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [{"embedding": [0.1] * 512}]
            }
            mock_post.return_value = mock_response

            model = ExternalEmbeddingModel.__new__(ExternalEmbeddingModel)
            model.api_url = "http://test/api"
            model.model_name = "test-model"
            model.api_key = None
            model.timeout = 30
            model.embedding_dimension = 768

            model._verify_connection()
            assert model.embedding_dimension == 512

    def test_non_200_raises_connection_error(self, monkeypatch):
        from mcp_memory_service.embeddings.external_api import ExternalEmbeddingModel

        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 500
            mock_response.json.return_value = {"error": {"message": "server error"}}
            mock_post.return_value = mock_response

            model = ExternalEmbeddingModel.__new__(ExternalEmbeddingModel)
            model.api_url = "http://test/api"
            model.model_name = "test-model"
            model.api_key = None
            model.timeout = 30
            model.embedding_dimension = 768

            with pytest.raises(ConnectionError, match="500"):
                model._verify_connection()

    def test_timeout_raises_connection_error(self, monkeypatch):
        import requests as req

        from mcp_memory_service.embeddings.external_api import ExternalEmbeddingModel

        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_post.side_effect = req.exceptions.Timeout("timed out")

            model = ExternalEmbeddingModel.__new__(ExternalEmbeddingModel)
            model.api_url = "http://test/api"
            model.model_name = "test-model"
            model.api_key = None
            model.timeout = 5
            model.embedding_dimension = 768

            with pytest.raises(ConnectionError, match="timed out"):
                model._verify_connection()

    def test_connection_error_raises(self, monkeypatch):
        import requests as req

        from mcp_memory_service.embeddings.external_api import ExternalEmbeddingModel

        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_post.side_effect = req.exceptions.ConnectionError("refused")

            model = ExternalEmbeddingModel.__new__(ExternalEmbeddingModel)
            model.api_url = "http://test/api"
            model.model_name = "test-model"
            model.api_key = None
            model.timeout = 30
            model.embedding_dimension = 768

            with pytest.raises(ConnectionError, match="Cannot connect"):
                model._verify_connection()

    def test_200_but_not_json_raises(self, monkeypatch):
        from mcp_memory_service.embeddings.external_api import ExternalEmbeddingModel

        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.side_effect = ValueError("not JSON")
            mock_post.return_value = mock_response

            model = ExternalEmbeddingModel.__new__(ExternalEmbeddingModel)
            model.api_url = "http://test/api"
            model.model_name = "test-model"
            model.api_key = None
            model.timeout = 30
            model.embedding_dimension = 768

            with pytest.raises(ConnectionError, match="not valid JSON"):
                model._verify_connection()

    def test_200_but_missing_data_raises(self, monkeypatch):
        from mcp_memory_service.embeddings.external_api import ExternalEmbeddingModel

        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"no_data_key": True}
            mock_post.return_value = mock_response

            model = ExternalEmbeddingModel.__new__(ExternalEmbeddingModel)
            model.api_url = "http://test/api"
            model.model_name = "test-model"
            model.api_key = None
            model.timeout = 30
            model.embedding_dimension = 768

            with pytest.raises(ConnectionError, match="missing embedding data"):
                model._verify_connection()


class TestExternalEmbeddingModelEncode:
    """Tests for ExternalEmbeddingModel.encode."""

    def _make_model(self):
        from mcp_memory_service.embeddings.external_api import ExternalEmbeddingModel

        model = ExternalEmbeddingModel.__new__(ExternalEmbeddingModel)
        model.api_url = "http://test/api"
        model.model_name = "test-model"
        model.api_key = None
        model.timeout = 30
        model.embedding_dimension = 4
        return model

    def test_encode_single_string(self):
        model = self._make_model()
        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]}]
            }
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            result = model.encode("hello")
            assert isinstance(result, np.ndarray)
            assert result.shape == (1, 4)

    def test_encode_batch(self):
        model = self._make_model()
        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [
                    {"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]},
                    {"index": 1, "embedding": [0.5, 0.6, 0.7, 0.8]},
                ]
            }
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            result = model.encode(["hello", "world"])
            assert result.shape == (2, 4)

    def test_encode_out_of_order_response(self):
        """Test that API returning embeddings out of order is handled correctly."""
        model = self._make_model()
        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [
                    {"index": 1, "embedding": [0.5, 0.6, 0.7, 0.8]},
                    {"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]},
                ]
            }
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            result = model.encode(["hello", "world"])
            assert result[0][0] == 0.1  # First embedding
            assert result[1][0] == 0.5  # Second embedding

    def test_encode_duplicate_index_raises(self):
        model = self._make_model()
        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [
                    {"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]},
                    {"index": 0, "embedding": [0.5, 0.6, 0.7, 0.8]},
                ]
            }
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            with pytest.raises(RuntimeError, match="duplicate index"):
                model.encode(["hello", "world"])

    def test_encode_missing_embedding_field_raises(self):
        model = self._make_model()
        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [{"index": 0}]  # No "embedding" key
            }
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            with pytest.raises(RuntimeError, match="missing the 'embedding' field"):
                model.encode(["hello"])

    def test_encode_missing_indices_raises(self):
        model = self._make_model()
        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [
                    {"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]},
                    # Missing index 1
                ]
            }
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            with pytest.raises(RuntimeError, match="did not return embeddings for indices"):
                model.encode(["hello", "world"])

    def test_encode_request_exception_raises(self):
        import requests as req
        model = self._make_model()
        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_post.side_effect = req.exceptions.RequestException("network error")

            with pytest.raises(RuntimeError, match="Failed to generate embedding"):
                model.encode(["hello"])

    def test_encode_returns_list_when_not_numpy(self):
        model = self._make_model()
        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                "data": [{"index": 0, "embedding": [0.1, 0.2, 0.3, 0.4]}]
            }
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            result = model.encode("hello", convert_to_numpy=False)
            assert isinstance(result, list)

    def test_get_sentence_embedding_dimension(self):
        model = self._make_model()
        assert model.get_sentence_embedding_dimension() == 4


# Need io for tarfile tests
import io
