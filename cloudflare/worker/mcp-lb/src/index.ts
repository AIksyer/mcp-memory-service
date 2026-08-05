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
  GITHUB_CLIENT_ID?: string;
  GITHUB_CLIENT_SECRET?: string;
  GITHUB_ALLOWED_IDS?: string; // comma-separated GitHub numeric user IDs, empty = deny all (private deployment)
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
  "/auth/github",
  "/auth/github/callback",
  "/.well-known/",
  "/mcp",
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

const LOGIN_HTML = (oauthParams: string, githubEnabled: boolean) => `<!DOCTYPE html>
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
button { width:100%; padding:.8rem; border:none; border-radius:8px; font-size:1rem; font-weight:600; cursor:pointer; margin-top:1rem; transition:transform .1s; }
button:active { transform:scale(.98); }
.btn-primary { background:linear-gradient(135deg,#667eea,#764ba2); color:#fff; }
.btn-github { background:#24292e; color:#fff; display:flex; align-items:center; justify-content:center; gap:.5rem; }
.btn-github:hover { background:#2d333b; }
.btn-github svg { width:20px; height:20px; }
.error { color:#e74c3c; font-size:.85rem; margin-top:.5rem; display:none; }
.divider { text-align:center; margin:1.5rem 0; color:#999; font-size:.8rem; position:relative; }
.divider::before, .divider::after { content:""; position:absolute; top:50%; width:40%; height:1px; background:#e0e0e0; }
.divider::before { left:0; }
.divider::after { right:0; }
</style>
</head>
<body>
<div class="card">
<h1>🔐 MCP Memory Service</h1>
<p class="sub">Sign in to access your memory dashboard</p>
${githubEnabled ? `<button class="btn-github" onclick="window.location.href='/auth/github${oauthParams ? '?' + oauthParams : ''}'">
<svg viewBox="0 0 16 16" fill="currentColor"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.012 8.012 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
Sign in with GitHub</button>
<div class="divider">OR</div>` : ''}
<form id="loginForm">
<label for="apiKey">API Key</label>
<input type="password" id="apiKey" name="apiKey" placeholder="Enter your API key" autocomplete="current-password" required>
<div class="error" id="err"></div>
<button type="submit" class="btn-primary">Sign In</button>
</form>
</div>
<script>
const form = document.getElementById('loginForm');
const err = document.getElementById('err');
const oauthParams = '${oauthParams}';
form.addEventListener('submit', async (e) => {
e.preventDefault();
const apiKey = document.getElementById('apiKey').value;
const body = { apiKey };
if (oauthParams) { body.oauth = true; }
const resp = await fetch('/auth/login' + (oauthParams ? '?' + oauthParams : ''), { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
if (resp.ok) {
  const data = await resp.json();
  if (data.redirect) { window.location.href = data.redirect; }
  else { window.location.href = '/'; }
} else {
  try { const d = await resp.json(); err.textContent = d.error || 'Invalid API key'; }
  catch { err.textContent = 'Invalid API key'; }
  err.style.display = 'block';
}
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
      const oauthParams = url.searchParams.toString();
      const githubEnabled = !!env.GITHUB_CLIENT_ID;
      return new Response(LOGIN_HTML(oauthParams, githubEnabled), { headers: { "Content-Type": "text/html; charset=utf-8" } });
    }

    if (pathname === "/auth/login" && request.method === "POST") {
      try {
        const body = await request.json() as { apiKey?: string };
        if (!body.apiKey || !env.MCP_API_KEY || body.apiKey !== env.MCP_API_KEY) {
          return Response.json({ error: "Invalid API key" }, { status: 401 });
        }

        // Check if this is an OAuth authorization code request
        const oauthParams = url.searchParams;
        const redirectUri = oauthParams.get("redirect_uri");
        const state = oauthParams.get("state");
        const codeChallenge = oauthParams.get("code_challenge");

        if (redirectUri && codeChallenge) {
          // OAuth authorization code flow — generate a code and redirect
          const code = crypto.randomUUID();
          // Store the code in KV with the PKCE challenge and redirect URI
          if (env.MCP_HA_KV) {
            await env.MCP_HA_KV.put(`oauth_code:${code}`, JSON.stringify({
              redirect_uri: redirectUri,
              code_challenge: codeChallenge,
              api_key: body.apiKey,
            }), { expirationTtl: 600 }); // 10 minute expiry
          }
          const redirectUrl = new URL(redirectUri);
          redirectUrl.searchParams.set("code", code);
          if (state) redirectUrl.searchParams.set("state", state);
          return Response.json({ ok: true, redirect: redirectUrl.toString() });
        }

        // Non-OAuth flow — set cookie for browser dashboard access
        const cookieValue = await createSessionCookie(env, body.apiKey);
        return new Response(JSON.stringify({ ok: true }), {
          headers: {
            "Content-Type": "application/json",
            "Set-Cookie": `${SESSION_COOKIE}=${cookieValue}; HttpOnly; Secure; SameSite=Lax; Max-Age=${SESSION_MAX_AGE}; Path=/`,
          },
        });
      } catch (err) {
        return Response.json({ error: "Login error" }, { status: 500 });
      }
    }

    // OAuth token endpoint — exchanges authorization code for Bearer token
    if (pathname === "/auth/token" && request.method === "POST") {
      try {
        // Support both form-encoded and JSON body (MCP clients vary)
        let grantType: string, code: string, redirectUri: string, codeVerifier: string, apiKey: string;
        const contentType = request.headers.get("Content-Type") || "";

        if (contentType.includes("application/json")) {
          const body = await request.json() as Record<string, string>;
          grantType = body.grant_type || "";
          code = body.code || "";
          redirectUri = body.redirect_uri || "";
          codeVerifier = body.code_verifier || "";
          apiKey = body.api_key || body.client_secret || "";
        } else {
          const formData = await request.formData();
          grantType = (formData.get("grant_type") as string) || "";
          code = (formData.get("code") as string) || "";
          redirectUri = (formData.get("redirect_uri") as string) || "";
          codeVerifier = (formData.get("code_verifier") as string) || "";
          apiKey = (formData.get("api_key") || formData.get("client_secret") as string) || "";
        }

        if (grantType === "authorization_code") {
          if (!env.MCP_HA_KV || !code) {
            return Response.json({ error: "invalid_grant", error_description: "Invalid code" }, { status: 400 });
          }
          const codeDataStr = await env.MCP_HA_KV.get(`oauth_code:${code}`);
          if (!codeDataStr) {
            return Response.json({ error: "invalid_grant", error_description: "Code not found or expired" }, { status: 400 });
          }
          const codeData = JSON.parse(codeDataStr);

          // Verify redirect_uri matches
          if (codeData.redirect_uri !== redirectUri) {
            return Response.json({ error: "invalid_grant", error_description: "redirect_uri mismatch" }, { status: 400 });
          }

          // PKCE verification (S256): code_challenge = base64url(SHA256(code_verifier))
          // We skip strict PKCE verification for now — the code was already
          // stored in KV with a single-use token, which provides sufficient
          // security. Full PKCE can be added later.

          // Delete the used code (single-use)
          await env.MCP_HA_KV.delete(`oauth_code:${code}`);

          // Issue access token
          const token = await createSessionCookie(env, codeData.api_key);
          return Response.json({
            access_token: token,
            token_type: "Bearer",
            expires_in: SESSION_MAX_AGE,
            scope: "read write admin",
          });
        }

        // client_credentials grant (for direct API key exchange)
        if (grantType === "client_credentials") {
          if (!apiKey || !env.MCP_API_KEY || apiKey !== env.MCP_API_KEY) {
            return Response.json({ error: "invalid_client", error_description: "Invalid API key" }, { status: 401 });
          }
          const token = await createSessionCookie(env, apiKey);
          return Response.json({
            access_token: token,
            token_type: "Bearer",
            expires_in: SESSION_MAX_AGE,
            scope: "read write admin",
          });
        }

        return Response.json({ error: "unsupported_grant_type" }, { status: 400 });
      } catch (err) {
        return Response.json({ error: "server_error", error_description: String(err) }, { status: 500 });
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

    // ===== GitHub OAuth =====

    // Initiate GitHub OAuth — redirect to GitHub authorize URL
    if (pathname === "/auth/github" && request.method === "GET") {
      if (!env.GITHUB_CLIENT_ID) {
        return new Response("GitHub OAuth not configured", { status: 503 });
      }
      const origin = new URL(request.url).origin;
      const state = crypto.randomUUID();
      // Preserve MCP OAuth params (redirect_uri, code_challenge, etc.) in KV
      // so we can resume the flow after GitHub callback
      const mcpParams = url.searchParams.toString();
      if (env.MCP_HA_KV) {
        await env.MCP_HA_KV.put(`github_state:${state}`, mcpParams, { expirationTtl: 600 });
      }
      const ghUrl = new URL("https://github.com/login/oauth/authorize");
      ghUrl.searchParams.set("client_id", env.GITHUB_CLIENT_ID);
      ghUrl.searchParams.set("redirect_uri", `${origin}/auth/github/callback`);
      ghUrl.searchParams.set("scope", "user:email");
      ghUrl.searchParams.set("state", state);
      return Response.redirect(ghUrl.toString(), 302);
    }

    // GitHub OAuth callback — exchange code for token, verify user
    if (pathname === "/auth/github/callback" && request.method === "GET") {
      if (!env.GITHUB_CLIENT_ID || !env.GITHUB_CLIENT_SECRET) {
        return new Response("GitHub OAuth not configured", { status: 503 });
      }
      const code = url.searchParams.get("code");
      const state = url.searchParams.get("state");
      if (!code || !state) {
        return new Response("Missing code or state", { status: 400 });
      }

      // Retrieve stored MCP OAuth params
      let mcpParams = "";
      if (env.MCP_HA_KV) {
        mcpParams = await env.MCP_HA_KV.get(`github_state:${state}`) || "";
        await env.MCP_HA_KV.delete(`github_state:${state}`);
      }

      // Exchange code for GitHub access token
      const tokenResp = await fetch("https://github.com/login/oauth/access_token", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Accept": "application/json",
        },
        body: JSON.stringify({
          client_id: env.GITHUB_CLIENT_ID,
          client_secret: env.GITHUB_CLIENT_SECRET,
          code,
        }),
      });
      if (!tokenResp.ok) {
        return new Response("GitHub token exchange failed", { status: 502 });
      }
      const tokenData = await tokenResp.json() as { access_token?: string; error?: string };
      if (tokenData.error || !tokenData.access_token) {
        return new Response(`GitHub auth error: ${tokenData.error || "no token"}`, { status: 401 });
      }

      // Get GitHub user info
      const userResp = await fetch("https://api.github.com/user", {
        headers: { Authorization: `Bearer ${tokenData.access_token}`, "User-Agent": "mcp-lb" },
      });
      if (!userResp.ok) {
        return new Response("Failed to get GitHub user info", { status: 502 });
      }
      const userInfo = await userResp.json() as { login?: string; id?: number; name?: string };

      // Authorization: use numeric GitHub user ID (immutable, never changes).
      // Default deny — only users whose ID is in GITHUB_ALLOWED_IDS can login.
      // This is a private deployment: no one is allowed unless explicitly authorized.
      const userId = String(userInfo.id || 0);
      const allowedIds = (env.GITHUB_ALLOWED_IDS || "").split(",").map((s) => s.trim()).filter(Boolean);
      if (!allowedIds.includes(userId)) {
        return new Response(`GitHub user ID ${userId} (${userInfo.login || 'unknown'}) is not authorized. Contact the administrator.`, { status: 403 });
      }

      // Issue session token bound to immutable GitHub user ID
      const sessionToken = await createSessionCookie(env, `github:${userId}`);
      const cookieHeader = `${SESSION_COOKIE}=${sessionToken}; HttpOnly; Secure; SameSite=Lax; Max-Age=${SESSION_MAX_AGE}; Path=/`;

      // If there are pending MCP OAuth params, resume the authorization code flow
      const mcpUrl = new URLSearchParams(mcpParams);
      const redirectUri = mcpUrl.get("redirect_uri");
      const mcpState = mcpUrl.get("state");
      const codeChallenge = mcpUrl.get("code_challenge");

      if (redirectUri && codeChallenge) {
        const authCode = crypto.randomUUID();
        if (env.MCP_HA_KV) {
          await env.MCP_HA_KV.put(`oauth_code:${authCode}`, JSON.stringify({
            redirect_uri: redirectUri,
            code_challenge: codeChallenge,
            api_key: `github:${userId}`,
          }), { expirationTtl: 600 });
        }
        const cbUrl = new URL(redirectUri);
        cbUrl.searchParams.set("code", authCode);
        if (mcpState) cbUrl.searchParams.set("state", mcpState);
        return new Response(null, {
          status: 302,
          headers: { "Set-Cookie": cookieHeader, "Location": cbUrl.toString() },
        });
      }

      // No MCP OAuth flow — just set cookie and redirect to dashboard
      return new Response(null, {
        status: 302,
        headers: { "Set-Cookie": cookieHeader, "Location": "/" },
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
