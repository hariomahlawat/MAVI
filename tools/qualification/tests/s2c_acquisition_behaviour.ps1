# Behavioural tests for tools/qualification/model_selection/acquire_s2c_candidates.ps1.
# Run by test_s2c_acquisition_script.py when pwsh is available. No network: a fake transport
# serves local bytes (200/206/416, resets, HTTP errors); the production catalog is only inspected.
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version 2.0
$scriptPath = Join-Path $PSScriptRoot '..\model_selection\acquire_s2c_candidates.ps1'
. $scriptPath

$failures = New-Object System.Collections.Generic.List[string]
function Check([bool]$Condition, [string]$Name) { if (-not $Condition) { $failures.Add($Name) } }
function Sha256Hex([byte[]]$Bytes) { $h = [Security.Cryptography.SHA256]::Create(); try { (($h.ComputeHash($Bytes) | ForEach-Object { $_.ToString('x2') }) -join '') } finally { $h.Dispose() } }
function Sha384Hex([byte[]]$Bytes) { $h = [Security.Cryptography.SHA384]::Create(); try { (($h.ComputeHash($Bytes) | ForEach-Object { $_.ToString('x2') }) -join '') } finally { $h.Dispose() } }
function BlobSha1Hex([byte[]]$Bytes) {
    $h = [Security.Cryptography.SHA1]::Create()
    try { $all = [Text.Encoding]::ASCII.GetBytes("blob $($Bytes.Length)`0") + $Bytes; (($h.ComputeHash([byte[]]$all) | ForEach-Object { $_.ToString('x2') }) -join '') } finally { $h.Dispose() }
}
function NewTempRoot { $p = Join-Path ([IO.Path]::GetTempPath()) ("mavi-acq-test-" + [Guid]::NewGuid().ToString('N')); [void](New-Item -ItemType Directory -Path $p); $p }

# ---- production catalog: permitted set only, immutable, OMZ multi-file
$catalog = Get-MaviS2cPermittedCatalog
Test-MaviS2cCatalog -Catalog $catalog
$families = @($catalog | ForEach-Object { $_.family })
Check ((@($families) -join ',') -eq 'dinov2-small,omz-person-attributes-recognition-crossroad-0230,omz-person-attributes-recognition-crossroad-0234,omz-person-attributes-recognition-crossroad-0238,omz-vehicle-attributes-recognition-barrier-0042,siglip2-base-patch16-224') 'catalog: exactly the six permitted families'
$ids = @($catalog | ForEach-Object { $_.candidateIds } | Sort-Object)
Check (($ids -join ',') -eq 'PC-1,PC-2B,PC-7,PO-1,PO-2B,PO-6B,PO-6C,VC-1B,VC-2,VC-5A') 'catalog: exactly the permitted candidate ids'
$text = Get-Content -LiteralPath $scriptPath -Raw
foreach ($u in $catalog) { foreach ($f in $u.files) {
    Check ($f.url -like 'https://*') "https only: $($f.url)"
    Check ($f.url -notmatch '(?i)dinov3|awiros|mobilenet|vtfpar') "no prohibited url: $($f.url)"
    Check ($f.url -notmatch '(?i)/(main|master|latest)/') "no floating ref: $($f.url)"
} }
foreach ($u in @($catalog | Where-Object { $_.family -like 'omz-*' })) {
    Check (@($u.files).Count -eq 2 -and ($u.files | Where-Object { $_.name -like 'FP32/*.xml' }) -and ($u.files | Where-Object { $_.name -like 'FP32/*.bin' })) "OMZ xml+bin: $($u.family)"
    Check (@($u.files | Where-Object { $_.publisherSha384 -match '^[0-9a-f]{96}$' -and -not $_.publisherSha256 }).Count -eq 2) "OMZ SHA-384 only: $($u.family)"
}
$sig = $catalog | Where-Object { $_.family -eq 'siglip2-base-patch16-224' }
Check (($sig.files | Where-Object { $_.name -eq 'model.safetensors' }).publisherSha256 -eq '612923381c76ec5a9bed335d1c48827e3f2e506ac31b044b63b2031fadee6a0b') 'SigLIP 2 publisher SHA-256 wired'
$dino = $catalog | Where-Object { $_.family -eq 'dinov2-small' }
Check (($dino.files | Where-Object { $_.name -eq 'model.safetensors' }).publisherSha256 -eq 'ae1e99fcefd534ed978cdeb8326f08030c96e28b7a81ffcbc98a857c84d14be1') 'DINOv2 publisher SHA-256 wired'
Check ((($sig.candidateIds) -join ',') -eq 'PC-1,PO-1,VC-2' -and (($dino.candidateIds) -join ',') -eq 'PC-2B,PO-2B,VC-1B') 'shared artefacts list every candidate id once'
Check ($text -notmatch '(?i)Bearer|HF_TOKEN|HUGGING_FACE|DefaultRequestHeaders|Headers\.Add|Headers\.Authorization|-Credential\b|Get-Credential') 'no credential or header injection in script'
Check (@(Get-MaviS2cBlockedFamilies | Where-Object { $_.PSObject.Properties.Name -contains 'url' }).Count -eq 0) 'blocked families carry no url'
Check (-not ((Get-Command $scriptPath).Parameters.Keys -contains 'Catalog')) 'CLI cannot supply a catalog'

