param(
    [Parameter(Mandatory = $true)]
    [string]$BaseUrl,

    [Parameter(Mandatory = $true)]
    [Guid]$CameraId,

    [Parameter(Mandatory = $true)]
    [string]$RecordingStartLocal,

    [Parameter(Mandatory = $true)]
    [string]$VideoPath,

    [string]$WebConfigPath
)

$ErrorActionPreference = "Stop"

$minimumQualificationBytes = 30MB
$maximumVideoBytes = 3GB
$multipartOverheadBytes = 1MB
$maximumRequestBytes = $maximumVideoBytes + $multipartOverheadBytes

function Assert-Status {
    param(
        [Parameter(Mandatory = $true)]$Response,
        [Parameter(Mandatory = $true)][int[]]$Allowed,
        [Parameter(Mandatory = $true)][string]$Operation
    )

    if ($Allowed -notcontains [int]$Response.StatusCode) {
        throw "$Operation returned HTTP $($Response.StatusCode); expected one of: $($Allowed -join ', ')."
    }
}

$uri = $BaseUrl.TrimEnd('/')

if (-not (Test-Path -LiteralPath $VideoPath -PathType Leaf)) {
    throw "Qualification video was not found: $VideoPath"
}

$file = Get-Item -LiteralPath $VideoPath
if ($file.Length -le $minimumQualificationBytes) {
    throw "Qualification video must exceed 30 MiB. Actual bytes: $($file.Length)."
}
if ($file.Length -gt $maximumVideoBytes) {
    throw "Qualification video exceeds the supported 3 GiB Task-15 limit."
}

if ($WebConfigPath) {
    if (-not (Test-Path -LiteralPath $WebConfigPath -PathType Leaf)) {
        throw "web.config was not found: $WebConfigPath"
    }

    [xml]$webConfig = Get-Content -LiteralPath $WebConfigPath -Raw
    $value = $webConfig.configuration.location.'system.webServer'.security.requestFiltering.requestLimits.maxAllowedContentLength
    if (-not $value) {
        throw "IIS maxAllowedContentLength is missing from web.config."
    }

    [uint64]$iisLimit = $value
    if ($iisLimit -lt $maximumRequestBytes) {
        throw "IIS limit $iisLimit is below the Task-15 application request ceiling $maximumRequestBytes."
    }
    if ($iisLimit -gt [uint32]::MaxValue) {
        throw "IIS maxAllowedContentLength exceeds its unsigned 32-bit ceiling."
    }
}

Write-Host "Checking same-origin API health..."
$health = Invoke-WebRequest -Uri "$uri/api/health" -UseBasicParsing
Assert-Status -Response $health -Allowed @(200) -Operation "GET /api/health"
if (($health.Headers.'Content-Type' -join ';') -notmatch 'application/json') {
    throw "GET /api/health did not return JSON."
}

Write-Host "Checking API-safe SPA fallback..."
try {
    $unknownApi = Invoke-WebRequest -Uri "$uri/api/task15-host-qualification-unknown" -UseBasicParsing
    $unknownStatus = [int]$unknownApi.StatusCode
} catch {
    if ($_.Exception.Response) {
        $unknownStatus = [int]$_.Exception.Response.StatusCode
    } else {
        throw
    }
}
if ($unknownStatus -ne 404) {
    throw "Unknown API path returned HTTP $unknownStatus; expected 404."
}

$testVideoId = [Guid]::NewGuid()
$deepLink = Invoke-WebRequest -Uri "$uri/processing/$testVideoId" -UseBasicParsing
Assert-Status -Response $deepLink -Allowed @(200) -Operation "SPA processing deep link"
if ($deepLink.Content -notmatch '<div id="root"></div>') {
    throw "Processing deep link did not return the React entry document."
}

Write-Host "Posting representative multipart video larger than the IIS default limit..."
$curlArgs = @(
    '--silent',
    '--show-error',
    '--write-out', '%{http_code}',
    '--output', "$env:TEMP\mavi-task15-upload-response.json",
    '--form', "cameraId=$($CameraId.ToString('D'))",
    '--form', "recordingStartLocal=$RecordingStartLocal",
    '--form', "file=@$VideoPath;type=video/mp4",
    "$uri/api/videos/import"
)

$httpCodeText = & curl.exe @curlArgs
if ($LASTEXITCODE -ne 0) {
    throw "curl.exe failed while posting the qualification video."
}

[int]$httpCode = $httpCodeText
if ($httpCode -eq 413) {
    throw "IIS or ASP.NET Core rejected a supported >30 MiB request with HTTP 413."
}
if ($httpCode -eq 404) {
    throw "Multipart import did not reach the MAVI API; HTTP 404 was returned."
}
if ($httpCode -notin @(201, 409)) {
    $body = Get-Content -LiteralPath "$env:TEMP\mavi-task15-upload-response.json" -Raw -ErrorAction SilentlyContinue
    throw "Qualification import returned HTTP $httpCode. Response: $body"
}

if ($httpCode -eq 409) {
    $problem = Get-Content -LiteralPath "$env:TEMP\mavi-task15-upload-response.json" -Raw | ConvertFrom-Json
    if ($problem.code -ne 'video_duplicate' -or -not $problem.videoAssetId) {
        throw "HTTP 409 did not provide the recoverable video_duplicate + videoAssetId contract."
    }
}

Write-Host "Task-15 Windows production-host qualification PASSED."
