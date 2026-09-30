# Behavioural tests for tools/qualification/model_selection/acquire_s2c_candidates.ps1.
# Run by test_s2c_acquisition_script.py when pwsh is available. No network: a fake downloader
# writes local bytes; the production catalog is only inspected, never downloaded.
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

# ---- synthetic acquisition catalog + fake downloader (no network)
$payload = @{
    'https://huggingface.co/x/resolve/0000000000000000000000000000000000000001/model.safetensors' = [Text.Encoding]::UTF8.GetBytes('weights-bytes')
    'https://huggingface.co/x/resolve/0000000000000000000000000000000000000001/config.json' = [Text.Encoding]::UTF8.GetBytes('{"a":1}')
    'https://storage.openvinotoolkit.org/x/FP32/m.bin' = [Text.Encoding]::UTF8.GetBytes('ir-bin')
    'https://storage.openvinotoolkit.org/x/FP32/m.xml' = [Text.Encoding]::UTF8.GetBytes('<ir/>')
}
function FakeCatalog([hashtable]$over = @{}) {
    $w = $payload['https://huggingface.co/x/resolve/0000000000000000000000000000000000000001/model.safetensors']
    $cfg = $payload['https://huggingface.co/x/resolve/0000000000000000000000000000000000000001/config.json']
    $bin = $payload['https://storage.openvinotoolkit.org/x/FP32/m.bin']; $xml = $payload['https://storage.openvinotoolkit.org/x/FP32/m.xml']
    @(
        [pscustomobject]@{ family = 'hf-test'; candidateIds = @('PC-1', 'VC-2'); sourceRepository = 'https://huggingface.co/x'; revision = '0000000000000000000000000000000000000001'; revisionCheck = 'x-repo-commit'
            files = @(
                [pscustomobject]@{ name = 'config.json'; role = 'configuration'; url = 'https://huggingface.co/x/resolve/0000000000000000000000000000000000000001/config.json'; expectedSize = [long]$cfg.Length; publisherSha256 = $null; publisherSha384 = $null; publisherGitBlobSha1 = (BlobSha1Hex $cfg) },
                [pscustomobject]@{ name = 'model.safetensors'; role = 'weights'; url = 'https://huggingface.co/x/resolve/0000000000000000000000000000000000000001/model.safetensors'; expectedSize = [long]$(if ($over.ContainsKey('size')) { $over.size } else { $w.Length }); publisherSha256 = $(if ($over.ContainsKey('sha')) { $over.sha } else { Sha256Hex $w }); publisherSha384 = $null; publisherGitBlobSha1 = $null }
            ) },
        [pscustomobject]@{ family = 'omz-test'; candidateIds = @('PC-7'); sourceRepository = 'omz'; revision = 'a6946b6d6ce42cbf4278df20275fab199655fc7d'; revisionCheck = 'none'
            files = @(
                [pscustomobject]@{ name = 'FP32/m.bin'; role = 'openvino-ir-weights'; url = 'https://storage.openvinotoolkit.org/x/FP32/m.bin'; expectedSize = [long]$bin.Length; publisherSha256 = $null; publisherSha384 = (Sha384Hex $bin); publisherGitBlobSha1 = $null },
                [pscustomobject]@{ name = 'FP32/m.xml'; role = 'openvino-ir-topology'; url = 'https://storage.openvinotoolkit.org/x/FP32/m.xml'; expectedSize = [long]$xml.Length; publisherSha256 = $null; publisherSha384 = (Sha384Hex $xml); publisherGitBlobSha1 = $null }
            ) }
    )
}
$script:calls = 0
$fake = { param($Url, $Destination, $ExpectedRevision) $script:calls++; [IO.File]::WriteAllBytes($Destination, $payload[$Url]) }
$empty = { param($Url, $Destination, $ExpectedRevision) [IO.File]::WriteAllBytes($Destination, (New-Object byte[] 0)) }
$boom = { param($Url, $Destination, $ExpectedRevision) throw 'HTTP 503 from test' }
function Manifest($root) { Get-Content -LiteralPath (Join-Path $root 'acquisition-manifest.json') -Raw | ConvertFrom-Json }
function Run($root, $cat, $dl) { Invoke-MaviS2cAcquisition -Root $root -Catalog $cat -Downloader $dl -ScriptPath $scriptPath 6>$null }