# ---- catalog validation refuses unsafe entries
function CatalogRefused($mutate) {
    $c = @(Get-MaviS2cPermittedCatalog); & $mutate $c
    try { Test-MaviS2cCatalog -Catalog $c; return $false } catch { return $true }
}
Check (CatalogRefused { param($c) $c[0].files[0].url = $c[0].files[0].url -replace '^https', 'http' }) 'refuses http url'
Check (CatalogRefused { param($c) $c[5].files[1].url = 'https://huggingface.co/google/siglip2-base-patch16-224/resolve/main/model.safetensors' }) 'refuses floating main'
Check (CatalogRefused { param($c) $c[0].revision = 'main' }) 'refuses non-commit revision'
Check (CatalogRefused { param($c) $c[1].files = @($c[1].files[0]) }) 'refuses OMZ unit without xml'
Check (CatalogRefused { param($c) $c[0].files[0].url = 'https://evil.example.com/x' }) 'refuses non-allow-listed host'
Check (-not (Test-MaviAllowedHost 'huggingface.co.evil.com')) 'host suffix is not a substring match'
Check ((Test-MaviAllowedHost 'cas-bridge.xethub.hf.co') -and (Test-MaviAllowedHost 'storage.openvinotoolkit.org')) 'CDN hosts allowed'

