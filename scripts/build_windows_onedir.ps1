param(
    [switch]$PreviewAfterNetworkFailure
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$BuildPath = Join-Path $ProjectRoot "build\win"
$DistBase = Join-Path $ProjectRoot "dist\win"
$DistPath = Join-Path $DistBase "StockAnalysis"

function Remove-ProjectPath {
    param([string]$Target)
    $RootFull = [System.IO.Path]::GetFullPath($ProjectRoot).TrimEnd('\')
    $TargetFull = [System.IO.Path]::GetFullPath($Target)
    if (-not $TargetFull.StartsWith($RootFull + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean a path outside the project: $TargetFull"
    }
    if (Test-Path -LiteralPath $TargetFull) {
        Remove-Item -LiteralPath $TargetFull -Recurse -Force
    }
}

if (-not (Test-Path -LiteralPath $Python)) { throw "Missing .venv; run bootstrap_windows.ps1 first." }
$Version = (& $Python -c "from stock_analysis.version import __version__; print(__version__)").Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($Version)) {
    throw "Unable to determine the application version."
}
$ZipPath = Join-Path $DistBase "StockAnalysis_Windows_onedir.zip"
$HashPath = Join-Path $DistBase "SHA256SUMS.txt"
$ReportPath = Join-Path $DistBase "BUILD_REPORT_Windows.md"
$PreviousTemp = $env:TEMP
$PreviousTmp = $env:TMP
Push-Location $ProjectRoot
try {
    Remove-ProjectPath $BuildPath
    Remove-ProjectPath $DistPath
    New-Item -ItemType Directory -Path $BuildPath -Force | Out-Null
    & (Join-Path $PSScriptRoot "test_windows.ps1")
    $ValidationStatus = "passed"
    $ValidationSummary = "Offline tests and all live-network tests passed."
    $PreviousNetworkSetting = $env:RUN_NETWORK_TESTS
    $NetworkReport = Join-Path $BuildPath "network-junit.xml"
    try {
        $env:RUN_NETWORK_TESTS = "1"
        & $Python -m pytest -m network -ra `
            --basetemp (Join-Path $BuildPath "pytest-network") `
            -p no:cacheprovider --junitxml $NetworkReport
        $NetworkExitCode = $LASTEXITCODE
    } finally {
        if ($null -eq $PreviousNetworkSetting) {
            Remove-Item Env:RUN_NETWORK_TESTS -ErrorAction SilentlyContinue
        } else {
            $env:RUN_NETWORK_TESTS = $PreviousNetworkSetting
        }
    }
    if ($NetworkExitCode -ne 0) {
        if (-not (Test-Path -LiteralPath $NetworkReport)) {
            throw "Live-network tests failed without producing a JUnit report."
        }
        [xml]$NetworkXml = Get-Content -LiteralPath $NetworkReport -Raw -Encoding UTF8
        $NetworkSuite = $NetworkXml.testsuites.testsuite
        if ($null -eq $NetworkSuite -or [int]$NetworkSuite.errors -ne 0) {
            throw "Live-network tests hit an infrastructure error; preview build is forbidden."
        }
        $FailedCases = @($NetworkSuite.testcase | Where-Object { $null -ne $_.failure })
        if ($FailedCases.Count -eq 0) {
            throw "Live-network tests failed but JUnit contains no assertion failure."
        }
        if (-not $PreviewAfterNetworkFailure) {
            throw "Live-network tests have $($FailedCases.Count) failures; strict build stopped."
        }
        $FailureNames = ($FailedCases | ForEach-Object { $_.name }) -join ", "
        $ValidationStatus = "blocked"
        $ValidationSummary = (
            "Live-network tests $([int]$NetworkSuite.tests - $FailedCases.Count)/" +
            "$([int]$NetworkSuite.tests) passed; failures: $FailureNames. " +
            "The field-coverage gate remains blocked."
        )
        Write-Warning "$ValidationSummary Continuing with a $Version test preview."
    }
    $RuntimeTemp = Join-Path $BuildPath "runtime_tmp"
    New-Item -ItemType Directory -Path $RuntimeTemp -Force | Out-Null
    $env:TEMP = $RuntimeTemp
    $env:TMP = $RuntimeTemp
    & $Python (Join-Path $PSScriptRoot "generate_version_info.py")
    if ($LASTEXITCODE -ne 0) { throw "Windows version resource generation failed: $LASTEXITCODE" }
    & $Python -m PyInstaller --noconfirm --clean --workpath $BuildPath --distpath $DistBase (Join-Path $ProjectRoot "packaging\StockAnalysis.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed: $LASTEXITCODE" }
    $Exe = Join-Path $DistPath "StockAnalysis.exe"
    if (-not (Test-Path -LiteralPath $Exe)) { throw "PyInstaller did not create StockAnalysis.exe." }
    $TemplateDirectory = Join-Path $DistPath "_internal\resources\templates"
    $TemplateFiles = @(Get-ChildItem -LiteralPath $TemplateDirectory -Filter '*.xlsx' -File -ErrorAction SilentlyContinue)
    if ($TemplateFiles.Count -eq 0) {
        throw "The packaged template resource is missing."
    }
    & (Join-Path $PSScriptRoot "smoke_dist_windows.ps1")
    $PackagedSmokeLog = Join-Path $DistPath "logs\stock_analysis.log"
    if (Test-Path -LiteralPath $PackagedSmokeLog) {
        Remove-Item -LiteralPath $PackagedSmokeLog -Force
    }
    New-Item -ItemType Directory -Path $DistBase -Force | Out-Null
    if (Test-Path -LiteralPath $ZipPath) { Remove-Item -LiteralPath $ZipPath -Force }
    if (Test-Path -LiteralPath $HashPath) { Remove-Item -LiteralPath $HashPath -Force }
    if (Test-Path -LiteralPath $ReportPath) { Remove-Item -LiteralPath $ReportPath -Force }
    Compress-Archive -LiteralPath $DistPath -DestinationPath $ZipPath -CompressionLevel Optimal
    & $Python (Join-Path $PSScriptRoot "collect_release_artifacts.py") `
        --platform windows --version $Version --binary $Exe --archive $ZipPath `
        --hash-file $HashPath --report $ReportPath `
        --validation-status $ValidationStatus --validation-summary $ValidationSummary
    if ($LASTEXITCODE -ne 0) { throw "Release artifact collection failed: $LASTEXITCODE" }
    Get-FileHash -LiteralPath $Exe, $ZipPath -Algorithm SHA256
} finally {
    $env:TEMP = $PreviousTemp
    $env:TMP = $PreviousTmp
    Pop-Location
}
