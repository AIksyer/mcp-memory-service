/**
 * MCP Memory Service — Cloudflare Worker Load Balancer
 *
 * Features:
 * - Round-robin routing with automatic failover
 * - Health check caching (60s healthy / 15s unhealthy retry)
 * - Node pinning via KV (admin API)
 * - Visibility control (hide backend URLs when MCP_HA_HIDDEN=true)
 * - Auth gateway: inject API key, cookie-based browser login, path whitelist
 * - MCP Streamable HTTP transport (stateless mode, no session affinity)
 *
 * Environment variables (set via wrangler secret or [vars]):
 *   BACKENDS              — comma-separated backend URLs (secret)
 *   MCP_API_KEY           — shared API key injected into backend requests (secret)
 *   MCP_ADMIN_TOKEN       — admin token for HA management API (secret)
 *   MCP_COOKIE_SECRET     — signing secret for session cookies (secret)
 *   MCP_HA_HIDDEN         — "true" to hide all backend info (var, default "false")
 *   HEALTH_CHECK_PATH     — default "/api/health"
 *   HEALTHY_STATUS       — default "healthy"
 *
 * KV namespace bindings:
 *   MCP_HA_KV            — stores pin state and session data
 */

// ===== Types =====

export interface BackendState {
  url: string;
  healthy: boolean;
  lastCheck: number;
  failCount: number;
}

interface Env {
  BACKENDS?: string;
  MCP_API_KEY?: string;
  MCP_ADMIN_TOKEN?: string;
  MCP_COOKIE_SECRET?: string;
  MCP_HA_HIDDEN?: string;
  HEALTH_CHECK_PATH?: string;
  HEALTHY_STATUS?: string;
  MCP_HA_KV?: KVNamespace;
}

// ===== Constants =====

const HEALTH_CHECK_INTERVAL_MS = 60_000;
const UNHEALTHY_RETRY_MS = 15_000;
const MAX_FAIL_COUNT = 3;
const REQUEST_TIMEOUT_MS = 30_000;
const SESSION_COOKIE = "mcp_session";
const SESSION_MAX_AGE = 60 * 60 * 24 * 7; // 7 days

// Paths that don't require auth (public endpoints)
const PUBLIC_PATHS = [
  "/api/health",
  "/auth/login",
  "/auth/logout",
  "/.well-known/",
];

// ===== Global State =====

let backends: BackendState[] = [];
let lastIndex = 0;

// ===== Backend Management =====

function initBackends(env: Env): void {
  if (backends.length > 0) return;
  const raw = env.BACKENDS || "";
  if (!raw) {
    console.error("BACKENDS env var not set. Configure via: wrangler secret put BACKENDS");
    return;
  }
  const urls = raw.split(",").map((s) => s.trim()).filter(Boolean);
  backends = urls.map((url) => ({
    url: url.replace(/\/+$/, ""),
    healthy: true,
    lastCheck: 0,
    failCount: 0,
  }));
}

function isHidden(env: Env): boolean {
  return env.MCP_HA_HIDDEN === "true";
}

function maskUrl(url: string, index: number): string {
  return `backend-${index}`;
}

function maskBackends(env: Env): Array<{ id: string; healthy: boolean; failCount: number }> {
  return backends.map((b, i) => ({
    id: isHidden(env) ? maskUrl(b.url, i) : b.url,
    healthy: b.healthy,
    failCount: b.failCount,
  }));
}