# ---- synthetic acquisition catalog + fake transport (no network)
$weightsBytes = [byte[]](0..63 | ForEach-Object { [byte](($_ * 7 + 3) % 256) })
$payload = @{
    'https://huggingface.co/x/resolve/0000000000000000000000000000000000000001/model.safetensors' = $weightsBytes
    'https://huggingface.co/x/resolve/0000000000000000000000000000000000000001/config.json' = [Text.Encoding]::UTF8.GetBytes('{"a":1}')
    'https://storage.openvinotoolkit.org/x/FP32/m.bin' = [Text.Encoding]::UTF8.GetBytes('ir-bin')
    'https://storage.openvinotoolkit.org/x/FP32/m.xml' = [Text.Encoding]::UTF8.GetBytes('<ir/>')
}
$weightsUrl = 'https://huggingface.co/x/resolve/0000000000000000000000000000000000000001/model.safetensors'
function FakeCatalog([hashtable]$over = @{}) {
    $w = $payload[$weightsUrl]
    $cfg = $payload['https://huggingface.co/x/resolve/0000000000000000000000000000000000000001/config.json']
    $bin = $payload['https://storage.openvinotoolkit.org/x/FP32/m.bin']; $xml = $payload['https://storage.openvinotoolkit.org/x/FP32/m.xml']
    @(
        [pscustomobject]@{ family = 'hf-test'; candidateIds = @('PC-1', 'VC-2'); sourceRepository = 'https://huggingface.co/x'; revision = '0000000000000000000000000000000000000001'; revisionCheck = 'x-repo-commit'
            files = @(
                [pscustomobject]@{ name = 'config.json'; role = 'configuration'; url = 'https://huggingface.co/x/resolve/0000000000000000000000000000000000000001/config.json'; expectedSize = [long]$cfg.Length; publisherSha256 = $null; publisherSha384 = $null; publisherGitBlobSha1 = (BlobSha1Hex $cfg) },
                [pscustomobject]@{ name = 'model.safetensors'; role = 'weights'; url = $weightsUrl; expectedSize = [long]$(if ($over.ContainsKey('size')) { $over.size } else { $w.Length }); publisherSha256 = $(if ($over.ContainsKey('sha')) { $over.sha } else { Sha256Hex $w }); publisherSha384 = $null; publisherGitBlobSha1 = $null }
            ) },
        [pscustomobject]@{ family = 'omz-test'; candidateIds = @('PC-7'); sourceRepository = 'omz'; revision = 'a6946b6d6ce42cbf4278df20275fab199655fc7d'; revisionCheck = 'none'
            files = @(
                [pscustomobject]@{ name = 'FP32/m.bin'; role = 'openvino-ir-weights'; url = 'https://storage.openvinotoolkit.org/x/FP32/m.bin'; expectedSize = [long]$bin.Length; publisherSha256 = $null; publisherSha384 = (Sha384Hex $bin); publisherGitBlobSha1 = $null },
                [pscustomobject]@{ name = 'FP32/m.xml'; role = 'openvino-ir-topology'; url = 'https://storage.openvinotoolkit.org/x/FP32/m.xml'; expectedSize = [long]$xml.Length; publisherSha256 = $null; publisherSha384 = (Sha384Hex $xml); publisherGitBlobSha1 = $null }
            ) }
    )
}

# Fake server behaviour, applied to the weights URL only unless noted.
function ResetServer { $script:srv = @{ calls = @{}; ranges = New-Object System.Collections.Generic.List[long]; sleeps = New-Object System.Collections.Generic.List[int]
    ignoreRange = $false; badStart = $false; badTotal = $false; return416 = $false; alwaysTransient = $false; http = $null; cutOnce = 0; downAfterCut = $false; emptyBody = $false } }
ResetServer
$fakeTransport = {
    param($Url, [long]$RangeStart, $ExpectedRevision, $OpenSink)
    $srv = $script:srv
    $srv.calls[$Url] = 1 + $(if ($srv.calls.ContainsKey($Url)) { $srv.calls[$Url] } else { 0 })
    $bytes = [byte[]]$payload[$Url]
    if ($Url -ne $weightsUrl) {
        if ($srv.emptyBody) { $sink = & $OpenSink 200 $null; $sink.Dispose(); return 200 }
        $sink = & $OpenSink 200 $null; try { $sink.Write($bytes, 0, $bytes.Length) } finally { $sink.Dispose() }; return 200
    }
    $srv.ranges.Add($RangeStart)
    if ($srv.alwaysTransient -or ($srv.downAfterCut -and $srv.cutOnce -eq 0)) { throw (Get-MaviTransientError 'connection reset (test)') }
    if ($srv.http) { if (@(408, 429, 500, 502, 503, 504) -contains $srv.http) { throw (Get-MaviTransientError "HTTP $($srv.http)") } else { throw "HTTP $($srv.http) from test" } }
    if ($srv.emptyBody) { $sink = & $OpenSink 200 $null; $sink.Dispose(); return 200 }
    $n = $bytes.Length
    if ($RangeStart -gt 0 -and ($srv.return416 -or $RangeStart -ge $n)) { return 416 }
    if ($RangeStart -gt 0 -and -not $srv.ignoreRange) {
        $first = $(if ($srv.badStart) { $RangeStart - 1 } else { $RangeStart })
        $total = $(if ($srv.badTotal) { $n + 1 } else { $n })
        $status = 206; $contentRange = "bytes $first-$($n - 1)/$total"; $body = [byte[]]($bytes[$first..($n - 1)])
    } else { $status = 200; $contentRange = $null; $body = $bytes }
    $sink = & $OpenSink $status $contentRange
    $limit = $body.Length
    if ($srv.cutOnce -gt 0) { $limit = [Math]::Min($limit, $srv.cutOnce) }
    try { $sink.Write($body, 0, $limit) } finally { $sink.Dispose() }
    if ($limit -lt $body.Length) { $srv.cutOnce = 0; throw (Get-MaviTransientError 'connection reset mid-body (test)') }
    return $status
}
$fakeSleep = { param([int]$Seconds) $script:srv.sleeps.Add($Seconds) }
function Manifest($root) { Get-Content -LiteralPath (Join-Path $root 'acquisition-manifest.json') -Raw | ConvertFrom-Json }
function Run($root, $cat) { Invoke-MaviS2cAcquisition -Root $root -Catalog $cat -Transport $fakeTransport -Sleep $fakeSleep -ScriptPath $scriptPath 6>$null }
function WeightsRecord($root) { (Manifest $root).artifacts | Where-Object { $_.fileName -eq 'model.safetensors' } }
function WeightsTarget($root) { Join-Path $root 'hf-test/0000000000000000000000000000000000000001/model.safetensors' }
function SeedPartial($root, [byte[]]$bytes) {
    $p = (WeightsTarget $root) + '.partial'
    [void](New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($p)))
    [IO.File]::WriteAllBytes($p, $bytes); $p
}
function SameBytes([byte[]]$a, [byte[]]$b) { if ($a.Length -ne $b.Length) { return $false }; for ($i = 0; $i -lt $a.Length; $i++) { if ($a[$i] -ne $b[$i]) { return $false } }; $true }
$prefix = [byte[]]($weightsBytes[0..9])

