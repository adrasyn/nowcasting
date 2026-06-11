<#
  refresh_local.ps1 - the R-dependent half of the weekly v2 refresh, for the
  LOCAL (Claude Cowork) task. The cloud routine can't do these (no R; and ABS/RBA
  aside, NAB/ANZ are Akamai-WAF-blocked from datacenter IPs). On the laptop we
  have R + a residential IP + a browser, so one task can refresh everything.

  This script does the DETERMINISTIC, R-dependent steps:
    1. fetch_rba_panel.R   -> credit, housing/business credit, yields, spreads,
                              BBSW, credit_card   (RBA CSV; closes the stale gap)
    2. fetch_abs_panel.R   -> employment, hours, MHSI, exports, building approvals
    3. emit_v2_json.R      -> re-run the nowcast -> data/latest_v2.json

  RUN ORDER in the Cowork task: do the SURVEY scrapes first (NAB/ANZ/Westpac via
  the agent + scrapers/nab_monthly.py), THEN run this script, THEN commit + push.
  That way emit_v2_json.R sees every fresh series.

  Usage (from anywhere):  pwsh nowcasting_v2/scrapers/refresh_local.ps1
#>
$ErrorActionPreference = "Stop"

# repo root = two levels up from this script (scrapers -> nowcasting_v2 -> repo)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$repo = Resolve-Path (Join-Path $here "..\..")
$v2   = Join-Path $repo "nowcasting_v2"
$lib  = Join-Path $repo "pipeline\renv\library\windows\R-4.5\x86_64-w64-mingw32"

# locate Rscript
$rs = (Get-Command Rscript -ErrorAction SilentlyContinue).Source
if (-not $rs) { $rs = (Get-ChildItem "C:\Program Files\R\*\bin\x64\Rscript.exe" -ErrorAction SilentlyContinue | Select-Object -Last 1).FullName }
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
    @{ name = "ABS panel";                     script = "R/fetch/fetch_abs_panel.R" },
    @{ name = "nowcast emit (latest_v2.json)"; script = "R/emit_v2_json.R" }
)) {
    Write-Host "==== $($step.name) ===="
    & $rs $step.script
    if ($LASTEXITCODE -ne 0) { throw "$($step.script) failed (exit $LASTEXITCODE)" }
    Write-Host ""
}

Write-Host "== refresh_local.ps1 done. Review 'git status', then commit + push."
