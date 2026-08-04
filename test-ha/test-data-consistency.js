// test-data-consistency.js — Write via LB, read from each backend individually
// Usage: MCP_LB_URL=https://your-lb.example.com MCP_BACKENDS="url1,url2,url3" node test-data-consistency.js

const LB = process.env.MCP_LB_URL || 'http://127.0.0.1:8000';
const BACKENDS = (process.env.MCP_BACKENDS || '').split(',').filter(Boolean).map(url => {
  const u = url.trim();
  return { name: new URL(u).hostname, url: u.replace(/\/+$/, '') };
});

async function main() {
  if (!process.env.MCP_LB_URL || !process.env.MCP_BACKENDS) {
    console.error('❌ Set env vars:');
    console.error('   MCP_LB_URL=https://your-lb.example.com');
    console.error('   MCP_BACKENDS="https://b1.example.com,https://b2.example.com,https://b3.example.com"');
    process.exit(1);
  }
  console.log(`=== Test 2: Cross-Backend Data Consistency (${LB}) ===\n`);

  // Step 1: Write a unique memory via LB
  const testContent = `HA-CONSISTENCY-TEST ${Date.now()} — written via LB, read from each backend`;
  console.log(`1. Writing memory via LB: "${testContent.slice(0, 60)}..."`);
  
  const writeResp = await fetch(`${LB}/api/memories`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      content: testContent,
      tags: ['ha-test', 'consistency-test', '__test__'],
      metadata: { source: 'ha-consistency-verify' },
    }),
  });
  const writeData = await writeResp.json();
  const hash = writeData.content_hash || writeData.memory?.content_hash;
  console.log(`   ✅ Written, hash: ${hash?.slice(0, 16)}...`);
  console.log(`   Routed to: ${writeResp.headers.get('x-lb-backend')?.replace('https://', '')}\n`);

  // Wait for Cloudflare D1/Vectorize propagation
  console.log('2. Waiting 8s for index propagation...\n');
  await new Promise(r => setTimeout(r, 8000));

  // Step 2: Read from each backend individually
  console.log('3. Reading from each backend individually:');
  let allFound = true;
  
  for (const backend of BACKENDS) {
    try {
      const searchResp = await fetch(`${backend.url}/api/search`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: 'HA-CONSISTENCY-TEST', n_results: 3 }),
      });
      const searchData = await searchResp.json();
      const results = searchData.results || searchData.memories || [];
      const match = results.find(r => 
        (r.memory?.content || r.content || '').includes('HA-CONSISTENCY-TEST')
      );
      
      if (match) {
        const content = match.memory?.content || match.content || '';
        const score = match.similarity_score || match.score || 'N/A';
        console.log(`   ✅ ${backend.name.padEnd(20)} → Found (score: ${typeof score === 'number' ? score.toFixed(4) : score})`);
      } else {
        console.log(`   ❌ ${backend.name.padEnd(20)} → NOT FOUND`);
        allFound = false;
      }
    } catch (e) {
      console.log(`   ❌ ${backend.name.padEnd(20)} → ERROR: ${e.message}`);
      allFound = false;
    }
  }

  console.log(`\n   Result: ${allFound ? '✅ PASS — all backends return the same memory' : '❌ FAIL — data missing on some backends'}`);
  process.exit(allFound ? 0 : 1);
}

main().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