# 1. fresh complete acquisition
ResetServer; $root = NewTempRoot
$code = Run $root (FakeCatalog)
$m = Manifest $root; $w = WeightsRecord $root
Check ($code -eq 0) 'fresh: exit 0'
Check (@($m.artifacts | Where-Object { $_.status -eq 'ACQUIRED' }).Count -eq 4) 'fresh: 4 files ACQUIRED'
Check ((@($m.artifacts | ForEach-Object { $_.localRelativePath }) -join '|') -eq 'hf-test/0000000000000000000000000000000000000001/config.json|hf-test/0000000000000000000000000000000000000001/model.safetensors|omz-test/a6946b6d6ce42cbf4278df20275fab199655fc7d/FP32/m.bin|omz-test/a6946b6d6ce42cbf4278df20275fab199655fc7d/FP32/m.xml') 'fresh: deterministic ordering and paths'
Check (($w.candidateIds -join ',') -eq 'PC-1,VC-2') 'shared file downloaded once with all ids'
Check ($w.transferAttempts -eq 1 -and $null -eq $w.resumedFromBytes -and $w.partialRetained -eq $false) 'fresh: audit fields'
Check ((($script:srv.ranges) -join ',') -eq '0') 'fresh: no Range on a fresh transfer'
Check (($m.artifacts | Where-Object { $_.fileName -eq 'FP32/m.bin' }).hashComparison.sha384 -eq 'MATCH') 'OMZ SHA-384 compared'
Check ($null -eq ($m.artifacts | Where-Object { $_.fileName -eq 'FP32/m.bin' }).publisherSha256) 'OMZ has no invented SHA-256'
Check (($m.artifacts | Where-Object { $_.fileName -eq 'config.json' }).hashComparison.gitBlobSha1 -eq 'MATCH') 'HF config git blob SHA-1 compared'
Check (@(Get-ChildItem -LiteralPath $root -Recurse -Filter '*.partial').Count -eq 0) 'no .partial left behind after success'
Check ($m.schema -eq 'mavi-s2c-candidate-acquisition-manifest-v1' -and $m.scriptVersion -eq '1.1.0' -and $m.overallStatus -eq 'COMPLETE' -and $m.scriptSha256 -match '^[0-9a-f]{64}$') 'manifest header'
Check (@($m.blockedFamilies).Count -eq 4 -and @($m.blockedFamilies | Where-Object { $_.status -ne 'BLOCKED' }).Count -eq 0) 'blocked families recorded'
$bytes = [IO.File]::ReadAllBytes((Join-Path $root 'acquisition-manifest.json'))
Check (-not ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB) -and -not ([Text.Encoding]::UTF8.GetString($bytes).Contains("`r"))) 'manifest UTF-8 without BOM, LF only'
Check (Test-Path -LiteralPath (Join-Path $root 'acquisition-summary.txt')) 'summary written'

