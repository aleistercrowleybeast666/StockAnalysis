param(
    [switch]$IncludeNetwork
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$TestTempRoot = Join-Path $ProjectRoot "build\pytest-windows"
if (-not (Test-Path -LiteralPath $Python)) { throw "Missing .venv; run bootstrap_windows.ps1 first." }

function Invoke-PythonChecked {
    param([string[]]$Arguments)
    & $Python @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed (exit $LASTEXITCODE): $($Arguments -join ' ')"
    }
}

Push-Location $ProjectRoot
try {
    New-Item -ItemType Directory -Path $TestTempRoot -Force | Out-Null
    Invoke-PythonChecked @('-m', 'compileall', '-q', 'src')
    Invoke-PythonChecked @('-m', 'ruff', 'check', '.')
    Invoke-PythonChecked @(
        '-m', 'pytest', '-m', 'not network',
        '--cov=stock_analysis', '--cov-report=term-missing',
        '--basetemp', (Join-Path $TestTempRoot 'offline'),
        '-p', 'no:cacheprovider'
    )
    if ($IncludeNetwork) {
        $PreviousNetworkSetting = $env:RUN_NETWORK_TESTS
        $env:RUN_NETWORK_TESTS = '1'
        try {
            Invoke-PythonChecked @(
                '-m', 'pytest', '-m', 'network', '-ra',
                '--basetemp', (Join-Path $TestTempRoot 'network'),
                '-p', 'no:cacheprovider'
            )
        } finally {
            if ($null -eq $PreviousNetworkSetting) {
                Remove-Item Env:RUN_NETWORK_TESTS -ErrorAction SilentlyContinue
            } else {
                $env:RUN_NETWORK_TESTS = $PreviousNetworkSetting
            }
        }
    }
} finally {
    Pop-Location
}
