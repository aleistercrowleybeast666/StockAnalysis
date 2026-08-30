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
    $ValidationSummary = "离线测试与全部真实网络测试通过。"
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
            throw "真实网络测试失败且没有生成 JUnit 报告。"
        }
        [xml]$NetworkXml = Get-Content -LiteralPath $NetworkReport -Raw -Encoding UTF8
        $NetworkSuite = $NetworkXml.testsuites.testsuite
        if ($null -eq $NetworkSuite -or [int]$NetworkSuite.errors -ne 0) {
            throw "真实网络测试发生基础设施错误，禁止继续生成预览。"
        }
        $FailedCases = @($NetworkSuite.testcase | Where-Object { $null -ne $_.failure })
        if ($FailedCases.Count -eq 0) {
            throw "真实网络测试退出失败但 JUnit 中没有断言失败记录。"
        }
        if (-not $PreviewAfterNetworkFailure) {
            throw "真实网络测试有 $($FailedCases.Count) 项失败，严格构建停止。"
        }
        $FailureNames = ($FailedCases | ForEach-Object { $_.name }) -join "、"
        $ValidationStatus = "blocked"
        $ValidationSummary = (
            "真实网络测试 $([int]$NetworkSuite.tests - $FailedCases.Count)/" +
            "$([int]$NetworkSuite.tests) 通过；失败：$FailureNames。" +
            "字段覆盖率门禁未解除。"
        )
        Write-Warning "$ValidationSummary 将继续生成 0.4.1 测试预览。"
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
