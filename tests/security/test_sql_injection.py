# Copyright 2024 Heinrich Krupp
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""SQL injection tests for the REST API and storage layer.

Verifies that SQL meta-characters in user-controlled fields (content,
metadata, tags, search queries, graph parameters) do not corrupt the
database or leak unintended data.
"""

import uuid

import pytest

# Fixtures (temp_db, initialized_storage, authed_client) are provided by
# tests/security/conftest.py

# --- SQL injection payloads ---
SQLI_PAYLOADS = [
    "'; DROP TABLE memories; --",
    "' OR '1'='1",
    "' OR '1'='1' --",
    "' UNION SELECT * FROM memories --",
    "'; INSERT INTO memories VALUES ('evil'); --",
    "admin'--",
    "' OR 1=1 #",
    "'; EXEC xp_cmdshell('dir'); --",
    "1; DROP TABLE memories",
    "' OR ''='",
]


@pytest.mark.integration
class TestSQLInjectionInStore:
    """SQL meta-characters in memory content must not corrupt the database."""

    @pytest.mark.parametrize("payload", SQLI_PAYLOADS)
    def test_store_sqli_content(self, authed_client, payload):
        """Storing SQL injection payloads in content should succeed safely."""
        uid = uuid.uuid4().hex[:8]
        response = authed_client.post(
            "/api/memories",
            json={
                "content": f"Test memory with SQLi payload {uid}: {payload}",
                "tags": ["__test__", "sqli"],
            },
        )
        assert response.status_code in (200, 201), response.text
        # Verify the memory was stored with the payload intact (no execution)
        data = response.json()
        stored_content = data.get("memory", {}).get("content", data.get("content", ""))
        assert payload in stored_content

    @pytest.mark.parametrize("payload", SQLI_PAYLOADS)
    def test_store_sqli_in_tags(self, authed_client, payload):
        """SQL injection payloads in tags must be stored safely."""
        uid = uuid.uuid4().hex[:8]
        response = authed_client.post(
            "/api/memories",
            json={
                "content": f"Tag injection test {uid}",
                "tags": ["__test__", payload],
            },
        )
        assert response.status_code in (200, 201), response.text

    @pytest.mark.parametrize("payload", SQLI_PAYLOADS)
    def test_store_sqli_in_metadata(self, authed_client, payload):
        """SQL injection payloads in metadata values must be stored safely."""
        uid = uuid.uuid4().hex[:8]
        response = authed_client.post(
            "/api/memories",
            json={
                "content": f"Metadata injection test {uid}",
                "tags": ["__test__"],
                "metadata": {"inject_field": payload},
            },
        )
        assert response.status_code in (200, 201), response.text


@pytest.mark.integration
class TestSQLInjectionInSearch:
    """Search endpoints must not be vulnerable to SQL injection."""

    @pytest.mark.parametrize("payload", SQLI_PAYLOADS)
    def test_semantic_search_sqli(self, authed_client, payload):
        """Semantic search with SQL injection payloads must not error."""
        # First store a memory so the database is non-empty
        authed_client.post(
            "/api/memories",
            json={"content": "Benign memory for search test", "tags": ["__test__"]},
        )
        response = authed_client.post(
            "/api/search",
            json={"query": payload, "n_results": 5},
        )
        # Should return results (possibly empty) without error
        assert response.status_code == 200, response.text
        data = response.json()
        assert isinstance(data.get("results", []), list)

    def test_tag_search_sqli(self, authed_client):
        """Tag search with SQL injection in tag values must not error."""
        sqli_tag = "' OR '1'='1"
        authed_client.post(
            "/api/memories",
            json={
                "content": "Memory for tag search injection test",
                "tags": ["__test__", sqli_tag],
            },
        )
        response = authed_client.post(
            "/api/search/by-tag",
            json={"tags": [sqli_tag], "match_all": False},
        )
        assert response.status_code == 200, response.text


@pytest.mark.integration
class TestSQLInjectionInDelete:
    """DELETE /memories/{content_hash} must sanitize hash parameter."""

    @pytest.mark.parametrize("payload", SQLI_PAYLOADS)
    def test_delete_sqli_in_hash(self, authed_client, payload):
        """SQL injection in content_hash path parameter must not corrupt the database."""
        response = authed_client.delete(f"/api/memories/{payload}")
        # Should return 200 with success=False (hash not found) or 404 — never 500
        assert response.status_code in (200, 404), response.text
        if response.status_code == 200:
            data = response.json()
            assert data.get("success") is False

    def test_delete_does_not_drop_table(self, authed_client):
        """A DROP TABLE injection in hash must not actually drop any table."""
        # Store a memory first
        store_resp = authed_client.post(
            "/api/memories",
            json={"content": "Memory before delete injection", "tags": ["__test__"]},
        )
        assert store_resp.status_code in (200, 201)

        # Attempt DROP TABLE via hash parameter
        authed_client.delete("/api/memories/'; DROP TABLE memories; --")

        # Verify table still exists — store another memory
        uid = uuid.uuid4().hex[:8]
        post_inject = authed_client.post(
            "/api/memories",
            json={"content": f"Memory after delete injection {uid}", "tags": ["__test__"]},
        )
        assert post_inject.status_code in (200, 201), post_inject.text

        # Search should still work (table not dropped)
        search = authed_client.post(
            "/api/search",
            json={"query": f"Memory after delete injection {uid}", "n_results": 5},
        )
        assert search.status_code == 200


@pytest.mark.integration
class TestSQLInjectionInGraph:
    """Graph endpoints must sanitize entity_name and relation_type parameters."""

    def test_graph_add_relation_sqli(self, authed_client):
        """Adding a graph relation with SQL injection in entity names must be safe."""
        sqli_entity = "entity'; DROP TABLE memory_graph; --"
        response = authed_client.post(
            "/api/analytics/graph/add-relation",
            json={
                "source_entity": sqli_entity,
                "target_entity": "target_entity",
                "relation_type": "causes",
            },
        )
        # Should either succeed (parameterized) or reject gracefully — never 500
        assert response.status_code in (200, 201, 400, 404, 422), response.text

    def test_graph_search_sqli(self, authed_client):
        """Graph search with SQL injection in entity name must not error."""
        sqli_entity = "' OR '1'='1' --"
        response = authed_client.get(
            "/api/analytics/graph/search",
            params={"entity_name": sqli_entity},
        )
        assert response.status_code in (200, 400, 404, 422), response.text


@pytest.mark.integration
class TestDatabaseIntegrityAfterInjection:
    """After injection attempts, the database must remain intact."""

    def test_database_not_corrupted_after_sqli(self, authed_client):
        """After multiple SQL injection attempts, normal operations still work."""
        # Attempt various injection payloads
        for payload in SQLI_PAYLOADS[:5]:
            authed_client.post(
                "/api/memories",
                json={
                    "content": f"Injection attempt: {payload}",
                    "tags": ["__test__", "integrity"],
                    "metadata": {"payload": payload},
                },
            )

        # Verify the database is still functional
        uid = uuid.uuid4().hex[:8]
        store_resp = authed_client.post(
            "/api/memories",
            json={"content": f"Post-injection memory {uid}", "tags": ["__test__"]},
        )
        assert store_resp.status_code in (200, 201)

        # Verify search still works
        search_resp = authed_client.post(
            "/api/search",
            json={"query": f"Post-injection memory {uid}", "n_results": 5},
        )
        assert search_resp.status_code == 200

        # Verify list still works
        list_resp = authed_client.get("/api/memories", params={"limit": 10})
        assert list_resp.status_code == 200
