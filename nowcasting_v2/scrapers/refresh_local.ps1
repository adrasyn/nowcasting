<#
  refresh_local.ps1 — MANUAL FALLBACK for the R-dependent half of the v2 refresh.

  NOT the scheduled routine. The GitHub Actions weekly cron is now canonical for
  all v2 R work (fetch RBA/ABS, fetch GDP, emit, regenerate the indicator grid).
  Use this only for an ad-hoc local refresh (e.g. the cron is down, or you want a
  same-day refresh after a data drop). The separate Codex cloud survey task is
  R-free — see docs/weekly-survey-refresh.md.

  Runs the same R + Python steps the cron runs, in the same order:
    1. fetch_rba_panel.R   -> credit, yields, spreads, BBSW, credit_card  (RBA)
    2. fetch_abs_panel.R   -> employment, hours, MHSI, exports, building approvals
    3. fetch_rt_gdp.R      -> GDP regressand + target-quarter driver (ABS)
    4. emit_v2_json.R      -> re-run the nowcast -> data/latest_v2.json
    5. gen_indicators_v2.py-> refresh the indicator grid -> data/indicators_v2.json

  Then review `git status` and commit + push yourself.

  Usage (from anywhere):  pwsh nowcasting_v2/scrapers/refresh_local.ps1
#>
$ErrorActionPreference = "Stop"

# repo root = two levels up from this script (scrapers -> nowcasting_v2 -> repo)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Resolve-Path (Join-Path $here "..\..")
$v2   = Join-Path $repo "nowcasting_v2"
$lib  = Join-Path $repo "pipeline\renv\library\windows\R-4.5\x86_64-w64-mingw32"

# locate Rscript — prefer a 4.5.x (matches the renv lib), else the highest version
# present. Sort by parsed [version], NOT lexically (so R-4.10 > R-4.5).
$rs = $null
$cands = Get-ChildItem "C:\Program Files\R\R-*\bin\x64\Rscript.exe" -ErrorAction SilentlyContinue |
         Sort-Object { [version]($_.FullName -replace '.*\\R-([\d.]+)\\.*', '$1') }
$rs = ($cands | Where-Object { $_.FullName -match '\\R-4\.5\.' } | Select-Object -Last 1).FullName
if (-not $rs) { $rs = ($cands | Select-Object -Last 1).FullName }
if (-not $rs) { $rs = (Get-Command Rscript -ErrorAction SilentlyContinue).Source }
if (-not $rs) { throw "Rscript not found - install R 4.5.x" }
if (-not (Test-Path $lib)) { throw "renv library not found at $lib" }

# rlang 1.1.6 (base lib) is too old; putting the renv lib on R_LIBS makes R load
# rlang 1.2.0 from there instead. This is the documented host workaround.
$env:R_LIBS = $lib
Set-Location $v2
Write-Host "== R: $rs"
Write-Host "== R_LIBS: $lib`n"

foreach ($step in @(
    @{ name = "RBA panel (incl. credit_card)"; script = "R/fetch/fetch_rba_panel.R" },
    @{ name = "ABS panel (incl. MHSI, building approvals)"; script = "R/fetch/fetch_abs_panel.R" },
    @{ name = "GDP regressand / target driver";  script = "R/fetch_rt_gdp.R" },
    @{ name = "nowcast emit (latest_v2.json)";    script = "R/emit_v2_json.R" }
)) {
    Write-Host "==== $($step.name) ===="
    & $rs $step.script
    if ($LASTEXITCODE -ne 0) { throw "$($step.script) failed (exit $LASTEXITCODE)" }
    Write-Host ""
}

Write-Host "==== indicator grid (indicators_v2.json) ===="
python gen_indicators_v2.py
if ($LASTEXITCODE -ne 0) { throw "gen_indicators_v2.py failed (exit $LASTEXITCODE)" }

Write-Host "`n== refresh_local.ps1 done. Review 'git status', then commit + push."
