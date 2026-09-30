<#
.SYNOPSIS
    Acquire the R-5-permitted S2c first-pass candidate artefacts into the controlled store.

.DESCRIPTION
    Slice A / SA-B2 acquisition for events msr-person-attributes-2026-01 and
    msr-vehicle-attributes-2026-01. Governing record:
    docs/qualification/stage2-s2c/real-qualification-execution-record.md (§4.3.2, §4.3.8, §4.3.9).

    Acquisition and hashing only. The script never executes, loads, trains, tunes, scores or
    selects a model. It downloads exactly the six families that R-5 recorded as
    PERMITTED_FOR_EVALUATION (SigLIP 2 base patch16-224, DINOv2 ViT-S/14, Intel OMZ 0230, 0234,
    0238 and 0042). The catalog is fixed in this file and cannot be widened or filtered from the
    command line. DINOv3 (NOT_PERMITTED; gated access NOT APPROVED) and the REVIEW_PENDING
    candidates (Awiros, torchvision MobileNetV3-Small, VTFPAR++) are listed only as BLOCKED
    manifest entries and have no source URL here.

    Every file:
    - is fetched from an immutable revision-specific HTTPS URL (every redirect hop must be HTTPS
      to an allow-listed host; no credentials or authorization headers are ever sent);
    - is written to "<name>.partial" and renamed only after its size and every publisher
      checksum verify (SHA-256 for the HF weights, git blob SHA-1 for the HF configuration
      files, SHA-384 for the OMZ files, plus the exact published byte size);
    - resumes an interrupted ".partial" with "Range: bytes=<length>-": bytes are appended only
      to an HTTP 206 whose Content-Range starts exactly at that length and whose total equals
      the expected size; a 200 answer to a Range request never appends (its full body replaces
      the partial as a fresh transfer); a 416 fails closed unless the partial is already
      complete; transient transport errors (resets, TLS failures, timeouts, HTTP
      408/429/500/502/503/504) are retried at most 5 times (2, 4, 8, 16 s back-off) and the
      partial is kept for the next run; any other failure, and every identity or integrity
      failure, is final and never promotes the partial;
    - gets its MAVI SHA-256 computed locally with Get-FileHash.

    Re-running is safe: a present file that verifies is recorded ALREADY_PRESENT_VERIFIED and not
    downloaded again; a present file that differs is FAILED and left untouched.

    Outputs under -Root: acquisition-manifest.json and acquisition-summary.txt (a previous
    manifest that differs is moved to history\ first). Exit code 0 = every permitted file
    acquired or verified; 1 = at least one file failed; 2 = refused before any download.

.PARAMETER Root
    Controlled component/evidence store. Must resolve outside every Git worktree.

.PARAMETER DryRun
    Print the plan (families, URLs, target paths, expected checks). No network, no writes.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File tools\qualification\model_selection\acquire_s2c_candidates.ps1 -Root "D:\MAVI-Controlled\Models\S2c\2026-01"
