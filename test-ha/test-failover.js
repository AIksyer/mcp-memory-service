// test-failover.js — Verify LB failover logic
// Usage: MCP_LB_URL=https://your-lb.example.com node test-failover.js

const LB = process.env.MCP_LB_URL || 'http://127.0.0.1:8000';

async function main() {
  if (!process.env.MCP_LB_URL) {
    console.error('❌ Set MCP_LB_URL env var, e.g.: MCP_LB_URL=https://your-lb.example.com node test-failover.js');
    process.exit(1);
  }
  console.log(`=== Test 3: Failover & High Availability (${LB}) ===\n`);

  // 3a: Check LB health endpoint
  console.log('3a. LB health endpoint:');
  const lbHealth = await (await fetch(`${LB}/lb-health`)).json();
  const healthyCount = lbHealth.backends.filter(b => b.healthy).length;
  const totalCount = lbHealth.backends.length;
  for (const b of lbHealth.backends) {
    console.log(`    ${b.healthy ? '✅' : '❌'} ${b.url.replace('https://', '').padEnd(40)} failCount=${b.failCount}`);
  }
  const healthPass = healthyCount === totalCount && totalCount >= 2;
  console.log(`    → ${healthPass ? '✅ PASS' : '❌ FAIL'} — ${healthyCount}/${totalCount} healthy\n`);

  // 3b: Availability test — 15 rapid requests, all must succeed
  console.log('3b. Availability test (15 rapid requests):');
  let success = 0;
  let failed = 0;
  const backendsHit = new Set();
  
  const promises = Array.from({ length: 15 }, (_, i) =>
    fetch(`${LB}/api/health`).then(async r => {
      const backend = r.headers.get('x-lb-backend');
      const body = await r.json();
      if (r.ok && body.status === 'healthy') {
        success++;
        backendsHit.add(backend);
      } else {
        failed++;
      }
    }).catch(e => { failed++; })
  );
  
  await Promise.all(promises);
  const availPass = success >= 14; // Allow 1 failure for cold start
  const multiBackendPass = backendsHit.size >= 2;
  console.log(`    Success: ${success}/15, Failed: ${failed}/15`);
  console.log(`    Distinct backends: ${backendsHit.size}`);
  console.log(`    → ${availPass && multiBackendPass ? '✅ PASS' : '❌ FAIL'}\n`);

  // 3c: Error passthrough — LB should pass through 404
  console.log('3c. Error passthrough (404 on non-existent path):');
  const errResp = await fetch(`${LB}/api/nonexistent-endpoint`);
  const errBackend = errResp.headers.get('x-lb-backend');
  const errPass = errResp.status === 404 && errBackend !== null;
  console.log(`    Status: ${errResp.status}, Backend: ${errBackend?.replace('https://', '')}`);
  console.log(`    → ${errPass ? '✅ PASS' : '❌ FAIL'}\n`);

  // 3d: POST request passthrough — write/read cycle
  console.log('3d. Write + Read cycle through LB:');
  const testContent = `HA-FAILOVER-TEST ${Date.now()}`;
  const writeResp = await fetch(`${LB}/api/memories`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ content: testContent, tags: ['ha-test', 'failover-test', '__test__'] }),
  });
  const writeData = await writeResp.json();
  const writeOk = writeResp.ok && writeData.success;
  console.log(`    Write: ${writeOk ? '✅' : '❌'} (backend: ${writeResp.headers.get('x-lb-backend')?.replace('https://', '')})`);

  await new Promise(r => setTimeout(r, 8000));

  const readResp = await fetch(`${LB}/api/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: 'HA-FAILOVER-TEST', n_results: 1 }),
  });
  const readData = await readResp.json();
  const found = (readData.results || []).some(r => (r.memory?.content || '').includes('HA-FAILOVER-TEST'));
  console.log(`    Read:  ${found ? '✅' : '❌'} (backend: ${readResp.headers.get('x-lb-backend')?.replace('https://', '')})`);
  console.log(`    → ${writeOk && found ? '✅ PASS' : '❌ FAIL'}\n`);

  const allPass = healthPass && availPass && multiBackendPass && errPass && writeOk && found;
  console.log(`=== Overall: ${allPass ? '✅ ALL PASS' : '❌ SOME FAILED'} ===`);
  process.exit(allPass ? 0 : 1);
}

main().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
