<#
  First-run setup for Windows. Double-click or: powershell -ExecutionPolicy Bypass -File setup.ps1
  Verifies Python, Node, Ollama; installs deps; pulls models; inits storage.
#>
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
Write-Host "=== Study Assistant setup (fully local) ===" -ForegroundColor Cyan

function Need($name, $cmd) {
  try { $v = & $cmd 2>&1 | Out-String; Write-Host "[OK] $name : $($v.Trim().Split([Environment]::NewLine)[0])" -ForegroundColor Green; return $true }
  catch { Write-Host "[MISSING] $name" -ForegroundColor Red; return $false }
}

$py = $false; $node = $false; $ollama = $false
try { py --version; $py = $true } catch { try { python --version; $py = $true } catch { Write-Host "Install Python 3.11+ from python.org (tick 'Add to PATH')." -ForegroundColor Yellow } }
try { node --version; $node = $true } catch { Write-Host "Install Node.js LTS from nodejs.org." -ForegroundColor Yellow }
try { ollama --version; $ollama = $true } catch { Write-Host "Install Ollama from https://ollama.com/download then re-run setup." -ForegroundColor Yellow }

if ($py) {
  Write-Host "`n-- Python deps --"
  py -m pip install --upgrade pip
  py -m pip install -r backend/requirements.txt
}
if ($node) {
  Write-Host "`n-- Frontend deps --"
  Push-Location frontend
  npm install
  Pop-Location
}

New-Item -ItemType Directory -Force -Path data, data/pdfs, data/chroma | Out-Null
Write-Host "[OK] data/ folders ready" -ForegroundColor Green

if ($ollama) {
  Write-Host "`n-- Ollama models (downloads once, then offline) --"
  try { Start-Service Ollama -ErrorAction SilentlyContinue } catch {}
  Start-Process -FilePath "ollama" -ArgumentList "serve" -WindowStyle Hidden -ErrorAction SilentlyContinue
  Start-Sleep -Seconds 3
  ollama pull qwen3-embedding:0.6b
  ollama pull qwen3.5:9b
  Write-Host "If 9b is too heavy, fallback: ollama pull qwen2.5:3b" -ForegroundColor Cyan
  ollama list
} else {
  Write-Host "Skipping model download (Ollama missing). Install Ollama, then run: ollama pull qwen3.5:9b ; ollama pull qwen3-embedding:0.6b" -ForegroundColor Yellow
}

Write-Host "`n-- Building frontend --"
if ($node) { Push-Location frontend; npm run build; Pop-Location }

Write-Host "`n-- Quick backend check --"
if ($py) { py -m pytest backend/tests -q }

Write-Host "`nSetup done. Start with: start_app.bat" -ForegroundColor Green
Pause
