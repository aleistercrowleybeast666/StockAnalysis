param(
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Test-PythonCandidate {
    param([string]$Candidate)
    if (-not $Candidate) { return $false }
    try {
        $Info = & $Candidate -c "import struct,sys; print(f'{sys.version_info.major}.{sys.version_info.minor}|{struct.calcsize(chr(80))*8}')"
        if ($LASTEXITCODE -ne 0) { return $false }
        $Parts = $Info.Trim().Split('|')
        return $Parts.Count -eq 2 -and $Parts[0] -in @('3.11','3.12','3.13') -and $Parts[1] -eq '64'
    } catch {
        return $false
    }
}

function Invoke-PythonChecked {
    param(
        [string]$Executable,
        [string[]]$Arguments
    )
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed (exit $LASTEXITCODE): $($Arguments -join ' ')"
    }
}

if (-not (Test-Path -LiteralPath $VenvPython)) {
    $Candidates = @()
    if ($PythonPath) { $Candidates += $PythonPath }
    try { $Candidates += (& py -3.12 -c "import sys; print(sys.executable)").Trim() } catch {}
    try { $Candidates += (& python3.12 -c "import sys; print(sys.executable)").Trim() } catch {}
    try { $Candidates += (& python -c "import sys; print(sys.executable)").Trim() } catch {}
    $Selected = $Candidates | Where-Object { Test-PythonCandidate $_ } | Select-Object -First 1
    if (-not $Selected) {
        throw "No compatible 64-bit Python 3.12/3.11/3.13 was found. Use -PythonPath to specify one."
    }
    Invoke-PythonChecked $Selected @('-m', 'venv', (Join-Path $ProjectRoot '.venv'))
}

Invoke-PythonChecked $VenvPython @('-m', 'pip', 'install', '--upgrade', 'pip', 'setuptools', 'wheel')
Invoke-PythonChecked $VenvPython @('-m', 'pip', 'install', '-e', "${ProjectRoot}[dev]")
Invoke-PythonChecked $VenvPython @(
    '-c',
    "import platform,sys,PySide6,PyInstaller; print(sys.executable); print(sys.version); print(platform.architecture()); print('PySide6',PySide6.__version__); print('PyInstaller',PyInstaller.__version__)"
)
