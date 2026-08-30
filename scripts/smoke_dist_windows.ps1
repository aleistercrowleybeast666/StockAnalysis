$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$DistFolder = Join-Path $ProjectRoot "dist\win\StockAnalysis"
$Exe = Join-Path $DistFolder "StockAnalysis.exe"
$TempBase = [System.IO.Path]::GetTempPath()
$ChinesePrefix = -join [char[]](0x80A1, 0x7968, 0x5206, 0x6790, 0x8868)
$ChineseTest = -join [char[]](0x6D4B, 0x8BD5)
$TestRoot = Join-Path $TempBase ($ChinesePrefix + ' ' + $ChineseTest)

if (-not (Test-Path -LiteralPath $Exe)) { throw "Packaged StockAnalysis.exe is missing." }

function ConvertTo-QuotedArgument {
    param([string]$Value)
    return '"' + $Value.Replace('"', '\"') + '"'
}

function Invoke-WorkbookValidation {
    param([string]$WorkbookPath)
    & $Python (Join-Path $PSScriptRoot "validate_workbook.py") $WorkbookPath
    if ($LASTEXITCODE -ne 0) { throw "Workbook validation failed: $WorkbookPath" }
}

function Invoke-CheckedCliProcess {
    param(
        [string]$FilePath,
        [string[]]$ProcessArguments,
        [string]$FailureLabel
    )

    $Process = Start-Process -FilePath $FilePath -ArgumentList $ProcessArguments -PassThru -WindowStyle Hidden
    if (-not $Process.WaitForExit(120000)) {
        Stop-Process -Id $Process.Id -Force
        $null = $Process.WaitForExit(5000)
        throw "$FailureLabel timed out after 120 seconds."
    }
    if ($Process.ExitCode -ne 0) { throw "$FailureLabel exit code: $($Process.ExitCode)" }
    $Process.Dispose()
}

function Remove-TestRootSafely {
    param([string]$Path)

    for ($Attempt = 1; $Attempt -le 12; $Attempt++) {
        if (-not (Test-Path -LiteralPath $Path)) { return }
        try {
            Remove-Item -LiteralPath $Path -Recurse -Force
            return
        } catch {
            if ($Attempt -eq 12) { throw }
            Start-Sleep -Milliseconds 250
        }
    }
}