# 13. rerun is idempotent: known-good finals stay ALREADY_PRESENT_VERIFIED
ResetServer
$code = Run $root (FakeCatalog)
$m = Manifest $root
Check ($code -eq 0 -and $script:srv.calls.Count -eq 0) 'rerun: no transfers, exit 0'
Check (@($m.artifacts | Where-Object { $_.status -eq 'ALREADY_PRESENT_VERIFIED' }).Count -eq 4) 'rerun: ALREADY_PRESENT_VERIFIED'
Check (@(Get-ChildItem -LiteralPath (Join-Path $root 'history') -Filter 'acquisition-manifest-*.json').Count -eq 1) 'rerun: previous manifest retained in history'

# a known-good final with a stray partial beside it is left alone
[IO.File]::WriteAllBytes((WeightsTarget $root) + '.partial', [byte[]](1, 2, 3))
ResetServer
$code = Run $root (FakeCatalog)
Check ($code -eq 0 -and (WeightsRecord $root).status -eq 'ALREADY_PRESENT_VERIFIED' -and (SameBytes ([IO.File]::ReadAllBytes((WeightsTarget $root))) $weightsBytes)) 'final wins over stray partial; final untouched'
Remove-Item -LiteralPath ((WeightsTarget $root) + '.partial') -Force

# pre-existing differing final is never overwritten
[IO.File]::WriteAllBytes((WeightsTarget $root), [Text.Encoding]::UTF8.GetBytes('tampered-bytes'))
ResetServer
$code = Run $root (FakeCatalog)
$m = Manifest $root
Check ($code -eq 1 -and (WeightsRecord $root).status -eq 'FAILED' -and $m.overallStatus -eq 'FAILED') 'tampered final: FAILED'
Check ([Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes((WeightsTarget $root))) -eq 'tampered-bytes') 'tampered final: left untouched'
Remove-Item -Recurse -Force $root

# differing final present before any acquisition record exists (publisher check alone)
ResetServer; $root = NewTempRoot
[void](New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName((WeightsTarget $root))))
[IO.File]::WriteAllBytes((WeightsTarget $root), [Text.Encoding]::UTF8.GetBytes('unrelated-bytes'))
$code = Run $root (FakeCatalog)
$w = WeightsRecord $root
Check ($code -eq 1 -and $w.status -eq 'FAILED' -and $w.hashComparison.sha256 -eq 'MISMATCH') 'pre-existing (no record): FAILED on publisher hash'
Check ([Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes((WeightsTarget $root))) -eq 'unrelated-bytes' -and -not $script:srv.calls.ContainsKey($weightsUrl)) 'pre-existing (no record): untouched, not re-downloaded'
Remove-Item -Recurse -Force $root

# 2/3/14. partial + proper 206 resumes to the exact expected bytes
ResetServer; $root = NewTempRoot; [void](SeedPartial $root $prefix)
$code = Run $root (FakeCatalog); $w = WeightsRecord $root
Check ($code -eq 0 -and $w.status -eq 'ACQUIRED' -and $w.resumedFromBytes -eq 10 -and $w.transferAttempts -eq 1) 'resume: 206 appended from offset 10'
Check ((($script:srv.ranges) -join ',') -eq '10') 'resume: Range starts at the partial length'
Check (SameBytes ([IO.File]::ReadAllBytes((WeightsTarget $root))) $weightsBytes) 'resume: final bytes exact'
Remove-Item -Recurse -Force $root