# fresh acquisition
$root = NewTempRoot
$code = Run $root (FakeCatalog) $fake
$m = Manifest $root
Check ($code -eq 0) 'fresh: exit 0'
Check (@($m.artifacts | Where-Object { $_.status -eq 'ACQUIRED' }).Count -eq 4) 'fresh: 4 files ACQUIRED'
Check ((@($m.artifacts | ForEach-Object { $_.localRelativePath }) -join '|') -eq 'hf-test/0000000000000000000000000000000000000001/config.json|hf-test/0000000000000000000000000000000000000001/model.safetensors|omz-test/a6946b6d6ce42cbf4278df20275fab199655fc7d/FP32/m.bin|omz-test/a6946b6d6ce42cbf4278df20275fab199655fc7d/FP32/m.xml') 'fresh: deterministic ordering and paths'
Check ((($m.artifacts | Where-Object { $_.fileName -eq 'model.safetensors' }).candidateIds -join ',') -eq 'PC-1,VC-2') 'shared file downloaded once with all ids'
Check ($script:calls -eq 4) 'fresh: one download per file'
Check (($m.artifacts | Where-Object { $_.fileName -eq 'FP32/m.bin' }).hashComparison.sha384 -eq 'MATCH') 'OMZ SHA-384 compared'
Check ($null -eq ($m.artifacts | Where-Object { $_.fileName -eq 'FP32/m.bin' }).publisherSha256) 'OMZ has no invented SHA-256'
Check (($m.artifacts | Where-Object { $_.fileName -eq 'config.json' }).hashComparison.gitBlobSha1 -eq 'MATCH') 'HF config git blob SHA-1 compared'
Check (@(Get-ChildItem -LiteralPath $root -Recurse -Filter '*.partial').Count -eq 0) 'no .partial left behind'
Check ($m.schema -eq 'mavi-s2c-candidate-acquisition-manifest-v1' -and $m.overallStatus -eq 'COMPLETE' -and $m.scriptSha256 -match '^[0-9a-f]{64}$') 'manifest header'
Check (@($m.blockedFamilies).Count -eq 4 -and @($m.blockedFamilies | Where-Object { $_.status -ne 'BLOCKED' }).Count -eq 0) 'blocked families recorded'
$bytes = [IO.File]::ReadAllBytes((Join-Path $root 'acquisition-manifest.json'))
Check (-not ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB) -and -not ([Text.Encoding]::UTF8.GetString($bytes).Contains("`r"))) 'manifest UTF-8 without BOM, LF only'
Check (Test-Path -LiteralPath (Join-Path $root 'acquisition-summary.txt')) 'summary written'

# rerun is idempotent
$script:calls = 0
$code = Run $root (FakeCatalog) $fake
$m = Manifest $root
Check ($code -eq 0 -and $script:calls -eq 0) 'rerun: no downloads, exit 0'
Check (@($m.artifacts | Where-Object { $_.status -eq 'ALREADY_PRESENT_VERIFIED' }).Count -eq 4) 'rerun: ALREADY_PRESENT_VERIFIED'
Check (@(Get-ChildItem -LiteralPath (Join-Path $root 'history') -Filter 'acquisition-manifest-*.json').Count -eq 1) 'rerun: previous manifest retained in history'

# pre-existing differing file is never overwritten
$weights = Join-Path $root 'hf-test/0000000000000000000000000000000000000001/model.safetensors'
[IO.File]::WriteAllBytes($weights, [Text.Encoding]::UTF8.GetBytes('tampered-bytes'))
$code = Run $root (FakeCatalog) $fake
$m = Manifest $root
Check ($code -eq 1) 'tampered: exit 1'
Check ((($m.artifacts | Where-Object { $_.fileName -eq 'model.safetensors' }).status) -eq 'FAILED') 'tampered: FAILED'
Check ([Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($weights)) -eq 'tampered-bytes') 'tampered: file left untouched'
Check ($m.overallStatus -eq 'FAILED') 'tampered: overall FAILED'
Remove-Item -Recurse -Force $root

