# HA Test Suite

End-to-end tests for the MCP Memory Service high-availability cluster.

## Prerequisites

Set environment variables with your deployment URLs:

```bash
# Required: LB endpoint URL
export MCP_LB_URL="https://your-lb-domain.com"

# Required for consistency/sync tests: individual backend URLs (comma-separated)
export MCP_BACKENDS="https://backend1.example.com,https://backend2.example.com,https://backend3.example.com"

# Optional: local server URL (default: http://127.0.0.1:8000)
export MCP_LOCAL_URL="http://127.0.0.1:8000"
```

## Running Tests

```bash
# Run all tests sequentially
node test-ha/test-lb-roundrobin.js && \
node test-ha/test-data-consistency.js && \
node test-ha/test-failover.js && \
node test-ha/test-mcp-endpoint.js && \
node test-ha/test-hybrid-sync.js
```

## Test Descriptions

| Test | Description |
|------|-------------|
| `test-lb-roundrobin.js` | Sends 10 requests, verifies traffic distribution across backends |
| `test-data-consistency.js` | Writes via LB, reads from each backend individually |
| `test-failover.js` | 15 concurrent requests (100% availability), error passthrough, write+read cycle |
| `test-mcp-endpoint.js` | MCP JSON-RPC protocol: tools/list, memory_store, memory_search |
| `test-hybrid-sync.js` | Cloud write propagation, HA switch logic verification |
