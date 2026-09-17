[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$KitRoot,

    [Parameter(Mandatory = $true)]
    [string]$RuntimePackRoot,

    [Parameter(Mandatory = $true)]
    [string]$ModelPackRoot,

    [string]$RepositoryRoot = (Join-Path $PSScriptRoot "..\..")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot.Trim().Trim('"'))
$KitRoot = [IO.Path]::GetFullPath($KitRoot.Trim().Trim('"'))
$RuntimePackRoot = [IO.Path]::GetFullPath($RuntimePackRoot.Trim().Trim('"'))
$ModelPackRoot = [IO.Path]::GetFullPath($ModelPackRoot.Trim().Trim('"'))

foreach ($path in @($KitRoot, $RuntimePackRoot, $ModelPackRoot, $RepositoryRoot)) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        throw "Required directory does not exist: $path"
    }
}

$tool = Join-Path $RepositoryRoot "tools\vision\sync_offline_vision_components.py"
$requirements = Join-Path $RepositoryRoot "src\vision\config\components\mmdetection-phase1-v1.json"
if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) { throw "Vision component-store tool is missing: $tool" }
if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) { throw "Vision component requirements are missing: $requirements" }

$git = Get-Command git.exe -ErrorAction SilentlyContinue
if (-not $git) { throw "git.exe is required to identify the Application Overlay revision." }
$head = (& $git.Source -C $RepositoryRoot rev-parse HEAD 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') { throw "Unable to determine repository HEAD." }

$python = $null
$py = Get-Command py.exe -ErrorAction SilentlyContinue
if ($py -and $py.Source) {
    try {
        $candidate = (& $py.Source -3.13 -c "import sys; print(sys.executable)" 2>$null | Out-String).Trim()
        if ($LASTEXITCODE -eq 0 -and $candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            $python = $candidate
        }
    }
    catch { }
}
if (-not $python) {
    $pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($pythonCommand -and $pythonCommand.Source) { $python = $pythonCommand.Source }
}
if (-not $python) { throw "Python is required to synchronize the offline Vision component store." }

& $python $tool sync `
    --kit-root $KitRoot `
    --runtime-pack $RuntimePackRoot `
    --model-pack $ModelPackRoot `
    --component-requirements $requirements `
    --application-revision $head
if ($LASTEXITCODE -ne 0) { throw "Vision component-store synchronization failed with exit code $LASTEXITCODE." }

& $python $tool verify --kit-root $KitRoot
if ($LASTEXITCODE -ne 0) { throw "Vision component-store verification failed with exit code $LASTEXITCODE." }

Write-Host ""
Write-Host "MAVI offline Vision component store synchronized and verified." -ForegroundColor Green
Write-Host "  Kit root     : $KitRoot"
Write-Host "  Application  : $head"
Write-Host "  Inventory    : $(Join-Path $KitRoot 'vision\component-inventory.json')"
