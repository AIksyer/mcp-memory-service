// test-mcp-endpoint.js — Test MCP protocol through LB
// Usage: MCP_LB_URL=https://your-lb.example.com node test-mcp-endpoint.js

const LB = process.env.MCP_LB_URL || 'http://127.0.0.1:8000';

async function main() {
  if (!process.env.MCP_LB_URL) {
    console.error('❌ Set MCP_LB_URL env var, e.g.: MCP_LB_URL=https://your-lb.example.com node test-mcp-endpoint.js');
    process.exit(1);
  }
  console.log(`=== Test 4: MCP Protocol Endpoint Through LB (${LB}) ===\n`);

  // 4a: List tools via MCP JSON-RPC
  console.log('4a. MCP tools/list via JSON-RPC:');
  const toolsResp = await fetch(`${LB}/mcp`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jsonrpc: '2.0', id: 1, method: 'tools/list', params: {} }),
  });
  const backend = toolsResp.headers.get('x-lb-backend')?.replace('https://', '');
  
  if (toolsResp.ok) {
    const toolsData = await toolsResp.json();
    const tools = toolsData.result?.tools || toolsData.tools || [];
    const toolNames = tools.map(t => t.name);
    console.log(`    Backend: ${backend}`);
    console.log(`    Tools count: ${tools.length}`);
    console.log(`    Sample: ${toolNames.slice(0, 10).join(', ')}${toolNames.length > 10 ? '...' : ''}`);
    
    const hasStore = toolNames.includes('memory_store');
    const hasSearch = toolNames.includes('memory_search');
    const toolsPass = tools.length >= 10 && hasStore && hasSearch;
    console.log(`    → ${toolsPass ? '✅ PASS' : '❌ FAIL'}\n`);
  } else {
    console.log(`    ❌ FAIL — HTTP ${toolsResp.status}\n`);
  }

  // 4b: memory_store via MCP JSON-RPC
  console.log('4b. MCP memory_store via JSON-RPC:');
  const storeResp = await fetch(`${LB}/mcp`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0', id: 2, method: 'tools/call',
      params: { name: 'memory_store', arguments: {
        content: `MCP-PROTOCOL-TEST ${Date.now()} — via MCP JSON-RPC through LB`,
        tags: ['ha-test', 'mcp-protocol-test', '__test__'],
      }},
    }),
  });
  const storeData = await storeResp.json();
  let storeText = storeData.result?.content?.[0]?.text || JSON.stringify(storeData);
  const storePass = storeResp.ok && (storeText.includes('success') || storeText.includes('stored'));
  console.log(`    Backend: ${storeResp.headers.get('x-lb-backend')?.replace('https://', '')}`);
  console.log(`    Response: ${storeText.slice(0, 120)}`);
  console.log(`    → ${storePass ? '✅ PASS' : '❌ FAIL'}\n`);

  // 4c: memory_search via MCP JSON-RPC
  console.log('4c. MCP memory_search via JSON-RPC:');
  await new Promise(r => setTimeout(r, 8000));
  const searchResp = await fetch(`${LB}/mcp`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      jsonrpc: '2.0', id: 3, method: 'tools/call',
      params: { name: 'memory_search', arguments: { query: 'MCP-PROTOCOL-TEST', n_results: 3 }},
    }),
  });
  const searchData = await searchResp.json();
  let searchText = searchData.result?.content?.[0]?.text || JSON.stringify(searchData);
  const found = searchText.includes('MCP-PROTOCOL-TEST');
  console.log(`    Backend: ${searchResp.headers.get('x-lb-backend')?.replace('https://', '')}`);
  console.log(`    Found: ${found}`);
  console.log(`    → ${found ? '✅ PASS' : '❌ FAIL'}\n`);

  const allPass = storePass && found;
  console.log(`=== Overall: ${allPass ? '✅ MCP Protocol through LB works' : '❌ MCP Protocol issues'} ===`);
  process.exit(allPass ? 0 : 1);
}

main().catch(e => { console.error('FATAL:', e.message); process.exit(1); });