# differing file present before any acquisition record exists (publisher check alone)
$root = NewTempRoot
$pre = Join-Path $root 'hf-test/0000000000000000000000000000000000000001/model.safetensors'
[void](New-Item -ItemType Directory -Force -Path ([IO.Path]::GetDirectoryName($pre)))
[IO.File]::WriteAllBytes($pre, [Text.Encoding]::UTF8.GetBytes('unrelated-bytes'))
$script:calls = 0
$code = Run $root (FakeCatalog) $fake
$w = (Manifest $root).artifacts | Where-Object { $_.fileName -eq 'model.safetensors' }
Check ($code -eq 1 -and $w.status -eq 'FAILED' -and $w.hashComparison.sha256 -eq 'MISMATCH') 'pre-existing (no record): FAILED on publisher hash'
Check ([Text.Encoding]::UTF8.GetString([IO.File]::ReadAllBytes($pre)) -eq 'unrelated-bytes' -and $script:calls -eq 3) 'pre-existing (no record): untouched, not re-downloaded'
Remove-Item -Recurse -Force $root

# publisher SHA-256 mismatch
$root = NewTempRoot
$code = Run $root (FakeCatalog @{ sha = ('0' * 64) }) $fake
$m = Manifest $root; $w = $m.artifacts | Where-Object { $_.fileName -eq 'model.safetensors' }
Check ($code -eq 1 -and $w.status -eq 'FAILED' -and $w.hashComparison.sha256 -eq 'MISMATCH') 'sha mismatch: FAILED'
Check (-not (Test-Path -LiteralPath (Join-Path $root 'hf-test/0000000000000000000000000000000000000001/model.safetensors'))) 'sha mismatch: nothing renamed into place'
Check (@(Get-ChildItem -LiteralPath $root -Recurse -Filter '*.partial').Count -eq 0) 'sha mismatch: partial removed'
Check (@($m.artifacts | Where-Object { $_.status -eq 'ACQUIRED' }).Count -eq 3) 'one failure still records the others'
Remove-Item -Recurse -Force $root

# size mismatch, zero bytes, HTTP error
$root = NewTempRoot
$code = Run $root (FakeCatalog @{ size = 999 }) $fake
Check ($code -eq 1 -and ((Manifest $root).artifacts | Where-Object { $_.fileName -eq 'model.safetensors' }).hashComparison.size -eq 'MISMATCH') 'size mismatch: FAILED'
Remove-Item -Recurse -Force $root
$root = NewTempRoot
$code = Run $root (FakeCatalog) $empty
Check ($code -eq 1 -and @((Manifest $root).artifacts | Where-Object { $_.hashComparison.size -eq 'ZERO_BYTES' }).Count -eq 4) 'zero bytes: FAILED'
Remove-Item -Recurse -Force $root
$root = NewTempRoot
$code = Run $root (FakeCatalog) $boom
$m = Manifest $root
Check ($code -eq 1 -and @($m.artifacts | Where-Object { $_.status -eq 'FAILED' -and $_.error -like '*503*' }).Count -eq 4) 'HTTP error: FAILED with error recorded'
Remove-Item -Recurse -Force $root

# root inside a Git worktree is refused before anything is written
$repoLike = NewTempRoot
[void](New-Item -ItemType Directory -Path (Join-Path $repoLike '.git'))
$inside = Join-Path $repoLike 'models'
$script:calls = 0
$code = Run $inside (FakeCatalog) $fake 2>$null
Check ($code -eq 2 -and $script:calls -eq 0 -and -not (Test-Path -LiteralPath $inside)) 'inside Git worktree: refused'
$repoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
$code = Invoke-MaviS2cAcquisition -Root (Join-Path $repoRoot 'tmp-models') -Catalog (FakeCatalog) -Downloader $fake -ScriptPath $scriptPath 2>$null 6>$null
Check ($code -eq 2 -and -not (Test-Path -LiteralPath (Join-Path $repoRoot 'tmp-models'))) 'inside MAVI repository: refused'
Remove-Item -Recurse -Force $repoLike

# dry run touches nothing
$root = Join-Path ([IO.Path]::GetTempPath()) ("mavi-acq-dry-" + [Guid]::NewGuid().ToString('N'))
$code = Invoke-MaviS2cAcquisition -Root $root -DryRun -ScriptPath $scriptPath 6>$null
Check ($code -eq 0 -and -not (Test-Path -LiteralPath $root)) 'dry run: no writes'

if ($failures.Count -gt 0) { $failures | ForEach-Object { Write-Output "FAIL: $_" }; exit 1 }
Write-Output 'ALL S2C ACQUISITION BEHAVIOUR TESTS PASSED'
exit 0
