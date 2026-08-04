/**
 * MCP Memory Service — Cloudflare Worker Load Balancer
 *
 * Distributes traffic across 3 cloud deployments with:
 * - Round-robin routing
 * - Health check caching (60s TTL via Cloudflare Cache API)
 * - Automatic failover on 5xx / timeout
 * - Transparent header/body passthrough
 */

export interface BackendState {
  url: string;
  healthy: boolean;
  lastCheck: number;
  failCount: number;
}

const HEALTH_CHECK_INTERVAL_MS = 60_000; // re-check healthy backends every 60s
const UNHEALTHY_RETRY_MS = 15_000; // retry unhealthy backends every 15s
const MAX_FAIL_COUNT = 3;
const REQUEST_TIMEOUT_MS = 30_000;

// Global state persists across requests within a Worker isolate
let backends: BackendState[] = [];
let lastIndex = 0;

function initBackends(env: Record<string, string>): void {
  if (backends.length > 0) return;
  const raw = env.BACKENDS || "";
  if (!raw) {
    console.error("BACKENDS env var not set. Configure via: wrangler secret put BACKENDS");
    return;
  }
  const urls = raw.split(",").map((s) => s.trim()).filter(Boolean);
  backends = urls.map((url) => ({
    url: url.replace(/\/+$/, ""), // strip trailing slash
    healthy: true,
    lastCheck: 0,
    failCount: 0,
  }));
}

async function checkBackendHealth(backend: BackendState, env: Record<string, string>): Promise<boolean> {
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5_000);
    const resp = await fetch(`${backend.url}${env.HEALTH_CHECK_PATH || "/api/health"}`, {
      signal: controller.signal,
      headers: { "User-Agent": "mcp-lb-healthcheck" },
    });
    clearTimeout(timeout);
    if (!resp.ok) return false;
    const body = await resp.json() as Record<string, unknown>;
    return body.status === (env.HEALTHY_STATUS || "healthy");
  } catch {
    return false;
  }
}

async function updateBackendHealth(env: Record<string, string>): Promise<void> {
  const now = Date.now();
  const checks = backends.map(async (backend) => {
    const interval = backend.healthy ? HEALTH_CHECK_INTERVAL_MS : UNHEALTHY_RETRY_MS;
    if (now - backend.lastCheck < interval) return;
    backend.lastCheck = now;
    const wasHealthy = backend.healthy;
    backend.healthy = await checkBackendHealth(backend, env);
    if (backend.healthy) {
      backend.failCount = 0;
    } else {
      backend.failCount++;
      backend.healthy = backend.failCount < MAX_FAIL_COUNT;
    }
    if (wasHealthy !== backend.healthy) {
      console.log(`Backend ${backend.url} health changed: ${backend.healthy ? "healthy" : "unhealthy"}`);
    }
  });
  await Promise.all(checks);
}

function pickBackend(): BackendState | null {
  const healthy = backends.filter((b) => b.healthy);
  if (healthy.length === 0) return null;
  // Round-robin among healthy backends
  lastIndex = (lastIndex + 1) % healthy.length;
  return healthy[lastIndex];
}

async function proxyRequest(request: Request, backend: BackendState): Promise<Response> {
  const url = new URL(request.url);
  const targetUrl = `${backend.url}${url.pathname}${url.search}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  try {
    const resp = await fetch(targetUrl, {
      method: request.method,
      headers: request.headers,
      body: request.method !== "GET" && request.method !== "HEAD" ? request.body : undefined,
      signal: controller.signal,
      redirect: "manual",
    });
    clearTimeout(timeout);
    return resp;
  } catch (err) {
    clearTimeout(timeout);
    throw err;
  }
}

export default {
  async fetch(request: Request, env: Record<string, string>): Promise<Response> {
    initBackends(env);
    await updateBackendHealth(env);

    const url = new URL(request.url);

    // LB health endpoint
    if (url.pathname === "/lb-health") {
      return Response.json({
        backends: backends.map((b) => ({
          url: b.url,
          healthy: b.healthy,
          failCount: b.failCount,
        })),
      });
    }

    // Try healthy backends in round-robin order, failover on error
    const tried = new Set<number>();
    for (let attempt = 0; attempt < backends.length; attempt++) {
      const backend = pickBackend();
      if (!backend || tried.has(backends.indexOf(backend))) continue;
      tried.add(backends.indexOf(backend));

      try {
        const resp = await proxyRequest(request, backend);
        // 5xx = backend error, try next
        if (resp.status >= 500) {
          console.log(`Backend ${backend.url} returned ${resp.status}, failing over`);
          backend.failCount++;
          if (backend.failCount >= MAX_FAIL_COUNT) backend.healthy = false;
          continue;
        }
        // Add backend identifier header for debugging
        const headers = new Headers(resp.headers);
        headers.set("X-LB-Backend", backend.url);
        return new Response(resp.body, { status: resp.status, statusText: resp.statusText, headers });
      } catch (err) {
        console.log(`Backend ${backend.url} failed: ${err}, failing over`);
        backend.failCount++;
        if (backend.failCount >= MAX_FAIL_COUNT) backend.healthy = false;
        continue;
      }
    }

    // All backends failed
    return Response.json(
      { error: "All backends are unavailable", backends: backends.map((b) => ({ url: b.url, healthy: b.healthy })) },
      { status: 503 }
    );
  },
};
