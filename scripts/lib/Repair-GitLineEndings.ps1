# Windows Git 기본값(core.autocrlf=true)으로 CRLF 체크아웃된 저장소를 커밋과 같은 LF로 되돌린다.
# scripts/setup-taisei.ps1에서 game/taisei에 사용한다(이슈 #4). 테스트: tests/setup-taisei/
#
# 안전 원칙
# - 인덱스를 지우거나 reset·checkout하지 않는다. 사용자 수정이 사라질 수 있는 동작은 하지 않는다.
# - 다음 중 하나라도 있으면 아무것도 바꾸지 않고 건너뛴다.
#   진행 중인 merge·rebase·cherry-pick·revert, sparse checkout,
#   assume-unchanged·skip-worktree 항목, 줄바꿈 무시 기준으로도 보이는 수정·스테이징,
#   내용 검증에 실패한 파일(줄바꿈 말고 다른 차이가 있는 파일)
# - 대상은 인덱스가 LF이고 작업 트리가 CRLF인 추적 파일(git ls-files --eol의 "i/lf w/crlf")뿐이다.
#   각 파일의 CRLF를 LF로 바꾼 내용의 blob 해시가 인덱스 blob과 같은지 직접 계산해 확인한다.
#   모든 대상이 확인된 뒤에만 그 파일들을 같은 자리에서 LF로 다시 쓰고, 해당 인덱스 항목의 파일 정보만 갱신한다.
#   미추적 파일·하위 submodule·다른 추적 파일은 건드리지 않는다.

function Get-GitBlobSha1 {
    # git hash-object와 같은 blob 해시: sha1("blob <길이>\0" + 내용)
    param([byte[]]$Bytes)
    $header = [System.Text.Encoding]::ASCII.GetBytes("blob $($Bytes.Length)`0")
    $sha1 = [System.Security.Cryptography.SHA1]::Create()
    try {
        $null = $sha1.TransformBlock($header, 0, $header.Length, $null, 0)
        $null = $sha1.TransformFinalBlock($Bytes, 0, $Bytes.Length)
        return ([System.BitConverter]::ToString($sha1.Hash) -replace '-', '').ToLowerInvariant()
    } finally {
        $sha1.Dispose()
    }
}

function ConvertTo-LfBytes {
    # CRLF(0D 0A)만 LF(0A)로 바꾼다. 단독 CR은 그대로 둔다.
    param([byte[]]$Bytes)
    $output = New-Object System.IO.MemoryStream ($Bytes.Length)
    try {
        for ($i = 0; $i -lt $Bytes.Length; $i++) {
            if ($Bytes[$i] -eq 13 -and ($i + 1) -lt $Bytes.Length -and $Bytes[$i + 1] -eq 10) {
                continue
            }
            $output.WriteByte($Bytes[$i])
        }
        return , $output.ToArray()
    } finally {
        $output.Dispose()
    }
}

