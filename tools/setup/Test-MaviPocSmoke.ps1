[CmdletBinding()]
param(
    [string]$DataRoot = (Join-Path $env:ProgramData "MAVI\PoC"),
    # One small MP4 clip. The repository carries no media: use the bundle's smoke clip or a
    # local clip the operator is entitled to use (owner-machine runs).
    [Parameter(Mandatory = $true)][string]$ClipPath,
    [string]$CameraCode = "POC-S2-01",
    # Local wall-clock start of the recording, in the camera's time zone.
    [string]$RecordingStartLocal = "2026-10-28T09:00:00",
    [int]$TimeoutMinutes = 60,
    # Where the result and the transcript are retained (default <DataRoot>\logs\smoke-<time>).
    [string]$EvidenceDirectory
)

# PoC S1 smoke test (register row A3): against a running poc-single-host installation,
# import one clip -> processing completes -> GET /api/tracks returns Tracks for it (search)
# -> the first Track's detail reads back (Review). Exit code 0 only when every step passed;
# the result JSON and the transcript are retained either way.

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
Import-Module (Join-Path $PSScriptRoot "Mavi.Setup.Common.psm1") -Force
Import-Module (Join-Path $PSScriptRoot "Mavi.Poc.psm1") -Force
Add-Type -AssemblyName System.Net.Http

$state = Read-MaviJson -Path (Join-Path ([IO.Path]::GetFullPath($DataRoot)) "config\poc-installation.json")
$apiBaseUrl = ([string]$state.apiBaseUrl).TrimEnd("/")
if ([string]::IsNullOrWhiteSpace($EvidenceDirectory)) {
    $EvidenceDirectory = Join-Path ([string]$state.dataRoot) ("logs\smoke-" + (Get-Date -Format "yyyyMMdd-HHmmss"))
}
New-Item -ItemType Directory -Path $EvidenceDirectory -Force | Out-Null
$transcriptPath = Join-Path $EvidenceDirectory "smoke-transcript.log"
$resultPath = Join-Path $EvidenceDirectory "smoke-result.json"
Start-Transcript -LiteralPath $transcriptPath -Force | Out-Null

$steps = New-Object System.Collections.Generic.List[object]
function Add-MaviSmokeStep {
    param([string]$Name, [bool]$Passed, [string]$Detail)
    $steps.Add([ordered]@{ step = $Name; passed = $Passed; detail = $Detail; atUtc = [DateTimeOffset]::UtcNow.ToString("O") })
    Write-MaviSetupStatus -Name $Name -Status $(if ($Passed) { "OK" } else { "FAIL" }) -Detail $Detail
    if (-not $Passed) { throw "Smoke step '$Name' failed: $Detail" }
}
function Invoke-MaviApi {
    param([string]$Method = "Get", [Parameter(Mandatory = $true)][string]$Path, $Body)
    $arguments = @{ Uri = "$apiBaseUrl$Path"; Method = $Method; TimeoutSec = 60 }
    if ($null -ne $Body) { $arguments.ContentType = "application/json"; $arguments.Body = ($Body | ConvertTo-Json -Compress) }
    Invoke-RestMethod @arguments
}

