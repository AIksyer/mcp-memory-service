<#
.SYNOPSIS
  MCP Memory Service — 高可用切换脚本
.DESCRIPTION
  检测本地 MCP Memory Service 是否在线：
  - 在线 → 启用 local (hybrid)，禁用 cloud
  - 离线 → 禁用 local，启用 cloud (LB endpoint)
  下次本地恢复后，重新运行此脚本即可切回本地并自动同步。
#>

param(
    [string]$SettingsPath = "$env:USERPROFILE\.codely-cli\settings.json",
    [string]$LocalUrl = "http://127.0.0.1:8000",
    [string]$CloudUrl = $env:MCP_LB_URL  # Set MCP_LB_URL env var, e.g. https://your-lb-domain.com
)

if (-not $CloudUrl) {
    Write-Host "❌ MCP_LB_URL environment variable not set." -ForegroundColor Red
    Write-Host "   Example: `$env:MCP_LB_URL = 'https://your-lb-domain.com'" -ForegroundColor Gray
    Write-Host "   Or pass -CloudUrl parameter." -ForegroundColor Gray
    exit 1
}

function Test-Endpoint($url) {
    try {
        $resp = Invoke-RestMethod -Uri "$url/api/health" -Method Get -TimeoutSec 3
        return $resp.status -eq "healthy"
    } catch {
        return $false
    }
}

$localAlive = Test-Endpoint $LocalUrl

# Read settings
$settings = Get-Content $SettingsPath -Raw | ConvertTo-Json -Depth 10 -AsHashtable

if ($localAlive) {
    Write-Host "✅ 本地 MCP Memory Service 在线 → 启用 local (hybrid), 禁用 cloud" -ForegroundColor Green
    $settings.mcpServers.memory.enabled = $true
    if ($settings.mcpServers.ContainsKey("memory-cloud")) {
        $settings.mcpServers."memory-cloud".enabled = $false
    }
} else {
    Write-Host "⚠️  本地 MCP Memory Service 离线 → 禁用 local, 启用 cloud ($CloudUrl)" -ForegroundColor Yellow
    $settings.mcpServers.memory.enabled = $false
    if ($settings.mcpServers.ContainsKey("memory-cloud")) {
        $settings.mcpServers."memory-cloud".enabled = $true
    }
}

# Write back
$settings | ConvertTo-Json -Depth 10 | Set-Content $SettingsPath -Encoding UTF8

$status = if ($localAlive) { "LOCAL (hybrid)" } else { "CLOUD ($CloudUrl)" }
Write-Host "`n当前模式: $status" -ForegroundColor Cyan
if (-not $localAlive) {
    Write-Host "`n💡 本地恢复后运行: memory-ha.ps1" -ForegroundColor Gray
}
