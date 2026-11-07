# Launch a visible Chrome with remote debugging so the scraper can attach.
#   .\scripts\open_chrome.ps1 -Port 9222
param(
    [int]$Port = 9222,
    [string]$Url = "https://www.hltv.org"
)

$candidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$chrome = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) { Write-Error "Chrome not found. Set CHROME_PATH."; exit 1 }

$profileDir = Join-Path $env:LOCALAPPDATA "hltv-scrape-profile"

Start-Process $chrome -ArgumentList @(
    "--user-data-dir=$profileDir",
    "--remote-debugging-port=$Port",
    "--remote-allow-origins=*",
    "--no-first-run",
    "--no-default-browser-check",
    "--window-size=1440,960",
    "--new-window",
    $Url
)

Write-Host "Chrome started on port $Port (profile: $profileDir)"
Write-Host "If a Cloudflare checkbox appears, click it once, then run the scraper."
