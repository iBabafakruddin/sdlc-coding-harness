<#
.SYNOPSIS
  Native Windows PowerShell Installer for Lean Parallel SDLC Harness.
.EXAMPLE
  .\install.ps1
  .\install.ps1 -TargetDir "C:\Projects\my-spring-app"
#>
param(
    [string]$TargetDir = "."
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if (Get-Command python -ErrorAction SilentlyContinue) {
    python "$ScriptDir\install.py" "$TargetDir"
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    py -3 "$ScriptDir\install.py" "$TargetDir"
} else {
    Write-Error "Python 3 is required. Install Python from https://www.python.org/ or Microsoft Store."
}