$client = New-Object System.Net.Http.HttpClient
$client.Timeout = [TimeSpan]::FromMinutes(30)
$passed = $false
$failure = $null
$summary = [ordered]@{}
try {
    Write-Host "MAVI PoC smoke test (row A3) against $apiBaseUrl"
    Write-Host "  $(Get-MaviPocDisclosureStatement)" -ForegroundColor Yellow

    $health = Invoke-MaviApi -Path "/api/health"
    Add-MaviSmokeStep "Platform health" ([string]$health.status -eq "ok") "$($health.build) / $($health.commit)"

    $deployment = Invoke-MaviApi -Path "/api/system/deployment"
    $disclosureOk = [string]$deployment.profile -eq (Get-MaviPocProfile) -and -not [bool]$deployment.productionQualified -and [string]$deployment.evidenceClass -eq "Development"
    $deviceText = if ($deployment.device) { "$($deployment.device.resolvedPolicy) ($($deployment.device.reason))" } else { [string]$deployment.deviceStatus }
    Add-MaviSmokeStep "Disclosure" $disclosureOk "$($deployment.profile); productionQualified=$($deployment.productionQualified); evidence $($deployment.evidenceClass); device $deviceText"
    $summary.device = $deployment.device
    $summary.applicationRevision = $deployment.applicationRevision

    $clip = (Resolve-Path -LiteralPath $ClipPath).Path
    $clipSha256 = Get-MaviSha256 -Path $clip
    $summary.clip = [ordered]@{ fileName = [IO.Path]::GetFileName($clip); sha256 = $clipSha256; sizeBytes = (Get-Item -LiteralPath $clip).Length }
    $camera = @(Invoke-MaviApi -Path "/api/cameras" | ForEach-Object { $_ }) | Where-Object { [string]$_.code -eq $CameraCode } | Select-Object -First 1
    Add-MaviSmokeStep "Camera" ($null -ne $camera) "$CameraCode"

    # Import (multipart, as the UI sends it). A clip imported before answers 409 with its
    # existing id; the smoke test then reuses that video, so a rerun is meaningful.
    $form = New-Object System.Net.Http.MultipartFormDataContent
    $form.Add((New-Object System.Net.Http.StringContent([string]$camera.id)), "cameraId")
    $form.Add((New-Object System.Net.Http.StringContent($RecordingStartLocal)), "recordingStartLocal")
    $stream = [IO.File]::OpenRead($clip)
    try {
        $fileContent = New-Object System.Net.Http.StreamContent($stream)
        $fileContent.Headers.ContentType = New-Object System.Net.Http.Headers.MediaTypeHeaderValue("video/mp4")
        $form.Add($fileContent, "file", [IO.Path]::GetFileName($clip))
        $response = $client.PostAsync("$apiBaseUrl/api/videos/import", $form).GetAwaiter().GetResult()
        $text = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
    }
    finally { $stream.Dispose() }
    $status = [int]$response.StatusCode
    $payload = if ($text) { $text | ConvertFrom-Json } else { $null }
    $videoId = if ($status -eq 201) { [string]$payload.id } elseif ($status -eq 409 -and $payload.PSObject.Properties["videoAssetId"]) { [string]$payload.videoAssetId } else { $null }
    Add-MaviSmokeStep "Import" (-not [string]::IsNullOrWhiteSpace($videoId)) "HTTP $status; video $videoId"
    $summary.videoAssetId = $videoId

    $video = Invoke-MaviApi -Path "/api/videos/$videoId"
    if ([string]$video.processingStatus -in @("NotQueued", "Failed")) {
        [void](Invoke-MaviApi -Method Post -Path "/api/videos/$videoId/process")
    }
    $deadline = [DateTime]::UtcNow.AddMinutes($TimeoutMinutes)
    $started = [DateTime]::UtcNow
    do {
        Start-Sleep -Seconds 10
        $video = Invoke-MaviApi -Path "/api/videos/$videoId"
        Write-Host ("  processing: {0} ({1:n0} s)" -f $video.processingStatus, ([DateTime]::UtcNow - $started).TotalSeconds)
    } while ([string]$video.processingStatus -in @("Queued", "Processing") -and [DateTime]::UtcNow -lt $deadline)
    Add-MaviSmokeStep "Processing" ([string]$video.processingStatus -eq "Processed") "status $($video.processingStatus) after $([int]([DateTime]::UtcNow - $started).TotalSeconds) s"
    $summary.processingSeconds = [int]([DateTime]::UtcNow - $started).TotalSeconds

    $search = Invoke-MaviApi -Path "/api/tracks?videoAssetId=$videoId&limit=50"
    $items = @($search.items)
    Add-MaviSmokeStep "Track search" ($items.Count -gt 0) "$($items.Count) Track(s) on the first page"
    $summary.firstPageTracks = $items.Count
    $summary.objectClasses = @($items | Group-Object objectClass | ForEach-Object { "$($_.Name)=$($_.Count)" })

    $detail = Invoke-MaviApi -Path "/api/tracks/$($items[0].id)"
    Add-MaviSmokeStep "Track review" ([string]$detail.id -eq [string]$items[0].id) "Track $($detail.id) detail read back"

    $passed = $true
}
catch {
    $failure = $_.Exception.Message
    Write-Host "SMOKE TEST FAILED: $failure" -ForegroundColor Red
}
finally {
    $client.Dispose()
    $result = [ordered]@{
        schemaVersion = "mavi-poc-smoke-result-v1"
        profile = Get-MaviPocProfile
        productionQualified = $false
        evidenceClass = "Development"
        passed = $passed
        failure = $failure
        apiBaseUrl = $apiBaseUrl
        completedAtUtc = [DateTimeOffset]::UtcNow.ToString("O")
        summary = $summary
        steps = $steps.ToArray()
        transcript = $transcriptPath
    }
    Write-MaviJson -Value $result -Path $resultPath -Depth 8
    Write-Host "Result: $resultPath"
    Stop-Transcript | Out-Null
}
if (-not $passed) { exit 1 }
exit 0
