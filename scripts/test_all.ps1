param([switch]$IncludeNetwork)

$ErrorActionPreference = "Stop"
& (Join-Path $PSScriptRoot "test_windows.ps1") -IncludeNetwork:$IncludeNetwork
