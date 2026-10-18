<#
Wires the Claude Code status line (statusline.sh beside this script) into
%USERPROFILE%\.claude\settings.json on this PC. Run it through
Setup_Statusline.bat. Safe to re-run: every step checks before it acts.

  1. finds Git Bash (Git for Windows);
  2. creates the state folder %LOCALAPPDATA%\Tools\claude_statusline;
  3. settings.json statusLine:
       - none set              -> set it to this folder's statusline.sh
       - points at a statusline.sh that exists -> left alone (warns if that
         file differs from this one)
       - anything else (another command, or a path that does not exist)
                               -> left alone unless -Force, which replaces
                                  it after a dated backup;
  4. checks Node (for the cost totals) and Python (for the config page);
  5. renders a sample payload.

Written 2026-10-08 as a per-PC setup for the claude-statusline tool; made
location-independent 2026-10-18 when the tool became its own repo. Verified by
running it on a PC with the line already wired and on a missing settings entry.
#>
param([switch]$Force)

$ErrorActionPreference = 'Stop'
$ok = $true
function Say($m)  { Write-Host "  $m" }
function Warn($m) { Write-Host "  WARNING: $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "  ERROR: $m" -ForegroundColor Red; $script:ok = $false }

$here     = $PSScriptRoot
$script   = Join-Path $here 'statusline.sh'
$settings = Join-Path $env:USERPROFILE '.claude\settings.json'

Write-Host 'Claude Code status line setup'
Say "Script: $script"

# 1. Git Bash -- never WSL's bash.exe from System32
$bash = @(
    (Join-Path $env:ProgramFiles 'Git\bin\bash.exe'),
    (Join-Path ${env:ProgramFiles(x86)} 'Git\bin\bash.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Git\bin\bash.exe')
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if ($bash) { Say "Git Bash: $bash" }
else { Fail 'Git Bash not found. Install Git for Windows and re-run.' }

# 2. state folder
$state = Join-Path $env:LOCALAPPDATA 'Tools\claude_statusline'
if (-not (Test-Path $state)) { New-Item -ItemType Directory $state -Force | Out-Null; Say "Created $state" }
else { Say "State folder: $state" }

# 3. settings.json statusLine
if ($ok) {
    $command = "`"$bash`" `"$script`""
    $raw = if (Test-Path $settings) { Get-Content $settings -Raw } else { $null }
    $cfg = if ($raw) { $raw | ConvertFrom-Json } else { [pscustomobject]@{} }
    $current = $cfg.statusLine.command
    $target = if ($current -match '"([^"]*statusline\.sh)"') { $Matches[1] } else { $null }
    $set = $false
    if (-not $current) {
        $set = $true
    } elseif ($target -and (Test-Path $target) -and -not $Force) {
        Say "settings.json: statusLine runs $target"
        if ((Get-FileHash $target).Hash -ne (Get-FileHash $script).Hash) {
            Warn 'That is a different statusline.sh from this one. Re-run with -Force to point at this folder.'
        }
    } elseif ($Force) {
        $set = $true
    } else {
        if ($target) { Warn "settings.json runs $target, which does not exist." }
        else { Warn "settings.json has another statusLine: $current" }
        Warn 'Left unchanged. Re-run with -Force (Setup_Statusline.bat -Force) to point it at this folder.'
    }
    if ($set) {
        if ($raw) { Copy-Item $settings "$settings.$(Get-Date -Format yyyy-MM-dd).bak" -Force }
        $cfg | Add-Member -NotePropertyName statusLine -NotePropertyValue ([pscustomobject]@{ type = 'command'; command = $command }) -Force
        New-Item -ItemType Directory (Split-Path $settings) -Force | Out-Null
        [IO.File]::WriteAllText($settings, ($cfg | ConvertTo-Json -Depth 32), (New-Object Text.UTF8Encoding $false))
        Say "settings.json: statusLine set to this folder$(if ($raw) { ' (backup saved beside it)' })"
    }
}

# 4. Node / npx for the cost totals, Python for the config page
if (Get-Command npx -ErrorAction SilentlyContinue) { Say 'Node/npx: found (cost totals via ccusage)' }
else { Warn 'Node.js not found: the week/month cost totals stay blank until it is installed.' }
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Warn 'Python not found: Statusline_Config.bat (the config page) needs it.' }

# 5. smoke test
if ($ok) {
    $payload = '{"model":{"id":"claude-opus-5-5","display_name":"Opus 5.5"},"current_dir":"C:\\Users\\example\\project","context_window":{"remaining_percentage":91}}'
    $out = $payload | & $bash $script
    Say "Test render: $out"
    Write-Host ''
    Write-Host 'Done. Start a new Claude Code session (or wait for the next refresh) to see it.'
} else {
    Write-Host ''
    Write-Host 'Setup incomplete - fix the errors above and re-run.' -ForegroundColor Red
    exit 1
}