async function checkBackendHealth(backend: BackendState, env: Env): Promise<boolean> {
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

async function updateBackendHealth(env: Env): Promise<void> {
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

async function getPin(env: Env): Promise<number | null> {
  if (!env.MCP_HA_KV) return null;
  const pin = await env.MCP_HA_KV.get("pinned_backend");
  return pin !== null ? parseInt(pin, 10) : null;
}

async function setPin(env: Env, index: number): Promise<void> {
  if (!env.MCP_HA_KV) return;
  await env.MCP_HA_KV.put("pinned_backend", String(index));
}

async function clearPin(env: Env): Promise<void> {
  if (!env.MCP_HA_KV) return;
  await env.MCP_HA_KV.delete("pinned_backend");
}

function pickBackend(pinIndex: number | null): BackendState | null {
  const healthy = backends.filter((b) => b.healthy);
  if (healthy.length === 0) return null;

  // If pinned, try that specific backend
  if (pinIndex !== null && pinIndex >= 0 && pinIndex < backends.length && backends[pinIndex].healthy) {
    return backends[pinIndex];
  }

  // Round-robin among healthy backends
  lastIndex = (lastIndex + 1) % healthy.length;
  return healthy[lastIndex];
}

async function proxyRequest(request: Request, backend: BackendState, env: Env, backendIndex: number): Promise<Response> {
  const url = new URL(request.url);
  const targetUrl = `${backend.url}${url.pathname}${url.search}`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const headers = new Headers(request.headers);

    // If the client authenticated with a Worker-issued Bearer token or session cookie,
    // translate to X-API-Key for the backend (which doesn't understand Worker tokens).
    // If the client sent X-API-Key directly, pass it through.
    const authHeader = request.headers.get("Authorization") || "";
    if (authHeader.startsWith("Bearer ") && env.MCP_API_KEY) {
      // Worker-issued Bearer token → inject API key for backend
      headers.set("X-API-Key", env.MCP_API_KEY);
      headers.delete("Authorization");
    }

    const resp = await fetch(targetUrl, {
      method: request.method,
      headers,
      body: request.method !== "GET" && request.method !== "HEAD" ? request.body : undefined,
      signal: controller.signal,
      redirect: "manual",
    });
    clearTimeout(timeout);

    // Mask backend identifier if hidden
    const respHeaders = new Headers(resp.headers);
    respHeaders.set("X-LB-Backend", isHidden(env) ? maskUrl(backend.url, backendIndex) : backend.url);
    return new Response(resp.body, { status: resp.status, statusText: resp.statusText, headers: respHeaders });
  } catch (err) {
    clearTimeout(timeout);
    throw err;
  }
}

// ===== Auth Gateway =====

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(p));
}

async function validateSession(request: Request, env: Env): Promise<boolean> {
  const cookieHeader = request.headers.get("Cookie") || "";
  const cookies = Object.fromEntries(
    cookieHeader.split(";").map((c) => {
      const [k, ...v] = c.trim().split("=");
      return [k, v.join("=")];
    })
  );
  const session = cookies[SESSION_COOKIE];
  if (!session) return false;

  // Session is a signed token: base64(payload).hmac
  // For simplicity, we accept the token if MCP_COOKIE_SECRET is set and the hmac matches
  if (!env.MCP_COOKIE_SECRET) return false;

  const parts = session.split(".");
  if (parts.length !== 2) return false;

  const [payloadB64, hmac] = parts;
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(env.MCP_COOKIE_SECRET),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["verify"]
  );
  const valid = await crypto.subtle.verify("HMAC", key, hexToBytes(hmac), encoder.encode(payloadB64));
  return valid;
}