# 4. a 200 answer to a Range request is never appended (wrong-prefix partial proves no concatenation)
ResetServer; $root = NewTempRoot; [void](SeedPartial $root ([byte[]](0..9 | ForEach-Object { 0xEE })))
$script:srv.ignoreRange = $true
$code = Run $root (FakeCatalog); $w = WeightsRecord $root
Check ($code -eq 0 -and $w.status -eq 'ACQUIRED' -and $null -eq $w.resumedFromBytes) '200 to Range: full body replaces partial'
Check (SameBytes ([IO.File]::ReadAllBytes((WeightsTarget $root))) $weightsBytes) '200 to Range: final bytes exact, nothing concatenated'
Remove-Item -Recurse -Force $root

# 5/6. wrong Content-Range start or total fails closed, partial retained, no retry
foreach ($case in @('badStart', 'badTotal')) {
    ResetServer; $root = NewTempRoot; $p = SeedPartial $root $prefix
    $script:srv[$case] = $true
    $code = Run $root (FakeCatalog); $w = WeightsRecord $root
    Check ($code -eq 1 -and $w.status -eq 'FAILED' -and $w.error -like '*Content-Range*') "${case}: FAILED"
    Check ($script:srv.calls[$weightsUrl] -eq 1 -and $script:srv.sleeps.Count -eq 0) "${case}: not retried"
    Check ((Get-Item -LiteralPath $p).Length -eq 10 -and $w.partialRetained -eq $true -and -not (Test-Path -LiteralPath (WeightsTarget $root))) "${case}: partial retained unchanged, nothing promoted"
    Remove-Item -Recurse -Force $root
}

# 416 with an incomplete partial fails closed
ResetServer; $root = NewTempRoot; $p = SeedPartial $root $prefix
$script:srv.return416 = $true
$code = Run $root (FakeCatalog); $w = WeightsRecord $root
Check ($code -eq 1 -and $w.status -eq 'FAILED' -and $w.error -like '*416*' -and (Get-Item -LiteralPath $p).Length -eq 10) '416 with incomplete partial: FAILED, partial retained'
Remove-Item -Recurse -Force $root

# 7. oversized partial fails closed without any transfer
ResetServer; $root = NewTempRoot; $p = SeedPartial $root ([byte[]]($weightsBytes + [byte[]](1, 2, 3)))
$code = Run $root (FakeCatalog); $w = WeightsRecord $root
Check ($code -eq 1 -and $w.status -eq 'FAILED' -and -not $script:srv.calls.ContainsKey($weightsUrl) -and (Get-Item -LiteralPath $p).Length -eq 67) 'oversized partial: FAILED, no transfer, retained'
Remove-Item -Recurse -Force $root

# 8. exact-size correct partial is verified and promoted without network
ResetServer; $root = NewTempRoot; [void](SeedPartial $root $weightsBytes)
$code = Run $root (FakeCatalog); $w = WeightsRecord $root
Check ($code -eq 0 -and $w.status -eq 'ACQUIRED' -and $w.transferAttempts -eq 0 -and -not $script:srv.calls.ContainsKey($weightsUrl)) 'exact-size partial: promoted without network'
Remove-Item -Recurse -Force $root

# zero-byte partial restarts cleanly
ResetServer; $root = NewTempRoot; [void](SeedPartial $root (New-Object byte[] 0))
$code = Run $root (FakeCatalog); $w = WeightsRecord $root
Check ($code -eq 0 -and $w.status -eq 'ACQUIRED' -and (($script:srv.ranges) -join ',') -eq '0' -and $null -eq $w.resumedFromBytes) 'zero-byte partial: clean restart'
Remove-Item -Recurse -Force $root

# 9/14. transient reset mid-body is retried and resumed within one run; no duplicated bytes
ResetServer; $root = NewTempRoot
$script:srv.cutOnce = 10
$code = Run $root (FakeCatalog); $w = WeightsRecord $root
Check ($code -eq 0 -and $w.status -eq 'ACQUIRED' -and $w.transferAttempts -eq 2 -and $w.resumedFromBytes -eq 10) 'mid-body reset: retried and resumed'
Check ((($script:srv.ranges) -join ',') -eq '0,10' -and (($script:srv.sleeps) -join ',') -eq '2') 'mid-body reset: Range 10 after 2 s back-off'
Check (SameBytes ([IO.File]::ReadAllBytes((WeightsTarget $root))) $weightsBytes) 'mid-body reset: final bytes exact, no duplicates'
Remove-Item -Recurse -Force $root

