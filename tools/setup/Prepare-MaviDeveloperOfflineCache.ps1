[CmdletBinding()]
param(
    [string]$Destination = (Join-Path $PSScriptRoot "..\..\vendor\developer-cache\win-x64"),

    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\.."))
$destination = [IO.Path]::GetFullPath($Destination)
$nugetRoot = Join-Path $destination "nuget-packages"
$npmRoot = Join-Path $destination "npm-cache"
$pythonRoot = Join-Path $destination "python-wheelhouse"

if (Test-Path -LiteralPath $destination) {
    Remove-Item -LiteralPath $destination -Recurse -Force
}
New-Item -ItemType Directory -Path $nugetRoot -Force | Out-Null
New-Item -ItemType Directory -Path $npmRoot -Force | Out-Null
New-Item -ItemType Directory -Path $pythonRoot -Force | Out-Null

Push-Location $repoRoot
try {
    & dotnet restore "MAVI.sln" --packages $nugetRoot
    if ($LASTEXITCODE -ne 0) {
        throw "Connected NuGet cache preparation failed."
    }

    Push-Location (Join-Path $repoRoot "src\web\mavi-web")
    try {
        & npm ci --cache $npmRoot --prefer-online
        if ($LASTEXITCODE -ne 0) {
            throw "Connected npm cache preparation failed."
        }
        & npm cache verify --cache $npmRoot
        if ($LASTEXITCODE -ne 0) {
            throw "npm cache verification failed."
        }
    }
    finally {
        Pop-Location
    }

    & $Python -m pip download --dest $pythonRoot "setuptools>=75"
    if ($LASTEXITCODE -ne 0) {
        throw "Python build dependency download failed."
    }

    Push-Location (Join-Path $repoRoot "src\vision")
    try {
        & $Python -m pip download --dest $pythonRoot ".[dev]"
        if ($LASTEXITCODE -ne 0) {
            throw "Python Development wheelhouse preparation failed."
        }
    }
    finally {
        Pop-Location
    }
}
finally {
    Pop-Location
}

Write-Host "MAVI offline developer dependency cache prepared."
Write-Host "  NuGet : $nugetRoot"
Write-Host "  npm   : $npmRoot"
Write-Host "  Python: $pythonRoot"
