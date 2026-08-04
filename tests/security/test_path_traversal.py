# Copyright 2024 Heinrich Krupp
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Path traversal tests for the HTTP API.

Verifies that endpoints which accept filesystem paths (harvest,
document ingestion) properly reject traversal attempts and that
``local_only_tools()`` filters dangerous tools from remote transport.
"""

import pytest

# Fixtures (temp_db, initialized_storage, authed_client) are provided by
# tests/security/conftest.py

# --- Path traversal payloads ---
TRAVERSAL_PAYLOADS = [
    "../../../etc/passwd",
    "..\\..\\..\\windows\\win.ini",
    "../../etc/shadow",
    "..%2F..%2F..%2Fetc%2Fpasswd",
    "....//....//....//etc/passwd",
    "/etc/passwd",
    "/absolute/path/to/file",
    "C:\\Windows\\System32\\config\\SAM",
    "..%252f..%252f..%252fetc%252fpasswd",
    "..%c0%af..%c0%af..%c0%afetc%c0%afpasswd",
]


@pytest.mark.integration
class TestHarvestPathTraversal:
    """The harvest endpoint must reject path traversal in project_path."""

    @pytest.fixture(autouse=True)
    def _setup_home(self, tmp_path, monkeypatch):
        """Redirect HOME/USERPROFILE to tmp_path so harvest resolves safely."""
        projects = tmp_path / ".claude" / "projects"
        projects.mkdir(parents=True)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setenv("USERPROFILE", str(tmp_path))

    @pytest.mark.parametrize("bad_path", TRAVERSAL_PAYLOADS)
    def test_harvest_rejects_traversal(self, authed_client, bad_path):
        """All path traversal attempts must not succeed (400 or 404, never 200)."""
        response = authed_client.post(
            "/api/harvest",
            json={"dry_run": True, "project_path": bad_path},
        )
        # 400 = validation rejected the path; 404 = path resolved but doesn't exist.
        # Both are safe — the important invariant is no 200 (successful file access).
        assert response.status_code in (400, 404), (
            f"Path traversal payload '{bad_path}' was not safely rejected: "
            f"got {response.status_code}"
        )

    def test_harvest_rejects_absolute_path(self, authed_client):
        """Absolute paths must be rejected."""
        response = authed_client.post(
            "/api/harvest",
            json={"dry_run": True, "project_path": "/etc/passwd"},
        )
        assert response.status_code == 400

    def test_harvest_rejects_symlink_escape(self, authed_client, tmp_path):
        """Symlinks that escape the allowed tree must be rejected."""
        import platform
        if platform.system() == "Windows":
            pytest.skip("Symlink test not reliable on Windows without admin")

        projects = tmp_path / ".claude" / "projects"
        evil = projects / "evil-link"
        try:
            evil.symlink_to("/etc", target_is_directory=True)
        except (OSError, PermissionError):
            pytest.skip("Cannot create symlinks on this system")

        response = authed_client.post(
            "/api/harvest",
            json={"dry_run": True, "project_path": "evil-link"},
        )
        # Even if the symlink exists, the resolved path must stay within the tree
        assert response.status_code in (400, 404)


@pytest.mark.integration
class TestDocumentIngestionPathSafety:
    """Document ingestion endpoints must not allow arbitrary file reads."""

    def test_document_ingest_rejects_traversal(self, authed_client):
        """Document ingestion via API must not accept traversal paths."""
        response = authed_client.post(
            "/api/documents/ingest",
            json={"file_path": "../../../etc/passwd"},
        )
        # Should be rejected — either by validation or by not finding the file
        assert response.status_code in (400, 404, 422), response.text

    def test_document_ingest_rejects_absolute_path(self, authed_client):
        """Document ingestion must reject absolute paths from remote clients."""
        response = authed_client.post(
            "/api/documents/ingest",
            json={"file_path": "/etc/passwd"},
        )
        assert response.status_code in (400, 404, 422), response.text


class TestLocalOnlyToolsFiltering:
    """local_only_tools() must filter filesystem-reading tools from HTTP transport."""

    def test_local_only_tools_contains_harvest_and_ingest(self):
        """The confused-deputy guard must list memory_harvest and memory_ingest."""
        from mcp_memory_service.server_impl import MemoryServer

        server = MemoryServer.__new__(MemoryServer)
        local_only = server.local_only_tools()
        assert "memory_harvest" in local_only
        assert "memory_ingest" in local_only

    def test_local_only_tools_is_frozenset(self):
        """local_only_tools() returns an immutable frozenset."""
        from mcp_memory_service.server_impl import MemoryServer

        server = MemoryServer.__new__(MemoryServer)
        local_only = server.local_only_tools()
        assert isinstance(local_only, frozenset)

    def test_mcp_http_shim_excludes_local_only_tools(self, authed_client):
        """The /mcp tools/list endpoint must not include local-only tools."""
        response = authed_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert response.status_code == 200
        data = response.json()
        tool_names = []
        if "result" in data and "tools" in data["result"]:
            tool_names = [t["name"] for t in data["result"]["tools"]]
        # memory_harvest and memory_ingest must NOT be in the HTTP tool list
        assert "memory_harvest" not in tool_names, (
            "memory_harvest should be filtered from HTTP transport"
        )
        assert "memory_ingest" not in tool_names, (
            "memory_ingest should be filtered from HTTP transport"
        )