function Invoke-GitLines {
    # git 출력을 줄 배열로 받는다. 실패하면 예외를 던진다.
    # 비ASCII 경로가 깨지지 않도록 UTF-8로 읽고 core.quotePath=false로 경로를 그대로 출력하게 한다.
    param([string]$RepoPath, [string[]]$Arguments)
    $previous = $ErrorActionPreference
    $previousEncoding = [Console]::OutputEncoding
    $ErrorActionPreference = 'Continue'
    try {
        [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
        $lines = @(& git -C $RepoPath -c core.quotePath=false @Arguments 2>$null)
        $code = $LASTEXITCODE
    } finally {
        [Console]::OutputEncoding = $previousEncoding
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) {
        throw "git $($Arguments -join ' ') failed in $RepoPath (exit $code)."
    }
    # 줄 단위로 내보낸다. 호출 측은 항상 @(...)로 받는다(배열을 객체 하나로 내보내면 빈 결과도 개수 1이 된다).
    return $lines
}

function Repair-GitLineEndings {
    <#
    결과 객체: Action = 'normalized' | 'none' | 'skipped', Reason(건너뛴 이유), Count(다시 쓴 파일 수), Details(관련 경로 일부)
    호출 측의 core.autocrlf 설정과 무관하게 동작하도록 필요한 git 호출에 -c core.autocrlf 값을 명시한다.
    #>
    [CmdletBinding()]
    param([Parameter(Mandatory)] [string]$RepoPath)

    $skip = {
        param([string]$Reason, [string[]]$Details = @())
        return [pscustomobject]@{ Action = 'skipped'; Reason = $Reason; Count = 0; Details = @($Details | Select-Object -First 5) }
    }

    # 1. 평범한 checkout인지 확인한다.
    $gitDir = @(Invoke-GitLines $RepoPath @('rev-parse', '--path-format=absolute', '--git-dir'))[0].Trim()
    foreach ($marker in @('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'rebase-merge', 'rebase-apply', 'sequencer')) {
        if (Test-Path -LiteralPath (Join-Path $gitDir $marker)) {
            return & $skip "operation in progress ($marker)"
        }
    }
    $sparse = @(Invoke-GitLines $RepoPath @('config', '--bool', '--default', 'false', '--get', 'core.sparseCheckout'))
    if ($sparse.Count -gt 0 -and $sparse[0].Trim() -eq 'true') {
        return & $skip 'sparse checkout is enabled'
    }

    # 2. 인덱스 특수 상태: assume-unchanged(소문자 태그), skip-worktree(S 태그). 이 항목의 수정은 상태 조회에 보이지 않는다.
    $flagged = @(Invoke-GitLines $RepoPath @('ls-files', '-v') | Where-Object { $_ -cmatch '^([a-z]|S) ' })
    if ($flagged.Count -gt 0) {
        return & $skip "$($flagged.Count) index entr(y/ies) marked assume-unchanged or skip-worktree" ($flagged | ForEach-Object { $_.Substring(2) })
    }

    # 3. 줄바꿈을 무시하는 기준(autocrlf=true)으로 보이는 수정·스테이징이 있으면 건너뛴다.
    $changes = @(Invoke-GitLines $RepoPath @('-c', 'core.autocrlf=true', 'status', '--porcelain', '--untracked-files=no', '--ignore-submodules=all'))
    if ($changes.Count -gt 0) {
        return & $skip "$($changes.Count) locally modified or staged file(s)" $changes
    }

    # 4. 대상 선정: 인덱스 LF, 작업 트리 CRLF
    $targets = @(Invoke-GitLines $RepoPath @('ls-files', '--eol') |
        Where-Object { $_ -match '^i/lf\s+w/crlf\s' } |
        ForEach-Object { ($_ -split "`t", 2)[1] })
    if ($targets.Count -eq 0) {
        return [pscustomobject]@{ Action = 'none'; Reason = ''; Count = 0; Details = @() }
    }

    # 5. 인덱스 blob 해시와 내용 비교. 하나라도 어긋나면 아무 파일도 쓰지 않는다.
    $indexSha = @{}
    foreach ($line in @(Invoke-GitLines $RepoPath @('ls-files', '-s'))) {
        # 형식: <mode> <sha> <stage>\t<path>
        $meta, $path = $line -split "`t", 2
        $fields = $meta -split ' '
        if ($fields[2] -ne '0') {
            return & $skip 'index has unmerged entries' @($path)
        }
        $indexSha[$path] = $fields[1]
    }
    $verified = New-Object System.Collections.Generic.List[object]
    $mismatched = New-Object System.Collections.Generic.List[string]
    foreach ($relative in $targets) {
        $full = Join-Path $RepoPath $relative
        $lf = ConvertTo-LfBytes ([System.IO.File]::ReadAllBytes($full))
        if ((Get-GitBlobSha1 $lf) -eq $indexSha[$relative]) {
            $verified.Add([pscustomobject]@{ Relative = $relative; Full = $full; Bytes = $lf })
        } else {
            $mismatched.Add($relative)
        }
    }
    if ($mismatched.Count -gt 0) {
        return & $skip "$($mismatched.Count) CRLF file(s) differ from the index beyond line endings" $mismatched
    }

    # 6. 확인된 파일만 같은 자리에서 LF로 다시 쓴다. 내용은 인덱스 blob과 같으므로 중간에 실패해도 잃는 내용은 없다.
    foreach ($item in $verified) {
        [System.IO.File]::WriteAllBytes($item.Full, $item.Bytes)
    }

    # 7. 다시 쓴 파일의 인덱스 항목만 파일 정보를 갱신한다. 내용 해시가 같으므로 스테이징되는 변경은 없다.
    #    (clone 시점에 기록된 CRLF 크기가 남아 있으면 Git이 크기 차이만 보고 수정됨으로 판단하기 때문)
    #    표준 입력 대신 인자로 넘긴다(Windows PowerShell 5.1이 파이프 끝에 CR을 붙여 경로가 바뀌는 문제 방지). 명령줄 길이 제한 때문에 나눠 보낸다.
    $paths = @($verified | ForEach-Object { $_.Relative })
    for ($start = 0; $start -lt $paths.Count; $start += 100) {
        $batch = $paths[$start..([Math]::Min($start + 99, $paths.Count - 1))]
        $null = Invoke-GitLines $RepoPath (@('-c', 'core.autocrlf=false', 'update-index', '--') + $batch)
    }

    $stillCrlf = @(Invoke-GitLines $RepoPath @('ls-files', '--eol') | Where-Object { $_ -match '^i/lf\s+w/crlf\s' })
    $remaining = @(Invoke-GitLines $RepoPath @('-c', 'core.autocrlf=false', 'status', '--porcelain', '--untracked-files=no', '--ignore-submodules=all'))
    if ($stillCrlf.Count -gt 0 -or $remaining.Count -gt 0) {
        throw "$RepoPath still has $($stillCrlf.Count) CRLF file(s) and $($remaining.Count) modified file(s) after normalization."
    }
    return [pscustomobject]@{ Action = 'normalized'; Reason = ''; Count = $verified.Count; Details = @() }
}