# 9. transient failure retains the partial and a later run completes it
ResetServer; $root = NewTempRoot
$script:srv.cutOnce = 10; $script:srv.downAfterCut = $true
$code = Run $root (FakeCatalog); $w = WeightsRecord $root
$p = (WeightsTarget $root) + '.partial'
Check ($code -eq 1 -and $w.status -eq 'FAILED' -and $w.partialRetained -eq $true -and (Get-Item -LiteralPath $p).Length -eq 10) 'network down: FAILED with partial retained'
ResetServer
$code = Run $root (FakeCatalog); $w = WeightsRecord $root
Check ($code -eq 0 -and $w.status -eq 'ACQUIRED' -and $w.resumedFromBytes -eq 10 -and (SameBytes ([IO.File]::ReadAllBytes((WeightsTarget $root))) $weightsBytes)) 'next run: resumed from retained partial'
Remove-Item -Recurse -Force $root

# 10. bounded retry: 5 attempts, 2/4/8/16 s, then FAILED
ResetServer; $root = NewTempRoot
$script:srv.alwaysTransient = $true
$code = Run $root (FakeCatalog); $w = WeightsRecord $root
Check ($code -eq 1 -and $w.status -eq 'FAILED' -and $w.error -like '*after 5 attempts*' -and $w.transferAttempts -eq 5) 'retry: stops after 5 attempts'
Check ($script:srv.calls[$weightsUrl] -eq 5 -and (($script:srv.sleeps) -join ',') -eq '2,4,8,16') 'retry: deterministic back-off'
Remove-Item -Recurse -Force $root

# non-transient HTTP errors are not retried; transient HTTP codes are
foreach ($status in @(401, 403, 404)) {
    ResetServer; $root = NewTempRoot; $script:srv.http = $status
    $code = Run $root (FakeCatalog)
    Check ($code -eq 1 -and $script:srv.calls[$weightsUrl] -eq 1 -and $script:srv.sleeps.Count -eq 0) "HTTP ${status}: not retried"
    Remove-Item -Recurse -Force $root
}
ResetServer; $root = NewTempRoot; $script:srv.http = 503
$code = Run $root (FakeCatalog)
Check ($code -eq 1 -and $script:srv.calls[$weightsUrl] -eq 5) 'HTTP 503: retried to the limit'
Remove-Item -Recurse -Force $root

# 11. checksum mismatch after a resumed completion fails closed and is not promoted
ResetServer; $root = NewTempRoot; $p = SeedPartial $root $prefix
$code = Run $root (FakeCatalog @{ sha = ('0' * 64) }); $w = WeightsRecord $root
Check ($code -eq 1 -and $w.status -eq 'FAILED' -and $w.hashComparison.sha256 -eq 'MISMATCH' -and $w.resumedFromBytes -eq 10) 'resumed + wrong hash: FAILED'
Check (-not (Test-Path -LiteralPath (WeightsTarget $root)) -and (Test-Path -LiteralPath $p) -and $w.partialRetained -eq $true) 'resumed + wrong hash: not promoted, evidence retained'
Check (@($(Manifest $root).artifacts | Where-Object { $_.status -eq 'ACQUIRED' }).Count -eq 3) 'one failure still records the others'
Remove-Item -Recurse -Force $root