$TempFull = [System.IO.Path]::GetFullPath($TestRoot)
$BaseFull = [System.IO.Path]::GetFullPath($TempBase)
if (-not $TempFull.StartsWith($BaseFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "The smoke-test path is outside the temporary directory."
}
Remove-TestRootSafely $TestRoot
New-Item -ItemType Directory -Path $TestRoot -Force | Out-Null
$OriginalAnalysisHome = $env:STOCK_ANALYSIS_HOME
$env:STOCK_ANALYSIS_HOME = Join-Path $TestRoot "runtime"

try {
    $Report = Join-Path $TestRoot "self-test.json"
    Invoke-CheckedCliProcess -FilePath $Exe -ProcessArguments @(
        '--self-test', '--report', (ConvertTo-QuotedArgument $Report)
    ) -FailureLabel "Packaged self-test"
    $ReportData = Get-Content -LiteralPath $Report -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $ReportData.ok) { throw "Packaged self-test report failed." }

    $Output = Join-Path $TestRoot ($ChinesePrefix + ' fixture output.xlsx')
    Invoke-CheckedCliProcess -FilePath $Exe -ProcessArguments @(
        '--headless', '--fixture-mode',
        '--max-a-share-companies', '4', '--max-hk-companies', '4',
        '--output', (ConvertTo-QuotedArgument $Output)
    ) -FailureLabel "Packaged fixture export"
    Invoke-WorkbookValidation $Output

    $SecondOutput = Join-Path $TestRoot ($ChinesePrefix + ' second fixture output.xlsx')
    Invoke-CheckedCliProcess -FilePath $Exe -ProcessArguments @(
        '--headless', '--fixture-mode',
        '--max-a-share-companies', '4', '--max-hk-companies', '4',
        '--output', (ConvertTo-QuotedArgument $SecondOutput)
    ) -FailureLabel "Second packaged fixture export"
    Invoke-WorkbookValidation $SecondOutput
    $PersistentDatabases = @(
        Get-ChildItem -LiteralPath $env:STOCK_ANALYSIS_HOME -Recurse -File `
            -ErrorAction SilentlyContinue |
            Where-Object { $_.Extension -in @('.sqlite', '.sqlite3', '.db') }
    )
    if ($PersistentDatabases.Count -ne 0) {
        throw "Packaged application created a persistent database."
    }
    foreach ($LegacyDirectoryName in @('cache', 'raw', 'raw_responses')) {
        if (Test-Path -LiteralPath (Join-Path $env:STOCK_ANALYSIS_HOME $LegacyDirectoryName)) {
            throw "Packaged application created legacy cache directory: $LegacyDirectoryName"
        }
    }

    $CopiedFolder = Join-Path $TestRoot "StockAnalysis"
    Copy-Item -LiteralPath $DistFolder -Destination $CopiedFolder -Recurse
    $CopiedExe = Join-Path $CopiedFolder "StockAnalysis.exe"
    $CopiedReport = Join-Path $TestRoot ($ChinesePrefix + ' path self-test.json')
    $CopiedOutput = Join-Path $TestRoot ($ChinesePrefix + ' path fixture output.xlsx')
    $OriginalPath = $env:PATH
    $env:PATH = Join-Path $env:SystemRoot "System32"
    try {
        Invoke-CheckedCliProcess -FilePath $CopiedExe -ProcessArguments @(
            '--self-test', '--report', (ConvertTo-QuotedArgument $CopiedReport)
        ) -FailureLabel "Copied-path self-test"
        Invoke-CheckedCliProcess -FilePath $CopiedExe -ProcessArguments @(
            '--headless', '--fixture-mode',
            '--max-a-share-companies', '4', '--max-hk-companies', '4',
            '--output', (ConvertTo-QuotedArgument $CopiedOutput)
        ) -FailureLabel "Copied-path fixture export"
    } finally {
        $env:PATH = $OriginalPath
    }
    Invoke-WorkbookValidation $CopiedOutput

    $PortableOutput = Join-Path $TestRoot ($ChinesePrefix + ' portable log output.xlsx')
    $PortableLog = Join-Path $CopiedFolder "logs\stock_analysis.log"
    $SmokeAnalysisHome = $env:STOCK_ANALYSIS_HOME
    $OriginalLocalAppData = $env:LOCALAPPDATA
    Remove-Item Env:STOCK_ANALYSIS_HOME -ErrorAction SilentlyContinue
    $env:LOCALAPPDATA = Join-Path $TestRoot "portable-profile"
    try {
        Invoke-CheckedCliProcess -FilePath $CopiedExe -ProcessArguments @(
            '--headless', '--fixture-mode',
            '--max-a-share-companies', '1', '--max-hk-companies', '1',
            '--output', (ConvertTo-QuotedArgument $PortableOutput)
        ) -FailureLabel "Portable-log fixture export"
    } finally {
        $env:STOCK_ANALYSIS_HOME = $SmokeAnalysisHome
        if ($null -eq $OriginalLocalAppData) {
            Remove-Item Env:LOCALAPPDATA -ErrorAction SilentlyContinue
        } else {
            $env:LOCALAPPDATA = $OriginalLocalAppData
        }
    }
    if (-not (Test-Path -LiteralPath $PortableLog)) {
        throw "Packaged application did not create its portable log file."
    }
    if ((Get-Item -LiteralPath $PortableLog).Length -eq 0) {
        throw "Packaged application created an empty portable log file."
    }
    Invoke-WorkbookValidation $PortableOutput

    $GuiProcess = Start-Process -FilePath $CopiedExe -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 4
    if ($GuiProcess.HasExited) { throw "GUI exited immediately with code $($GuiProcess.ExitCode)." }
    $null = $GuiProcess.CloseMainWindow()
    if (-not $GuiProcess.WaitForExit(5000)) {
        Stop-Process -Id $GuiProcess.Id -Force
        if (-not $GuiProcess.WaitForExit(5000)) {
            throw "GUI smoke-test process did not exit after termination."
        }
    }
    $GuiProcess.Dispose()
} finally {
    if ($null -eq $OriginalAnalysisHome) {
        Remove-Item Env:STOCK_ANALYSIS_HOME -ErrorAction SilentlyContinue
    } else {
        $env:STOCK_ANALYSIS_HOME = $OriginalAnalysisHome
    }
    Remove-TestRootSafely $TestRoot
}
