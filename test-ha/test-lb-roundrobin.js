// test-lb-roundrobin.js — 10 requests, check round-robin distribution
// Usage: MCP_LB_URL=https://your-lb.example.com node test-lb-roundrobin.js

const LB = process.env.MCP_LB_URL || 'http://127.0.0.1:8000';

async function main() {
  if (!process.env.MCP_LB_URL) {
    console.error('❌ Set MCP_LB_URL env var, e.g.: MCP_LB_URL=https://your-lb.example.com node test-lb-roundrobin.js');
    process.exit(1);
  }
  console.log(`=== Test 1: Round-Robin Load Balancing (${LB}) ===\n`);
  
  const backendCounts = {};
  
  for (let i = 1; i <= 10; i++) {
    const resp = await fetch(`${LB}/api/health`);
    const backend = resp.headers.get('x-lb-backend') || 'UNKNOWN';
    const body = await resp.json();
    backendCounts[backend] = (backendCounts[backend] || 0) + 1;
    const short = backend.replace('https://', '').slice(0, 40);
    console.log(`  Request ${String(i).padStart(2)} → ${short} [${body.status}]`);
  }

  console.log('\n--- Distribution ---');
  const counts = Object.values(backendCounts);
  const allHit = counts.length >= 2;
  for (const [url, count] of Object.entries(backendCounts)) {
    console.log(`  ${url.replace('https://', '').slice(0, 50)}: ${count} requests`);
  }
  
  console.log(`\n  Result: ${allHit ? '✅ PASS — multiple backends received traffic' : '❌ FAIL — single backend only'}`);
  process.exit(allHit ? 0 : 1);
}

main().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