# size mismatch and zero bytes from the server
ResetServer; $root = NewTempRoot
$code = Run $root (FakeCatalog @{ size = 999 }); $w = WeightsRecord $root
Check ($code -eq 1 -and $w.status -eq 'FAILED' -and $w.error -like '*416*' -and -not (Test-Path -LiteralPath (WeightsTarget $root))) 'expected size larger than served: FAILED (416), nothing promoted'
Remove-Item -Recurse -Force $root
ResetServer; $root = NewTempRoot
$code = Run $root (FakeCatalog @{ size = 10 }); $w = WeightsRecord $root
Check ($code -eq 1 -and $w.status -eq 'FAILED' -and $w.error -like '*more than expected*' -and $w.partialRetained -eq $true -and -not (Test-Path -LiteralPath (WeightsTarget $root))) 'served more than expected: FAILED, retained, nothing promoted'
Remove-Item -Recurse -Force $root
ResetServer; $root = NewTempRoot; $script:srv.emptyBody = $true
$code = Run $root (FakeCatalog)
Check ($code -eq 1 -and @((Manifest $root).artifacts | Where-Object { $_.hashComparison.size -eq 'ZERO_BYTES' }).Count -eq 4) 'zero bytes: FAILED'
Remove-Item -Recurse -Force $root

# root inside a Git worktree is refused before anything is written
$repoLike = NewTempRoot
[void](New-Item -ItemType Directory -Path (Join-Path $repoLike '.git'))
$inside = Join-Path $repoLike 'models'
ResetServer
$code = Run $inside (FakeCatalog) 2>$null
Check ($code -eq 2 -and $script:srv.calls.Count -eq 0 -and -not (Test-Path -LiteralPath $inside)) 'inside Git worktree: refused'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
$code = Invoke-MaviS2cAcquisition -Root (Join-Path $repoRoot 'tmp-models') -Catalog (FakeCatalog) -Transport $fakeTransport -Sleep $fakeSleep -ScriptPath $scriptPath 2>$null 6>$null
Check ($code -eq 2 -and -not (Test-Path -LiteralPath (Join-Path $repoRoot 'tmp-models'))) 'inside MAVI repository: refused'
Remove-Item -Recurse -Force $repoLike

# dry run touches nothing
$root = Join-Path ([IO.Path]::GetTempPath()) ("mavi-acq-dry-" + [Guid]::NewGuid().ToString('N'))
$code = Invoke-MaviS2cAcquisition -Root $root -DryRun -ScriptPath $scriptPath 6>$null
Check ($code -eq 0 -and -not (Test-Path -LiteralPath $root)) 'dry run: no writes'

# real transport request construction: Range only on resume, no other header
$r0 = New-MaviHttpRequest -Uri 'https://huggingface.co/x' -RangeStart 0
$r10 = New-MaviHttpRequest -Uri 'https://huggingface.co/x' -RangeStart 10
Check ($null -eq $r0.Headers.Range -and @($r0.Headers).Count -eq 0) 'request: fresh transfer sends no Range and no headers'
Check ($r10.Headers.Range.ToString() -eq 'bytes=10-' -and @($r10.Headers).Count -eq 1 -and $null -eq $r10.Headers.Authorization) 'request: resume sends exactly Range bytes=10-'
Check ((Get-Command $scriptPath).Parameters.Keys -notcontains 'Transport' -and (Get-Command $scriptPath).Parameters.Keys -notcontains 'Sleep') 'CLI cannot supply a transport or sleep'

# Content-Range parser unit checks
function RangeRefused($cr, $off, $size) { try { Resolve-MaviContentRange -ContentRange $cr -Offset $off -ExpectedSize $size; $false } catch { $true } }
Check (-not (RangeRefused 'bytes 10-63/64' 10 64) -and -not (RangeRefused 'bytes 10-63/*' 10 64)) 'Content-Range: valid forms accepted'
Check ((RangeRefused 'bytes 9-63/64' 10 64) -and (RangeRefused 'bytes 10-63/65' 10 64) -and (RangeRefused 'bytes 10-64/64' 10 64) -and (RangeRefused '' 10 64) -and (RangeRefused 'items 10-63/64' 10 64)) 'Content-Range: wrong start/total/end/malformed refused'

if ($failures.Count -gt 0) { $failures | ForEach-Object { Write-Output "FAIL: $_" }; exit 1 }
Write-Output 'ALL S2C ACQUISITION BEHAVIOUR TESTS PASSED'
exit 0
