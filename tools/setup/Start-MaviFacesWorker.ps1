[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Join-Path $PSScriptRoot "..\.."),
    [Parameter(Mandatory = $true)][string]$ApiBaseUrl,
    [string]$WorkerId = "faces-01",
    # The embeddings-onnx-v1 environment created by tools\setup\Install-MaviEmbeddingsRuntime.ps1: the faces role adds
    # no Python library (onnxruntime, numpy, Pillow, httpx, pydantic are that family's lock).
    [Parameter(Mandatory = $true)][string]$Python,
    # The model store the face pack was staged into (tools\vision\faces_packs.py stage).
    [Parameter(Mandatory = $true)][string]$ModelRoot,
    # cpu (default) or cuda. Explicit cuda fails closed where the CUDA build of ONNX Runtime is absent (no silent CPU fallback).
    [ValidateSet("cpu", "cuda", "auto")][string]$DevicePolicy = "cpu",
    [string]$CudaDllDirectory
)

# PoC S6 (ADR-022): the faces role on the committed Development manifest and pipeline profile. Always Development mode:
# the AdaFace checkpoint is research-only and the role is refused under P1-P3. The worker verifies every Model Pack
# artefact SHA-256 before loading, derives its identity from the manifest and profile bytes, and leases only that
# identity; it analyses only runs of cameras an operator opted in. The platform must run with the matching configuration:
#   Faces:Enabled=true
#   Faces:ModelManifestPath=<root>\models\manifests\faces-yunet-adaface-ir50-dev-v1.json
#   Faces:PipelineProfilePath=<root>\src\vision\config\faces\development-faces-adaface-v1.json

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force
$RepositoryRoot = [IO.Path]::GetFullPath($RepositoryRoot)
$head = (Resolve-MaviApplicationRevision -Root $RepositoryRoot).Revision

$env:MAVI_API_BASE_URL = $ApiBaseUrl
$env:MAVI_WORKER_ID = $WorkerId
$env:MAVI_PRODUCTION_MODE = "false"
$env:MAVI_DEVICE_POLICY = $DevicePolicy
$env:MAVI_FACE_MANIFEST_PATH = Join-Path $RepositoryRoot "models\manifests\faces-yunet-adaface-ir50-dev-v1.json"
$env:MAVI_FACE_PIPELINE_PROFILE_PATH = Join-Path $RepositoryRoot "src\vision\config\faces\development-faces-adaface-v1.json"
$env:MAVI_MODEL_ROOT = [IO.Path]::GetFullPath($ModelRoot)
$env:MAVI_BUILD_ID = "development"
$env:MAVI_COMMIT_SHA = $head
$env:PYTHONPATH = Join-Path $RepositoryRoot "src\vision"
if ($CudaDllDirectory) { $env:MAVI_CUDA_DLL_DIRECTORY = [IO.Path]::GetFullPath($CudaDllDirectory) }
else { Remove-Item Env:MAVI_CUDA_DLL_DIRECTORY -ErrorAction SilentlyContinue }

Write-Host "Starting MAVI faces worker (PoC S6, YuNet + AdaFace IR-50, unverified Model Pack; Development only)" -ForegroundColor Yellow
Write-Host "  Face results are candidates, never identification."
Write-Host "  Application : $head"
Write-Host "  Manifest    : $env:MAVI_FACE_MANIFEST_PATH"
Write-Host "  Profile     : $env:MAVI_FACE_PIPELINE_PROFILE_PATH"
Write-Host "  Model store : $env:MAVI_MODEL_ROOT"
Write-Host "  Device      : $DevicePolicy"
& $Python -m mavi_vision.faces.main
exit $LASTEXITCODE
