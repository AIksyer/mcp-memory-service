"""
MCP (Model Context Protocol) REST convenience endpoints.

The standard MCP Streamable HTTP transport (POST/GET/DELETE /mcp) is
handled by the SDK's `StreamableHTTPSessionManager`, mounted as an ASGI
app in `web/app.py`. This module provides REST-only endpoints for tool
discovery and health checks that are useful for dashboards and monitoring.

The tool surface and dispatch logic come from the same `MemoryServer`
instance the stdio transport uses (`server_impl.MemoryServer.list_tools`
and `.call_tool`).
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from ..oauth.middleware import AuthenticationResult, require_read_access

logger = logging.getLogger(__name__)


# Singleton MemoryServer shared across HTTP requests. Constructed lazily on
# the first request so import-time cost is avoided. Storage init is itself
# lazy inside MemoryServer, deferred to the first tool call that needs it.
#
# NOTE: The standard Streamable HTTP transport creates its own MemoryServer
# instance in the app lifespan (with transport_mode="remote"). This lazy
# singleton is used only by the REST convenience endpoints below.
_memory_server: Any | None = None


def _get_memory_server():
    """Return the process-wide MemoryServer used by REST endpoints.

    The HTTP REST layer already initializes a `MemoryStorage` (and
    optionally a consolidator + scheduler) in its FastAPI lifespan, so
    use those.
    """
    global _memory_server
    if _memory_server is None:
        import mcp_memory_service.server  # noqa: F401

        from ...server_impl import MemoryServer
        from ..dependencies import get_storage

        cons, sched = None, None
        try:
            from ...api.client import get_consolidator, get_scheduler

            cons = get_consolidator()
            sched = get_scheduler()
        except (ImportError, AttributeError):
            pass

        _memory_server = MemoryServer(
            storage=get_storage(),
            consolidator=cons,
            consolidation_scheduler=sched,
        )
    return _memory_server


def _tool_to_dict(tool) -> dict[str, Any]:
    """Convert an `mcp.types.Tool` to the wire shape returned by REST endpoints."""
    return {
        "name": tool.name,
        "description": tool.description,
        "inputSchema": tool.inputSchema,
    }


router = APIRouter(prefix="/api/mcp", tags=["mcp-protocol"])


@router.get("/tools")
async def list_mcp_tools(user: AuthenticationResult = Depends(require_read_access)):
    """List available MCP tools for discovery (REST convenience endpoint).

    The standard MCP `tools/list` is served by the Streamable HTTP transport
    at POST /mcp. This REST endpoint provides the same information for
    dashboards and monitoring tools.
    """
    server = _get_memory_server()
    tools = await server.list_tools()
    local_only = server.local_only_tools()
    return {
        "tools": [_tool_to_dict(t) for t in tools if t.name not in local_only],
        "protocol": "mcp",
        "version": "1.0",
    }


@router.get("/health")
async def mcp_health():
    """MCP-specific health check (REST convenience endpoint)."""
    server = _get_memory_server()
    await server._ensure_storage_initialized()
    stats = await server.storage.get_stats() if server.storage else {}
    tools = await server.list_tools()
    return {
        "status": "healthy",
        "protocol": "mcp",
        "tools_available": len(tools),
        "storage_backend": (
            server.storage.__class__.__name__ if server.storage else "uninitialized"
        ),
        "statistics": stats,
    }
