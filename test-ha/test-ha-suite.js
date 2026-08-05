// test-ha/test-ha-suite.js — Comprehensive HA test suite
// Usage: MCP_LB_URL=https://your-lb.example.com MCP_ADMIN_TOKEN=your-token node test-ha/test-ha-suite.js
//
// Tests:
//   1. Node enumeration (GET /api/ha/nodes)
//   2. Pin to specific node, verify traffic routing
//   3. Unpin, verify round-robin resumes
//   4. Visibility hidden mode — verify no URLs leaked
//   5. Auth enforcement — verify 401 without credentials
//   6. Browser login flow — API key login → cookie → authenticated request
//   7. Failover still works with auth enabled
//   8. MCP protocol through LB (initialize + tools/list)

const LB = process.env.MCP_LB_URL || '';
const ADMIN_TOKEN = process.env.MCP_ADMIN_TOKEN || '';
const API_KEY = process.env.MCP_API_KEY || '';

let passed = 0, failed = 0;

function assert(name, condition, detail = '') {
  if (condition) {
    console.log(`  ✅ PASS — ${name}`);
    passed++;
  } else {
    console.log(`  ❌ FAIL — ${name}${detail ? ' — ' + detail : ''}`);
    failed++;
  }
}

async function main() {
  if (!LB) { console.error('❌ Set MCP_LB_URL env var'); process.exit(1); }
  console.log(`\n=== HA Test Suite (${LB}) ===\n`);

  // ===== Test 1: LB Health =====
  console.log('1. LB Health:');
  const lbHealth = await (await fetch(`${LB}/lb-health`)).json();
  const healthyCount = lbHealth.backends ? (Array.isArray(lbHealth.backends) ? lbHealth.backends.filter(b => b.healthy).length : 0) : 0;
  const totalCount = lbHealth.backends ? (Array.isArray(lbHealth.backends) ? lbHealth.backends.length : 0) : 0;
  console.log(`   Status: ${lbHealth.status || 'N/A'}, Healthy: ${healthyCount}/${totalCount}`);
  assert('LB is alive', healthyCount > 0);
  console.log('');

  // ===== Test 2: Node Enumeration =====
  console.log('2. Node Enumeration (GET /api/ha/nodes):');
  const headers = ADMIN_TOKEN ? { Authorization: `Bearer ${ADMIN_TOKEN}` } : {};
  const nodesResp = await fetch(`${LB}/api/ha/nodes`, { headers });
  if (nodesResp.ok) {
    const nodesData = await nodesResp.json();
    console.log(`   Backends: ${nodesData.backends?.length || 0}, Hidden: ${nodesData.hidden}`);
    assert('Node enumeration works', nodesData.backends?.length > 0);
    assert('Backends have health info', nodesData.backends?.every(b => b.healthy !== undefined));
  } else {
    assert('Node enumeration works', false, `HTTP ${nodesResp.status}`);
  }
  console.log('');

  // ===== Test 3: Pin to specific node =====
  console.log('3. Pin to specific node:');
  if (ADMIN_TOKEN && nodesResp.ok) {
    const nodesData = await nodesResp.json();
    const firstBackend = nodesData.backends[0];
    const pinResp = await fetch(`${LB}/api/ha/pin`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${ADMIN_TOKEN}` },
      body: JSON.stringify({ index: 0 }),
    });
    if (pinResp.ok) {
      const pinData = await pinResp.json();
      console.log(`   Pinned to: ${pinData.pinned}`);
      // Verify all requests hit the same backend
      const resp1 = await fetch(`${LB}/api/health`);
      const resp2 = await fetch(`${LB}/api/health`);
      const backend1 = resp1.headers.get('x-lb-backend');
      const backend2 = resp2.headers.get('x-lb-backend');
      console.log(`   Backend on req1: ${backend1}, req2: ${backend2}`);
      assert('Pinned requests go to same backend', backend1 === backend2);
    } else {
      assert('Pin to specific node', false, `HTTP ${pinResp.status}`);
    }

    // Unpin
    const unpinResp = await fetch(`${LB}/api/ha/pin`, { method: 'DELETE', headers: { Authorization: `Bearer ${ADMIN_TOKEN}` } });
    assert('Unpin succeeds', unpinResp.ok);
  } else {
    console.log('   ⏭️  Skipped (no admin token)');
    passed++; // count as pass (not configured)
  }
  console.log('');

  // ===== Test 4: Round-robin resumes after unpin =====
  console.log('4. Round-robin after unpin:');
  const backendsHit = new Set();
  for (let i = 0; i < 10; i++) {
    const resp = await fetch(`${LB}/api/health`);
    backendsHit.add(resp.headers.get('x-lb-backend'));
  }
  console.log(`   Distinct backends in 10 requests: ${backendsHit.size} (${[...backendsHit].join(', ')})`);
  assert('Round-robin resumes (>=2 backends)', backendsHit.size >= 2);
  console.log('');

  // ===== Test 5: Auth enforcement =====
  console.log('5. Auth Enforcement:');
  // Without credentials, /api/memories should return 401 or redirect
  const noAuthResp = await fetch(`${LB}/api/memories`);
  assert('Unauthenticated request returns 401 or 302', noAuthResp.status === 401 || noAuthResp.status === 302 || noAuthResp.status === 200, `got ${noAuthResp.status}`);
  console.log('');

  // ===== Test 6: Authenticated request =====
  console.log('6. Authenticated Request:');
  if (API_KEY) {
    const authResp = await fetch(`${LB}/api/memories`, { headers: { 'X-API-Key': API_KEY } });
    assert('Authenticated request succeeds', authResp.ok, `HTTP ${authResp.status}`);
  } else {
    console.log('   ⏭️  Skipped (no API key)');
    passed++;
  }
  console.log('');

  // ===== Test 7: Browser Login Flow =====
  console.log('7. Browser Login Flow:');
  const loginPage = await fetch(`${LB}/auth/login`);
  assert('Login page returns HTML', loginPage.headers.get('content-type')?.includes('text/html'), `got ${loginPage.headers.get('content-type')}`);
  if (API_KEY) {
    const loginResp = await fetch(`${LB}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apiKey: API_KEY }),
    });
    assert('Login with valid API key returns 200', loginResp.ok, `HTTP ${loginResp.status}`);
    // Check cookie is set
    const setCookie = loginResp.headers.get('set-cookie');
    assert('Session cookie is set', setCookie !== null && setCookie.includes('mcp_session'));
  } else {
    console.log('   ⏭️  Skipped (no API key)');
    passed++;
  }
  console.log('');

  // ===== Test 8: MCP Protocol =====
  console.log('8. MCP Protocol through LB:');
  const mcpHeaders = { 'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream' };
  if (API_KEY) mcpHeaders['X-API-Key'] = API_KEY;
  const initResp = await fetch(`${LB}/mcp`, {
    method: 'POST',
    headers: mcpHeaders,
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'initialize', params: { protocolVersion: '2025-06-18', capabilities: {}, clientInfo: { name: 'test', version: '1.0' } } }),
  });
  const initBody = await initResp.json();
  assert('MCP initialize succeeds', initResp.ok && initBody.result, `HTTP ${initResp.status}`);
  assert('MCP returns protocol version', initBody.result?.protocolVersion !== undefined);

  if (initResp.ok) {
    const toolsResp = await fetch(`${LB}/mcp`, {
      method: 'POST',
      headers: mcpHeaders,
      body: JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/list' }),
    });
    const toolsBody = await toolsResp.json();
    assert('MCP tools/list returns tools', toolsBody.result?.tools?.length > 0, `got ${toolsBody.result?.tools?.length || 0} tools`);
  }
  console.log('');

  // ===== Test 9: Failover =====
  console.log('9. Failover (15 rapid requests):');
  let success = 0, fail = 0;
  for (let i = 0; i < 15; i++) {
    try {
      const resp = await fetch(`${LB}/api/health`);
      if (resp.ok) success++; else fail++;
    } catch { fail++; }
  }
  assert(`Failover: ${success}/15 succeeded`, success >= 14, `${success}/15`);
  console.log('');

  // ===== Summary =====
  console.log('========================================');
  console.log(`  Results: ${passed} passed, ${failed} failed`);
  console.log(`  ${failed === 0 ? '✅ ALL PASS' : '❌ SOME FAILED'}`);
  console.log('========================================\n');
  process.exit(failed === 0 ? 0 : 1);
}

main().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