#>
[CmdletBinding()]
param(
    [string]$Root = 'D:\MAVI-Controlled\Models\S2c\2026-01',
    [switch]$DryRun
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$script:MaviAcquisitionSchema = 'mavi-s2c-candidate-acquisition-manifest-v1'
$script:MaviAcquisitionScriptVersion = '1.1.0'
$script:MaviAllowedHostSuffixes = @('huggingface.co', 'hf.co', 'storage.openvinotoolkit.org')

function Get-MaviS2cPermittedCatalog {
    <# The only acquisition catalog. Values are copied from the execution record §4.3.2 and the
       publisher metadata retrieved at the recorded immutable revisions; nothing is resolved at
       run time. #>
    $hf = {
        param($repo, $rev, $name, $size, $sha256, $blobSha1, $role)
        [pscustomobject][ordered]@{
            name = $name; role = $role
            url = "https://huggingface.co/$repo/resolve/$rev/$name"
            expectedSize = [long]$size; publisherSha256 = $sha256; publisherSha384 = $null; publisherGitBlobSha1 = $blobSha1
        }
    }
    $omzRev = 'a6946b6d6ce42cbf4278df20275fab199655fc7d'
    $omz = {
        param($model, $ext, $size, $sha384)
        [pscustomobject][ordered]@{
            name = "FP32/$model.$ext"; role = $(if ($ext -eq 'xml') { 'openvino-ir-topology' } else { 'openvino-ir-weights' })
            url = "https://storage.openvinotoolkit.org/repositories/open_model_zoo/2023.0/models_bin/1/$model/FP32/$model.$ext"
            expectedSize = [long]$size; publisherSha256 = $null; publisherSha384 = $sha384; publisherGitBlobSha1 = $null
        }
    }
    $sigRev = '75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2'
    $dinoRev = 'ed25f3a31f01632728cabb09d1542f84ab7b0056'
    @(
        [pscustomobject][ordered]@{
            family = 'dinov2-small'; candidateIds = @('PC-2B', 'PO-2B', 'VC-1B')
            sourceRepository = 'https://huggingface.co/facebook/dinov2-small'; revision = $dinoRev
            revisionCheck = 'x-repo-commit'
            files = @(
                (& $hf 'facebook/dinov2-small' $dinoRev 'config.json' 547 $null '5664b325e6258d3960fad8c4c1cff958f3cc2272' 'configuration'),
                (& $hf 'facebook/dinov2-small' $dinoRev 'model.safetensors' 88249960 'ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1' $null 'weights'),
                (& $hf 'facebook/dinov2-small' $dinoRev 'preprocessor_config.json' 436 $null 'ff5b47c2edcd1d3556d63c01a65d93b58b9efce1' 'preprocessing')
            )
        },
        [pscustomobject][ordered]@{
            family = 'omz-person-attributes-recognition-crossroad-0230'; candidateIds = @('PC-7')
            sourceRepository = 'https://github.com/openvinotoolkit/open_model_zoo (models/intel/person-attributes-recognition-crossroad-0230/model.yml)'; revision = $omzRev
            revisionCheck = 'none'
            files = @(
                (& $omz 'person-attributes-recognition-crossroad-0230' 'bin' 2939232 'a78e7374128c8f6d7b1ff1b73859d418fae01a4c23284c60acf86d99750a1706985d2e7124a6e2f93e8e0d650f1b9ceb'),
                (& $omz 'person-attributes-recognition-crossroad-0230' 'xml' 183946 'd16a415f184cdf11e8f78dfc964e337464aba5df325bf378c49d28b4d26d1eff42919963c6a279794ee6e803a78d6fd0')
            )
        },
        [pscustomobject][ordered]@{
            family = 'omz-person-attributes-recognition-crossroad-0234'; candidateIds = @('PO-6B')
            sourceRepository = 'https://github.com/openvinotoolkit/open_model_zoo (models/intel/person-attributes-recognition-crossroad-0234/model.yml)'; revision = $omzRev
            revisionCheck = 'none'
            files = @(
                (& $omz 'person-attributes-recognition-crossroad-0234' 'bin' 94040700 '81f2016b0c0b2026e52f5b50b1dbc4e9d40e9cfc2bb16a8497dc1217f50705bee0380121fad81788ada77c2ed9e1de79'),
                (& $omz 'person-attributes-recognition-crossroad-0234' 'xml' 184747 'b2a54d611670c98ebb5979bf9e32c7d0de9597229852841b34c017cd3b0fd0c6e70613577ac67140e4565977bf5e4618')
            )
        },
        [pscustomobject][ordered]@{
            family = 'omz-person-attributes-recognition-crossroad-0238'; candidateIds = @('PO-6C')
            sourceRepository = 'https://github.com/openvinotoolkit/open_model_zoo (models/intel/person-attributes-recognition-crossroad-0238/model.yml)'; revision = $omzRev
            revisionCheck = 'none'
            files = @(
                (& $omz 'person-attributes-recognition-crossroad-0238' 'bin' 87188220 '6b564a9a596d4c62c147acb59282c002e4be1cd2835dd12daa27feadaf4953f49a3565924d6b1f10f8005121c9bc8138'),
                (& $omz 'person-attributes-recognition-crossroad-0238' 'xml' 297345 '6eddf2b2ffdadfa3f7992f4e743e77c9cd2b9bced4c95e890454ceace395886373fc867241847bab7b8360a876b3541e')
            )
        },
        [pscustomobject][ordered]@{
            family = 'omz-vehicle-attributes-recognition-barrier-0042'; candidateIds = @('VC-5A')
            sourceRepository = 'https://github.com/openvinotoolkit/open_model_zoo (models/intel/vehicle-attributes-recognition-barrier-0042/model.yml)'; revision = $omzRev
            revisionCheck = 'none'
            files = @(
                (& $omz 'vehicle-attributes-recognition-barrier-0042' 'bin' 44709480 '681619d583487afc2f3d7f984f86a789d1bc531e811e4c55eb428758c8d4f1f8157567cc4afa6e20cae117266c11f024'),
                (& $omz 'vehicle-attributes-recognition-barrier-0042' 'xml' 65883 '918218981e6267a3449c7084cabe5c7c45bdb20b9e8be56c81c5b0cb34870c5baa690753c281533fbffcfc4fad154191')
            )
        },
        [pscustomobject][ordered]@{
            family = 'siglip2-base-patch16-224'; candidateIds = @('PC-1', 'PO-1', 'VC-2')
            sourceRepository = 'https://huggingface.co/google/siglip2-base-patch16-224'; revision = $sigRev
            revisionCheck = 'x-repo-commit'
            files = @(
                (& $hf 'google/siglip2-base-patch16-224' $sigRev 'config.json' 253 $null 'c8cd2a20e58a738f44f267ae19f9568ff1095698' 'configuration'),
                (& $hf 'google/siglip2-base-patch16-224' $sigRev 'model.safetensors' 1500800904 '612923381c76ec5a9bed335d1c48827e3f2e506ac31b044b63b2031fadee6a0b' $null 'weights'),
                (& $hf 'google/siglip2-base-patch16-224' $sigRev 'preprocessor_config.json' 394 $null '2e52d8e8492b5c496ae04c37bfa09760469fb18b' 'preprocessing')
            )
        }
    )
}

function Get-MaviS2cBlockedFamilies {
    <# Recorded for audit only: no URL, never downloaded. #>
    @(
        [pscustomobject][ordered]@{ family = 'awiros-person-attribute-recognition'; candidateIds = @('PC-5'); status = 'BLOCKED'; reason = 'R-5 REVIEW_PENDING' },
        [pscustomobject][ordered]@{ family = 'dinov3-vits16-pretrain-lvd1689m'; candidateIds = @('PC-2A', 'PO-2A', 'VC-1A'); status = 'BLOCKED'; reason = 'R-5 NOT_PERMITTED_FOR_EVALUATION; gated access NOT APPROVED' },
        [pscustomobject][ordered]@{ family = 'torchvision-mobilenet-v3-small'; candidateIds = @('PC-8', 'PO-7', 'VC-4A'); status = 'BLOCKED'; reason = 'R-5 REVIEW_PENDING' },
        [pscustomobject][ordered]@{ family = 'vtfparpp-mars'; candidateIds = @('PC-9'); status = 'BLOCKED'; reason = 'R-5 REVIEW_PENDING; checkpoint file not identifiable' }
    )
}

function Test-MaviS2cCatalog {
    param([Parameter(Mandatory)] [object[]]$Catalog)
    $paths = @{}; $urls = @{}
    $families = @($Catalog | ForEach-Object { $_.family })
    for ($i = 1; $i -lt $families.Count; $i++) {
        if ([string]::CompareOrdinal($families[$i - 1], $families[$i]) -ge 0) { throw 'catalog: families must be unique and in ordinal order' }
    }
    foreach ($unit in $Catalog) {
        $names = @($unit.files | ForEach-Object { $_.name })
        for ($i = 1; $i -lt $names.Count; $i++) {
            if ([string]::CompareOrdinal($names[$i - 1], $names[$i]) -ge 0) { throw "catalog: files of $($unit.family) must be unique and in ordinal order" }
        }
        if ($unit.revision -notmatch '^[0-9a-f]{40}$') { throw "catalog: revision is not an immutable 40-hex commit for $($unit.family)" }
        if ($unit.family -notmatch '^[a-z0-9][a-z0-9-]*$') { throw "catalog: invalid family id $($unit.family)" }
        if (@($unit.files).Count -lt 1) { throw "catalog: no files for $($unit.family)" }
        foreach ($f in $unit.files) {
            $uri = [Uri]$f.url
            if ($uri.Scheme -ne 'https') { throw "catalog: non-HTTPS url $($f.url)" }
            if (-not (Test-MaviAllowedHost $uri.Host)) { throw "catalog: host not allowed $($uri.Host)" }
            if ($f.url -match '(?i)/(main|master|latest)(/|$)') { throw "catalog: floating reference in $($f.url)" }
            if ($unit.revisionCheck -eq 'x-repo-commit' -and $f.url -notlike "*/resolve/$($unit.revision)/*") { throw "catalog: url not pinned to revision $($f.url)" }
            if ($f.name -match '(^|[\\/])\.\.([\\/]|$)' -or $f.name -match '^[\\/]' -or $f.name -match ':') { throw "catalog: unsafe file name $($f.name)" }
            if ($f.expectedSize -le 0) { throw "catalog: expected size missing for $($f.name)" }
            if (-not ($f.publisherSha256 -or $f.publisherSha384 -or $f.publisherGitBlobSha1)) { throw "catalog: no publisher checksum for $($f.name)" }
            $rel = "$($unit.family)/$($unit.revision)/$($f.name)"
            if ($paths.ContainsKey($rel)) { throw "catalog: duplicate path $rel" }
            if ($urls.ContainsKey($f.url)) { throw "catalog: duplicate url $($f.url)" }
            $paths[$rel] = $true; $urls[$f.url] = $true
        }
        if ($unit.family -like 'omz-*') {
            $names = @($unit.files | ForEach-Object { $_.name })
            if (-not (@($names | Where-Object { $_ -like '*.xml' }).Count -eq 1 -and @($names | Where-Object { $_ -like '*.bin' }).Count -eq 1)) {
                throw "catalog: OpenVINO IR unit $($unit.family) must contain exactly one .xml and one .bin"
            }
        }
    }
}

function Test-MaviAllowedHost {
    param([string]$HostName)
    $h = $HostName.ToLowerInvariant()
    foreach ($suffix in $script:MaviAllowedHostSuffixes) {
        if ($h -eq $suffix -or $h.EndsWith('.' + $suffix)) { return $true }
    }
    return $false
}

function Get-MaviGitWorktreeAncestor {
    <# Returns the first ancestor (inclusive) that holds a .git entry, else $null. #>
    param([Parameter(Mandatory)] [string]$Path)
    $current = [IO.Path]::GetFullPath($Path)
    while ($current) {
        if (Test-Path -LiteralPath (Join-Path $current '.git')) { return $current }
        $parent = [IO.Path]::GetDirectoryName($current.TrimEnd('\', '/'))
        if (-not $parent -or $parent -eq $current) { break }
        $current = $parent
    }
    return $null
}

function Assert-MaviControlledRoot {
    param([Parameter(Mandatory)] [string]$Root, [string]$ScriptPath)
    if ([string]::IsNullOrWhiteSpace($Root)) { throw 'root: empty' }
    $full = [IO.Path]::GetFullPath($Root)
    $worktree = Get-MaviGitWorktreeAncestor -Path $full
    if ($worktree) { throw "root: '$full' is inside the Git worktree '$worktree'; refusing" }
    if ($ScriptPath) {
        $repo = Get-MaviGitWorktreeAncestor -Path ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($ScriptPath)))
        if ($repo) {
            $repoFull = [IO.Path]::GetFullPath($repo).TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
            if (($full.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar).StartsWith($repoFull, [StringComparison]::OrdinalIgnoreCase)) {
                throw "root: '$full' is inside the MAVI repository '$repo'; refusing"
            }
        }
    }
    return $full
}

function Get-MaviGitBlobSha1 {
    param([Parameter(Mandatory)] [string]$Path)
    $length = (Get-Item -LiteralPath $Path).Length
    $sha1 = [Security.Cryptography.SHA1]::Create()
    try {
        $header = [Text.Encoding]::ASCII.GetBytes("blob $length`0")
        [void]$sha1.TransformBlock($header, 0, $header.Length, $null, 0)
        $stream = [IO.File]::OpenRead($Path)
        try {
            $buffer = New-Object byte[] 1048576
            while (($read = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) { [void]$sha1.TransformBlock($buffer, 0, $read, $null, 0) }
        } finally { $stream.Dispose() }
        [void]$sha1.TransformFinalBlock((New-Object byte[] 0), 0, 0)
        return (($sha1.Hash | ForEach-Object { $_.ToString('x2') }) -join '')
    } finally { $sha1.Dispose() }
}

function Test-MaviFileAgainstPublisher {
    <# Returns an ordered record of every check; ok = all applicable checks pass. #>
    param([Parameter(Mandatory)] [string]$Path, [Parameter(Mandatory)] $File)
    $size = (Get-Item -LiteralPath $Path).Length
    $sha256 = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    $cmp = [ordered]@{ size = 'MATCH'; sha256 = 'NO_PUBLISHER_VALUE'; sha384 = 'NO_PUBLISHER_VALUE'; gitBlobSha1 = 'NO_PUBLISHER_VALUE' }
    $problems = New-Object System.Collections.Generic.List[string]
    if ($size -le 0) { $cmp.size = 'ZERO_BYTES'; $problems.Add('zero-byte file') }
    elseif ($size -ne $File.expectedSize) { $cmp.size = 'MISMATCH'; $problems.Add("size $size != expected $($File.expectedSize)") }
    if ($File.publisherSha256) {
        if ($sha256 -eq $File.publisherSha256) { $cmp.sha256 = 'MATCH' } else { $cmp.sha256 = 'MISMATCH'; $problems.Add('publisher SHA-256 mismatch') }
    }
    if ($File.publisherSha384) {
        $h = (Get-FileHash -LiteralPath $Path -Algorithm SHA384).Hash.ToLowerInvariant()
        if ($h -eq $File.publisherSha384) { $cmp.sha384 = 'MATCH' } else { $cmp.sha384 = 'MISMATCH'; $problems.Add('publisher SHA-384 mismatch') }
    }
    if ($File.publisherGitBlobSha1) {
        $h = Get-MaviGitBlobSha1 -Path $Path
        if ($h -eq $File.publisherGitBlobSha1) { $cmp.gitBlobSha1 = 'MATCH' } else { $cmp.gitBlobSha1 = 'MISMATCH'; $problems.Add('publisher git blob SHA-1 mismatch') }
    }
    [pscustomobject]@{ ok = ($problems.Count -eq 0); size = [long]$size; sha256 = $sha256; comparison = $cmp; problems = $problems.ToArray() }
}

function Get-MaviTransientError {
    <# A transfer failure the retry loop may retry: transport resets, TLS failures, timeouts,
       and HTTP 408/429/500/502/503/504. Everything else (policy, identity, integrity) is final. #>
    param([Parameter(Mandatory)] [string]$Message)
    return (New-Object System.Exception("TRANSIENT: $Message"))
}

function Test-MaviTransientError {
    param($ErrorRecord)
    return ($ErrorRecord.Exception.Message -like 'TRANSIENT: *')
}

function New-MaviHttpRequest {
    <# GET for one hop; a resume sends "Range: bytes=<RangeStart>-". No other header is set. #>
    param([Parameter(Mandatory)] [Uri]$Uri, [long]$RangeStart = 0)
    Add-Type -AssemblyName System.Net.Http
    $request = New-Object System.Net.Http.HttpRequestMessage([System.Net.Http.HttpMethod]::Get, $Uri)
    if ($RangeStart -gt 0) { $request.Headers.Range = [System.Net.Http.Headers.RangeHeaderValue]::Parse("bytes=$RangeStart-") }
    return $request
}

function Invoke-MaviHttpsTransport {
    <# Default transport: HTTPS only, allow-listed hosts on every hop, no credentials.
       RangeStart > 0 sends "Range: bytes=<RangeStart>-". For HTTP 200/206 it calls
       OpenSink(statusCode, contentRange) BEFORE reading the body; the sink validates and returns
       the stream to write to. Returns the final status code (416 is returned without a body). #>
    param([Parameter(Mandatory)] [string]$Url, [long]$RangeStart = 0, [string]$ExpectedRevision,
          [Parameter(Mandatory)] [scriptblock]$OpenSink)
    Add-Type -AssemblyName System.Net.Http
    try { [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12 } catch { }
    $handler = New-Object System.Net.Http.HttpClientHandler
    $handler.AllowAutoRedirect = $false
    $handler.UseDefaultCredentials = $false
    $handler.Credentials = $null
    $client = New-Object System.Net.Http.HttpClient($handler)
    $client.Timeout = [TimeSpan]::FromHours(3)
    try {
        $uri = [Uri]$Url
        for ($hop = 0; $hop -le 8; $hop++) {
            if ($uri.Scheme -ne 'https') { throw "refusing non-HTTPS hop $uri" }
            if (-not (Test-MaviAllowedHost $uri.Host)) { throw "refusing hop to non-allow-listed host $($uri.Host)" }
            $request = New-MaviHttpRequest -Uri $uri -RangeStart $RangeStart
            try {
                $response = $client.SendAsync($request, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
            } catch { throw (Get-MaviTransientError "connection to $($uri.Host) failed: $($_.Exception.Message)") }
            try {
                if ($hop -eq 0 -and $ExpectedRevision) {
                    $values = $null
                    if ($response.Headers.TryGetValues('X-Repo-Commit', [ref]$values)) {
                        $commit = (@($values) | Select-Object -First 1)
                        if ($commit -ne $ExpectedRevision) { throw "server revision $commit != pinned $ExpectedRevision" }
                    }
                }
                $code = [int]$response.StatusCode
                if ($code -ge 300 -and $code -lt 400) {
                    if (-not $response.Headers.Location) { throw "redirect without Location (HTTP $code)" }
                    $uri = New-Object Uri($uri, $response.Headers.Location)
                    continue
                }
                if ($code -eq 416) { return 416 }
                if (@(408, 429, 500, 502, 503, 504) -contains $code) { throw (Get-MaviTransientError "HTTP $code from $($uri.Host)") }
                if ($code -ne 200 -and $code -ne 206) { throw "HTTP $code from $($uri.Host)" }
                $contentRange = $null
                if ($response.Content.Headers.ContentRange) { $contentRange = $response.Content.Headers.ContentRange.ToString() }
                $sink = & $OpenSink $code $contentRange
                try {
                    try {
                        $source = $response.Content.ReadAsStreamAsync().GetAwaiter().GetResult()
                        try { $source.CopyTo($sink, 1048576) } finally { $source.Dispose() }
                    } catch { throw (Get-MaviTransientError "transfer from $($uri.Host) interrupted: $($_.Exception.Message)") }
                } finally { $sink.Flush(); $sink.Dispose() }
                return $code
            } finally { $response.Dispose() }
        }
        throw 'too many redirects'
    } finally { $client.Dispose(); $handler.Dispose() }
}

function Resolve-MaviContentRange {
    <# Validates a 206 "bytes <start>-<end>/<total|*>" header against the requested offset. #>
    param([string]$ContentRange, [long]$Offset, [long]$ExpectedSize)
    if (-not $ContentRange -or $ContentRange -notmatch '^bytes (\d+)-(\d+)/(\d+|\*)$') { throw "malformed Content-Range '$ContentRange'" }
    $first = [long]$Matches[1]; $last = [long]$Matches[2]
    if ($first -ne $Offset) { throw "Content-Range starts at $first, requested $Offset" }
    if ($last -lt $first -or $last -ge $ExpectedSize) { throw "Content-Range end $last outside expected size $ExpectedSize" }
    if ($Matches[3] -ne '*' -and [long]$Matches[3] -ne $ExpectedSize) { throw "Content-Range total $($Matches[3]) != expected size $ExpectedSize" }
}

function Invoke-MaviResumableTransfer {
    <# Brings "<target>.partial" to its expected size, resuming from its current length.
       Bounded retry of transient failures only; partial bytes are kept across failures. #>
    param([Parameter(Mandatory)] [string]$Partial, [Parameter(Mandatory)] $File, [string]$ExpectedRevision,
          [Parameter(Mandatory)] [scriptblock]$Transport, [Parameter(Mandatory)] [scriptblock]$Sleep,
          [Parameter(Mandatory)] [hashtable]$State, [int]$MaxAttempts = 5)
    # $State (attempts, resumedFromBytes) is owned by the caller so it survives a thrown failure.
    $State.attempts = 0; $State.resumedFromBytes = $null
    for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
        $length = 0L
        if (Test-Path -LiteralPath $Partial) { $length = (Get-Item -LiteralPath $Partial).Length }
        if ($length -gt $File.expectedSize) { throw "partial holds $length bytes, more than expected $($File.expectedSize); retained for diagnosis" }
        if ($length -eq $File.expectedSize) { break }
        if ($length -eq 0 -and (Test-Path -LiteralPath $Partial)) { Remove-Item -LiteralPath $Partial -Force }
        if ($length -gt 0 -and $null -eq $State.resumedFromBytes) { $State.resumedFromBytes = $length }
        $State.attempts = $attempt
        # The sink runs inside the transport call; it reads these mvi* variables by dynamic scope.
        $mviRestart = "$Partial.restart"
        if (Test-Path -LiteralPath $mviRestart) { Remove-Item -LiteralPath $mviRestart -Force }
        $mviExpected = $File.expectedSize; $mviLength = $length; $mviPartial = $Partial
        $openSink = {
            param([int]$StatusCode, [string]$ContentRange)
            if ($StatusCode -eq 206) {
                if ($mviLength -eq 0) { throw 'HTTP 206 to a request without Range' }
                Resolve-MaviContentRange -ContentRange $ContentRange -Offset $mviLength -ExpectedSize $mviExpected
                $stream = [IO.File]::Open($mviPartial, [IO.FileMode]::Append, [IO.FileAccess]::Write, [IO.FileShare]::None)
                if ($stream.Position -ne $mviLength) { $stream.Dispose(); throw 'partial length changed during resume' }
                return $stream
            }
            if ($StatusCode -eq 200 -and $mviLength -eq 0) {
                return [IO.File]::Open($mviPartial, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            }
            if ($StatusCode -eq 200) {
                # Server ignored the Range: never append a full body onto partial bytes.
                return [IO.File]::Open($mviRestart, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
            }
            throw "unexpected HTTP $StatusCode"
        }
        try {
            $code = & $Transport -Url $File.url -RangeStart $length -ExpectedRevision $ExpectedRevision -OpenSink $openSink
            if ($code -eq 416) {
                $now = 0L
                if (Test-Path -LiteralPath $Partial) { $now = (Get-Item -LiteralPath $Partial).Length }
                if ($now -ne $File.expectedSize) { throw "HTTP 416 for offset $length with partial of $now bytes (expected $($File.expectedSize))" }
                break
            }
            if (Test-Path -LiteralPath $mviRestart) {
                # A complete 200 body replaces the superseded partial as a fresh transfer.
                Remove-Item -LiteralPath $Partial -Force
                [IO.File]::Move($mviRestart, $Partial)
                $State.resumedFromBytes = $null
            }
        } catch {
            if (Test-Path -LiteralPath $mviRestart) { Remove-Item -LiteralPath $mviRestart -Force }
            if (-not (Test-MaviTransientError $_)) { throw }
            if ($attempt -ge $MaxAttempts) {
                $kept = $(if (Test-Path -LiteralPath $Partial) { "partial of $((Get-Item -LiteralPath $Partial).Length) bytes retained for the next run" } else { 'no partial bytes received' })
                throw "transient failure persisted after $MaxAttempts attempts: $($_.Exception.Message); $kept"
            }
            & $Sleep ([int][Math]::Pow(2, $attempt))
        }
    }
}

function Get-MaviUtcNow { [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.fffZ') }

function Write-MaviUtf8Lf {
    param([Parameter(Mandatory)] [string]$Path, [Parameter(Mandatory)] [string]$Text)
    $normalized = ($Text -replace "`r`n", "`n").TrimEnd("`n") + "`n"
    $partial = "$Path.partial"
    [IO.File]::WriteAllText($partial, $normalized, (New-Object Text.UTF8Encoding($false)))
    if (Test-Path -LiteralPath $Path) {
        $backup = "$Path.replaced"
        [IO.File]::Replace($partial, $Path, $backup)
        Remove-Item -LiteralPath $backup -Force
    } else { [IO.File]::Move($partial, $Path) }
}

function Invoke-MaviS2cAcquisition {
    param(
        [Parameter(Mandatory)] [string]$Root,
        [object[]]$Catalog = (Get-MaviS2cPermittedCatalog),
        [scriptblock]$Transport = ${function:Invoke-MaviHttpsTransport},
        [scriptblock]$Sleep = { param([int]$Seconds) Start-Sleep -Seconds $Seconds },
        [string]$ScriptPath = $PSCommandPath,
        [switch]$DryRun
    )
    try {
        Test-MaviS2cCatalog -Catalog $Catalog
        $rootFull = Assert-MaviControlledRoot -Root $Root -ScriptPath $ScriptPath
    } catch {
        [Console]::Error.WriteLine("REFUSED: $($_.Exception.Message)")
        return 2
    }
    $units = @($Catalog)
    if ($DryRun) {
        foreach ($u in $units) {
            foreach ($f in @($u.files)) {
                Write-Host ("PLAN {0} [{1}] {2} -> {3}" -f $u.family, ($u.candidateIds -join ','), $f.url, (Join-Path $rootFull (Join-Path $u.family (Join-Path $u.revision $f.name))))
            }
        }
        foreach ($b in Get-MaviS2cBlockedFamilies) { Write-Host ("BLOCKED {0} [{1}] {2}" -f $b.family, ($b.candidateIds -join ','), $b.reason) }
        return 0
    }

    [void](New-Item -ItemType Directory -Force -Path $rootFull)
    $manifestPath = Join-Path $rootFull 'acquisition-manifest.json'
    $prior = @{}
    if (Test-Path -LiteralPath $manifestPath) {
        try {
            foreach ($a in (Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json).artifacts) {
                if ($a.localSha256) { $prior[$a.localRelativePath] = $a.localSha256 }
            }
        } catch { Write-Warning "previous manifest unreadable; ignoring it for drift checks: $($_.Exception.Message)" }
    }
    $startUtc = Get-MaviUtcNow
    $artifacts = New-Object System.Collections.Generic.List[object]
    foreach ($u in $units) {
        foreach ($f in @($u.files)) {
            $rel = "$($u.family)/$($u.revision)/$($f.name)"
            $target = Join-Path $rootFull ($rel -replace '/', [IO.Path]::DirectorySeparatorChar)
            $record = [ordered]@{
                family = $u.family; candidateIds = @($u.candidateIds); sourceRepository = $u.sourceRepository
                sourceUrl = $f.url; immutableRevision = $u.revision; fileName = $f.name; role = $f.role
                localRelativePath = $rel; byteSize = $null; expectedByteSize = $f.expectedSize; localSha256 = $null
                publisherSha256 = $f.publisherSha256; publisherSha384 = $f.publisherSha384; publisherGitBlobSha1 = $f.publisherGitBlobSha1
                hashComparison = $null; status = 'FAILED'; acquiredAtUtc = $null; error = $null
                resumedFromBytes = $null; transferAttempts = 0; partialRetained = $false
            }
            try {
                [void](New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($target)))
                if (Test-Path -LiteralPath $target) {
                    $check = Test-MaviFileAgainstPublisher -Path $target -File $f
                    $record.byteSize = $check.size; $record.localSha256 = $check.sha256; $record.hashComparison = $check.comparison
                    if (-not $check.ok) { throw "pre-existing file differs from the pinned artefact ($($check.problems -join '; ')); left untouched" }
                    if ($prior.ContainsKey($rel) -and $prior[$rel] -ne $check.sha256) { throw 'pre-existing file differs from the previous acquisition record; left untouched' }
                    $record.status = 'ALREADY_PRESENT_VERIFIED'; $record.acquiredAtUtc = Get-MaviUtcNow
                } else {
                    $partial = "$target.partial"
                    try {
                        $transfer = @{ attempts = 0; resumedFromBytes = $null }
                        try {
                            Invoke-MaviResumableTransfer -Partial $partial -File $f -Transport $Transport -Sleep $Sleep -State $transfer `
                                -ExpectedRevision $(if ($u.revisionCheck -eq 'x-repo-commit') { $u.revision } else { $null })
                        } finally {
                            $record.transferAttempts = $transfer.attempts; $record.resumedFromBytes = $transfer.resumedFromBytes
                        }
                        if (-not (Test-Path -LiteralPath $partial)) { throw 'transfer produced no file' }
                        $check = Test-MaviFileAgainstPublisher -Path $partial -File $f
                        $record.byteSize = $check.size; $record.localSha256 = $check.sha256; $record.hashComparison = $check.comparison
                        if (-not $check.ok) { throw "transferred bytes rejected ($($check.problems -join '; ')); partial retained for diagnosis, delete it to retry" }
                        if (Test-Path -LiteralPath $target) { throw 'target appeared during download; not overwriting' }
                        [IO.File]::Move($partial, $target)
                    } finally {
                        $record.partialRetained = [bool](Test-Path -LiteralPath $partial)
                    }
                    $record.status = 'ACQUIRED'; $record.acquiredAtUtc = Get-MaviUtcNow
                }
            } catch {
                $record.status = 'FAILED'; $record.error = $_.Exception.Message
            }
            $artifacts.Add([pscustomobject]$record)
            Write-Host ("{0,-26} {1} {2}" -f $record.status, $rel, $(if ($record.error) { $record.error } else { $record.localSha256 }))
        }
    }
    $endUtc = Get-MaviUtcNow
    $failed = @($artifacts | Where-Object { $_.status -eq 'FAILED' }).Count
    $scriptSha = $null
    if ($ScriptPath -and (Test-Path -LiteralPath $ScriptPath)) { $scriptSha = (Get-FileHash -LiteralPath $ScriptPath -Algorithm SHA256).Hash.ToLowerInvariant() }
    $manifest = [ordered]@{
        schema = $script:MaviAcquisitionSchema
        scriptVersion = $script:MaviAcquisitionScriptVersion
        scriptSha256 = $scriptSha
        eventIds = @('msr-person-attributes-2026-01', 'msr-vehicle-attributes-2026-01')
        eventPairId = 'msr-attributes-2026-01'
        controlledRoot = $rootFull
        acquisitionHost = [Environment]::MachineName
        acquisitionStartUtc = $startUtc
        acquisitionEndUtc = $endUtc
        overallStatus = $(if ($failed -eq 0) { 'COMPLETE' } else { 'FAILED' })
        artifacts = $artifacts.ToArray()
        blockedFamilies = @(Get-MaviS2cBlockedFamilies)
    }
    $json = $manifest | ConvertTo-Json -Depth 8
    if (Test-Path -LiteralPath $manifestPath) {
        $old = [IO.File]::ReadAllText($manifestPath)
        if ($old -ne (($json -replace "`r`n", "`n").TrimEnd("`n") + "`n")) {
            $history = Join-Path $rootFull 'history'
            [void](New-Item -ItemType Directory -Force -Path $history)
            Move-Item -LiteralPath $manifestPath -Destination (Join-Path $history ("acquisition-manifest-{0}.json" -f ([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ'))))
        }
    }
    Write-MaviUtf8Lf -Path $manifestPath -Text $json
    $manifestSha = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $lines = New-Object System.Collections.Generic.List[string]
    $lines.Add("MAVI S2c candidate acquisition summary ($($script:MaviAcquisitionSchema), script $($script:MaviAcquisitionScriptVersion))")
    $lines.Add("script SHA-256: $scriptSha")
    $lines.Add("host: $([Environment]::MachineName)  root: $rootFull")
    $lines.Add("start: $startUtc  end: $endUtc  overall: $($manifest.overallStatus)")
    $lines.Add("acquisition-manifest.json SHA-256: $manifestSha")
    foreach ($a in $artifacts) {
        $lines.Add(("{0} | {1} | {2} | size={3} | sha256={4}{5}" -f $a.status, ($a.candidateIds -join ','), $a.localRelativePath, $a.byteSize, $a.localSha256, $(if ($a.error) { " | error=$($a.error)" } else { '' })))
    }
    foreach ($b in Get-MaviS2cBlockedFamilies) { $lines.Add(("BLOCKED | {0} | {1} | {2}" -f ($b.candidateIds -join ','), $b.family, $b.reason)) }
    Write-MaviUtf8Lf -Path (Join-Path $rootFull 'acquisition-summary.txt') -Text ($lines -join "`n")
    if ($failed -gt 0) { return 1 }
    return 0
}

if ($MyInvocation.InvocationName -ne '.') {
    $code = Invoke-MaviS2cAcquisition -Root $Root -DryRun:$DryRun -ScriptPath $PSCommandPath
    exit $code
}
