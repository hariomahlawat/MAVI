[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$KitRoot,

    # Every Runtime Pack to store (one per bound platform variant being shipped).
    [Parameter(Mandatory = $true)]
    [string[]]$RuntimePackRoot,

    # Every Model Pack the component binding requires for those variants.
    [Parameter(Mandatory = $true)]
    [string[]]$ModelPackRoot,

    [string]$RepositoryRoot = (Join-Path $PSScriptRoot "..\..")
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot.Trim().Trim('"'))
$KitRoot = [IO.Path]::GetFullPath($KitRoot.Trim().Trim('"'))
$RuntimePackRoot = @($RuntimePackRoot | ForEach-Object { [IO.Path]::GetFullPath($_.Trim().Trim('"')) })
$ModelPackRoot = @($ModelPackRoot | ForEach-Object { [IO.Path]::GetFullPath($_.Trim().Trim('"')) })

foreach ($path in @(@($KitRoot, $RepositoryRoot) + $RuntimePackRoot + $ModelPackRoot)) {
    if (-not (Test-Path -LiteralPath $path -PathType Container)) {
        throw "Required directory does not exist: $path"
    }
}

$tool = Join-Path $RepositoryRoot "tools\vision\sync_offline_vision_components.py"
$ownershipTool = Join-Path $RepositoryRoot "tools\vision\verify_offline_component_ownership.py"
$componentBinding = Join-Path $RepositoryRoot "src\vision\config\components\phase1-bindings-v2.json"
if (-not (Test-Path -LiteralPath $tool -PathType Leaf)) { throw "Vision component-store tool is missing: $tool" }
if (-not (Test-Path -LiteralPath $ownershipTool -PathType Leaf)) { throw "Vision component ownership verifier is missing: $ownershipTool" }
if (-not (Test-Path -LiteralPath $componentBinding -PathType Leaf)) { throw "Vision component binding is missing: $componentBinding" }

$git = Get-Command git.exe -ErrorAction SilentlyContinue
if (-not $git) { throw "git.exe is required to identify the Application Overlay revision." }
$head = (& $git.Source -C $RepositoryRoot rev-parse HEAD 2>$null | Out-String).Trim()
if ($LASTEXITCODE -ne 0 -or $head -notmatch '^[0-9a-f]{40}$') { throw "Unable to determine repository HEAD." }

# The tool reads the binding through mavi_vision, so the workspace environment
# (which has its dependencies) is preferred over a bare interpreter.
$python = $null
$workspacePython = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $workspacePython -PathType Leaf) { $python = $workspacePython }
$py = if ($python) { $null } else { Get-Command py.exe -ErrorAction SilentlyContinue }
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

$syncArguments = @($tool, "sync", "--kit-root", $KitRoot, "--component-binding", $componentBinding, "--application-revision", $head)
foreach ($root in $RuntimePackRoot) { $syncArguments += @("--runtime-pack", $root) }
foreach ($root in $ModelPackRoot) { $syncArguments += @("--model-pack", $root) }
& $python @syncArguments
if ($LASTEXITCODE -ne 0) { throw "Vision component-store synchronization failed with exit code $LASTEXITCODE." }

& $python $tool verify --kit-root $KitRoot
if ($LASTEXITCODE -ne 0) { throw "Vision component-store verification failed with exit code $LASTEXITCODE." }

# Component ownership is a separate fail-closed boundary: Runtime Pack and
# Model Pack may not silently carry the same heavy artifact, and the
# Application Overlay inventory may contain binding metadata only.
& $python $ownershipTool --kit-root $KitRoot
if ($LASTEXITCODE -ne 0) { throw "Vision component ownership verification failed with exit code $LASTEXITCODE." }

Write-Host ""
Write-Host "MAVI offline Vision component store synchronized and verified." -ForegroundColor Green
Write-Host "  Kit root     : $KitRoot"
Write-Host "  Application  : $head (provenance; the binding SHA-256 in the inventory is the compatibility identity)"
Write-Host "  Runtime Packs: $($RuntimePackRoot.Count)"
Write-Host "  Model Packs  : $($ModelPackRoot.Count)"
Write-Host "  Inventory    : $(Join-Path $KitRoot 'vision\component-inventory.json')"