function bytesToHex(bytes: ArrayBuffer): string {
  return [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function hexToBytes(hex: string): Uint8Array {
  const arr = new Uint8Array(hex.length / 2);
  for (let i = 0; i < hex.length; i += 2) {
    arr[i / 2] = parseInt(hex.slice(i, i + 2), 16);
  }
  return arr;
}

async function createSessionCookie(env: Env, apiKey: string): Promise<string> {
  const payload = JSON.stringify({ key: apiKey, exp: Date.now() + SESSION_MAX_AGE * 1000 });
  const payloadB64 = btoa(payload);
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(env.MCP_COOKIE_SECRET!),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const sig = await crypto.subtle.sign("HMAC", key, encoder.encode(payloadB64));
  return `${payloadB64}.${bytesToHex(sig)}`;
}

function adminAuth(request: Request, env: Env): boolean {
  if (!env.MCP_ADMIN_TOKEN) return false;
  const auth = request.headers.get("Authorization") || "";
  if (auth.startsWith("Bearer ")) {
    return auth.slice(7) === env.MCP_ADMIN_TOKEN;
  }
  return false;
}

// ===== Login Page =====

const LOGIN_HTML = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MCP Memory Service — Login</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif; background:linear-gradient(135deg,#667eea,#764ba2); min-height:100vh; display:flex; align-items:center; justify-content:center; }
.card { background:#fff; border-radius:16px; padding:2.5rem; box-shadow:0 20px 60px rgba(0,0,0,.15); width:100%; max-width:400px; }
h1 { font-size:1.5rem; color:#1a1a2e; margin-bottom:.5rem; }
p.sub { color:#6c7293; margin-bottom:1.5rem; font-size:.9rem; }
label { display:block; font-size:.85rem; color:#1a1a2e; margin-bottom:.4rem; font-weight:600; }
input { width:100%; padding:.75rem; border:2px solid #e0e0e0; border-radius:8px; font-size:1rem; transition:border .2s; }
input:focus { border-color:#667eea; outline:none; }
button { width:100%; padding:.8rem; background:linear-gradient(135deg,#667eea,#764ba2); color:#fff; border:none; border-radius:8px; font-size:1rem; font-weight:600; cursor:pointer; margin-top:1rem; transition:transform .1s; }
button:active { transform:scale(.98); }
.error { color:#e74c3c; font-size:.85rem; margin-top:.5rem; display:none; }
.divider { text-align:center; margin:1.5rem 0; color:#999; font-size:.8rem; position:relative; }
.divider::before, .divider::after { content:""; position:absolute; top:50%; width:40%; height:1px; background:#e0e0e0; }
.divider::before { left:0; }
.divider::after { right:0; }
.passkey-btn { width:100%; padding:.8rem; background:#1a1a2e; color:#fff; border:none; border-radius:8px; font-size:.9rem; cursor:pointer; }
.passkey-btn:hover { background:#2d2d4e; }
</style>
</head>
<body>
<div class="card">
<h1>🔐 MCP Memory Service</h1>
<p class="sub">Sign in to access your memory dashboard</p>
<form id="loginForm">
<label for="apiKey">API Key</label>
<input type="password" id="apiKey" name="apiKey" placeholder="Enter your API key" autocomplete="current-password" required>
<div class="error" id="err"></div>
<button type="submit">Sign In</button>
</form>
<div class="divider">OR</div>
<button class="passkey-btn" id="passkeyBtn">🔑 Sign in with Passkey</button>
</div>
<script>
const form = document.getElementById('loginForm');
const err = document.getElementById('err');
form.addEventListener('submit', async (e) => {
e.preventDefault();
const apiKey = document.getElementById('apiKey').value;
const resp = await fetch('/auth/login', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({apiKey}) });
if (resp.ok) { window.location.href = '/'; }
else { err.textContent = 'Invalid API key'; err.style.display = 'block'; }
});
// Passkey (WebAuthn) — calls backend through the LB
document.getElementById('passkeyBtn').addEventListener('click', async () => {
try {
const beginResp = await fetch('/api/auth/webauthn/auth/begin', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({}) });
if (!beginResp.ok) { err.textContent = 'Passkey authentication not available'; err.style.display='block'; return; }
const beginData = await beginResp.json();
const credential = await navigator.credentials.get({ publicKey: beginData.publicKey });
const finishResp = await fetch('/api/auth/webauthn/auth/finish', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({ credential: { id: credential.id, rawId: credential.id, type: credential.type, response: { authenticatorData: btoa(String.fromCharCode(...new Uint8Array(credential.response.authenticatorData))), clientDataJSON: btoa(String.fromCharCode(...new Uint8Array(credential.response.clientDataJSON))), signature: btoa(String.fromCharCode(...new Uint8Array(credential.response.signature))), userHandle: credential.response.userHandle ? btoa(String.fromCharCode(...new Uint8Array(credential.response.userHandle))) : null } } }) });
if (finishResp.ok) { window.location.href = '/'; }
else { err.textContent = 'Passkey authentication failed'; err.style.display = 'block'; }
} catch(ex) { err.textContent = 'Passkey error: ' + ex.message; err.style.display = 'block'; }
});
</script>
</body>
</html>`;

// ===== Main Handler =====

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    initBackends(env);
    await updateBackendHealth(env);

    const url = new URL(request.url);
    const pathname = url.pathname;

    // ===== Auth Routes =====

    if (pathname === "/auth/login" && request.method === "GET") {
      return new Response(LOGIN_HTML, { headers: { "Content-Type": "text/html; charset=utf-8" } });
    }

    if (pathname === "/auth/login" && request.method === "POST") {
      try {
        const body = await request.json() as { apiKey?: string };
        if (!body.apiKey || !env.MCP_API_KEY || body.apiKey !== env.MCP_API_KEY) {
          return Response.json({ error: "Invalid API key" }, { status: 401 });
        }
        // Issue a Bearer token (same as cookie but returned in body for MCP clients)
        const token = await createSessionCookie(env, body.apiKey);
        const cookieValue = await createSessionCookie(env, body.apiKey);
        return new Response(JSON.stringify({ ok: true, access_token: token, token_type: "Bearer", expires_in: SESSION_MAX_AGE }), {
          headers: {
            "Content-Type": "application/json",
            "Set-Cookie": `${SESSION_COOKIE}=${cookieValue}; HttpOnly; Secure; SameSite=Lax; Max-Age=${SESSION_MAX_AGE}; Path=/`,
          },
        });
      } catch (err) {
        return Response.json({ error: "Login error" }, { status: 500 });
      }
    }

    // OAuth token endpoint — exchanges API key for Bearer token
    if (pathname === "/auth/token" && request.method === "POST") {
      try {
        const body = await request.json() as { grant_type?: string; api_key?: string };
        // Support client_credentials grant with API key as client secret
        const apiKey = body.api_key || "";
        if (!apiKey || !env.MCP_API_KEY || apiKey !== env.MCP_API_KEY) {
          return Response.json({ error: "invalid_client", error_description: "Invalid API key" }, { status: 401 });
        }
        const token = await createSessionCookie(env, apiKey);
        return Response.json({
          access_token: token,
          token_type: "Bearer",
          expires_in: SESSION_MAX_AGE,
          scope: "read write",
        });
      } catch (err) {
        return Response.json({ error: "server_error" }, { status: 500 });
      }
    }

    // OAuth DCR (Dynamic Client Registration) — allows MCP clients to self-register
    if (pathname === "/auth/register" && request.method === "POST") {
      const clientId = crypto.randomUUID();
      return Response.json({
        client_id: clientId,
        client_id_issued_at: Math.floor(Date.now() / 1000),
        client_secret: null,
        token_endpoint_auth_method: "none",
        grant_types: ["client_credentials", "authorization_code"],
        response_types: ["code"],
      });
    }

    if (pathname === "/auth/logout") {
      return new Response(JSON.stringify({ ok: true }), {
        headers: {
          "Content-Type": "application/json",
          "Set-Cookie": `${SESSION_COOKIE}=; HttpOnly; Secure; SameSite=Lax; Max-Age=0; Path=/`,
        },
      });
    }

    // ===== HA Management API (admin) =====

    if (pathname === "/api/ha/nodes" && request.method === "GET") {
      if (!adminAuth(request, env)) {
        return Response.json({ error: "Unauthorized" }, { status: 401 });
      }
      const pin = await getPin(env);
      return Response.json({
        backends: maskBackends(env),
        pinned: pin !== null ? (isHidden(env) ? `backend-${pin}` : backends[pin]?.url) : null,
        hidden: isHidden(env),
      });
    }

    if (pathname === "/api/ha/pin" && request.method === "POST") {
      if (!adminAuth(request, env)) {
        return Response.json({ error: "Unauthorized" }, { status: 401 });
      }
      const body = await request.json() as { index?: number; url?: string };
      let pinIndex = -1;
      if (body.index !== undefined) {
        pinIndex = body.index;
      } else if (body.url) {
        pinIndex = backends.findIndex((b) => b.url === body.url);
      }
      if (pinIndex < 0 || pinIndex >= backends.length) {
        return Response.json({ error: "Invalid backend index or URL" }, { status: 400 });
      }
      await setPin(env, pinIndex);
      return Response.json({ ok: true, pinned: isHidden(env) ? maskUrl(backends[pinIndex].url, pinIndex) : backends[pinIndex].url });
    }

    if (pathname === "/api/ha/pin" && request.method === "DELETE") {
      if (!adminAuth(request, env)) {
        return Response.json({ error: "Unauthorized" }, { status: 401 });
      }
      await clearPin(env);
      return Response.json({ ok: true, message: "Pin removed, round-robin resumed" });
    }

    // ===== LB Health (public, respects hidden mode) =====

    if (pathname === "/lb-health") {
      if (isHidden(env)) {
        // Hidden mode: only show count, not URLs
        const healthy = backends.filter((b) => b.healthy).length;
        return Response.json({ status: "ok", backends: `${healthy}/${backends.length} healthy` });
      }
      return Response.json({
        backends: backends.map((b) => ({
          url: b.url,
          healthy: b.healthy,
          failCount: b.failCount,
        })),
      });
    }

    // ===== OAuth Discovery Endpoints (for MCP /mcp auth) =====
    // These let MCP clients (Codely CLI) discover auth config and authenticate.

    if (pathname === "/.well-known/oauth-protected-resource") {
      return Response.json({
        resource: `${new URL(request.url).origin}/mcp`,
        authorization_servers: [new URL(request.url).origin],
        bearer_methods_supported: ["header"],
        resource_documentation: `${new URL(request.url).origin}/api/docs`,
      });
    }

    if (pathname === "/.well-known/oauth-authorization-server") {
      const origin = new URL(request.url).origin;
      return Response.json({
        issuer: origin,
        authorization_endpoint: `${origin}/auth/login`,
        token_endpoint: `${origin}/auth/token`,
        registration_endpoint: `${origin}/auth/register`,
        response_types_supported: ["code"],
        grant_types_supported: ["authorization_code", "client_credentials"],
        token_endpoint_auth_methods_supported: ["none", "client_secret_basic"],
        code_challenge_methods_supported: ["S256"],
        scopes_supported: ["read", "write", "admin"],
      });
    }

    // ===== Auth Enforcement =====
    // All non-public paths require either a session cookie or
    // an Authorization / X-API-Key header from the client.

    if (!isPublicPath(pathname)) {
      const hasAuthHeader = request.headers.get("Authorization") || request.headers.get("X-API-Key");
      const hasValidSession = await validateSession(request, env);

      if (!hasAuthHeader && !hasValidSession) {
        // For browser requests, redirect to login
        const accept = request.headers.get("Accept") || "";
        if (accept.includes("text/html")) {
          return Response.redirect(new URL("/auth/login", request.url).toString(), 302);
        }
        // For MCP/API requests, return 401 with WWW-Authenticate pointing to OAuth discovery
        return new Response(
          JSON.stringify({ error: "invalid_token", error_description: "Authentication required" }),
          {
            status: 401,
            headers: {
              "Content-Type": "application/json",
              "WWW-Authenticate": `Bearer resource_metadata="${new URL(request.url).origin}/.well-known/oauth-protected-resource"`,
            },
          }
        );
      }
    }

    // ===== Proxy to Backend =====

    const pinIndex = await getPin(env);

    // Try healthy backends in round-robin (or pinned) order, failover on error
    const tried = new Set<number>();
    for (let attempt = 0; attempt < backends.length; attempt++) {
      const backend = pickBackend(pinIndex);
      if (!backend || tried.has(backends.indexOf(backend))) continue;
      tried.add(backends.indexOf(backend));

      try {
        const resp = await proxyRequest(request, backend, env, backends.indexOf(backend));
        if (resp.status >= 500) {
          console.log(`Backend ${backend.url} returned ${resp.status}, failing over`);
          backend.failCount++;
          if (backend.failCount >= MAX_FAIL_COUNT) backend.healthy = false;
          continue;
        }
        return resp;
      } catch (err) {
        console.log(`Backend ${backend.url} failed: ${err}, failing over`);
        backend.failCount++;
        if (backend.failCount >= MAX_FAIL_COUNT) backend.healthy = false;
        continue;
      }
    }

    return Response.json(
      { error: "All backends are unavailable" },
      { status: 503 }
    );
  },
};
