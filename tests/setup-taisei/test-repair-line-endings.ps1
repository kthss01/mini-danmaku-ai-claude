# scripts/lib/Repair-GitLineEndings.ps1 회귀 테스트 (이슈 #4, PR #25 검토 대응)
# 네트워크 없이 임시 Git 저장소를 만들어 검사한다. 실행: powershell -NoProfile -File tests\setup-taisei\test-repair-line-endings.ps1
# 종료 코드: 0 모두 통과, 1 실패 있음

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
. (Join-Path $repoRoot 'scripts\lib\Repair-GitLineEndings.ps1')

$workRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("repair-eol-test-" + [Guid]::NewGuid().ToString('N').Substring(0, 8))
New-Item -ItemType Directory -Path $workRoot | Out-Null
$script:failures = 0
$script:checks = 0

function Invoke-Git {
    param([string]$Repo, [string[]]$Arguments)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = @(& git -C $Repo -c user.name=test -c user.email=test@example.invalid @Arguments 2>&1 | ForEach-Object { "$_" })
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
    if ($code -ne 0) { throw "git $($Arguments -join ' ') failed: $($out -join ' ')" }
    # 줄 단위로 내보낸다. 호출 측은 @(...)로 받는다.
    return $out
}

function Assert-True {
    param([string]$Name, [bool]$Condition, [string]$Detail = '')
    $script:checks++
    if ($Condition) {
        Write-Host "  PASS $Name"
    } else {
        $script:failures++
        Write-Host "  FAIL $Name $Detail"
    }
}

function Write-Bytes { param([string]$Path, [string]$Text) [System.IO.File]::WriteAllBytes($Path, [System.Text.Encoding]::UTF8.GetBytes($Text)) }
function Read-Text { param([string]$Path) [System.Text.Encoding]::UTF8.GetString([System.IO.File]::ReadAllBytes($Path)) }
function Get-IndexHash { param([string]$Repo) (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $Repo '.git\index')).Hash }
function Get-CrlfCount { param([string]$Repo) @(Invoke-Git $Repo @('ls-files', '--eol') | Where-Object { $_ -match '^i/lf\s+w/crlf\s' }).Count }
function Get-Modified { param([string]$Repo) @(Invoke-Git $Repo @('-c', 'core.autocrlf=false', 'status', '--porcelain', '--untracked-files=no')) }

# 원본 저장소: LF로 커밋한 텍스트 2개와 바이너리 1개
$origin = Join-Path $workRoot 'origin'
New-Item -ItemType Directory -Path $origin | Out-Null
Invoke-Git $origin @('init', '-q') | Out-Null
Invoke-Git $origin @('config', 'core.autocrlf', 'false') | Out-Null
Write-Bytes (Join-Path $origin 'a.txt') "alpha 1`nalpha 2`n"
Write-Bytes (Join-Path $origin 'b.txt') "bravo 1`nbravo 2`n"
[System.IO.File]::WriteAllBytes((Join-Path $origin 'bin.dat'), [byte[]](0, 13, 10, 255, 0))
Invoke-Git $origin @('add', '.') | Out-Null
Invoke-Git $origin @('commit', '-q', '-m', 'init') | Out-Null

function New-CrlfClone {
    # Windows 기본값처럼 autocrlf=true로 clone해 작업 트리를 CRLF로 만든 뒤, setup-taisei처럼 autocrlf=false를 설정한다.
    param([string]$Name)
    $path = Join-Path $workRoot $Name
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & git -c core.autocrlf=true clone -q $origin $path 2>&1 | Out-Null
    $ErrorActionPreference = $previous
    if ($LASTEXITCODE -ne 0) { throw "clone failed: $Name" }
    Invoke-Git $path @('config', 'core.autocrlf', 'false') | Out-Null
    return $path
}

function Touch-All {
    # 파일 시각을 바꿔 Git이 캐시 대신 내용을 다시 비교하게 한다.
    param([string]$Repo)
    $now = (Get-Date).AddSeconds(5)
    foreach ($f in @('a.txt', 'b.txt', 'bin.dat')) {
        $p = Join-Path $Repo $f
        if (Test-Path -LiteralPath $p) { (Get-Item -LiteralPath $p).LastWriteTime = $now }
    }
}

try {
    Write-Host '1) 깨끗한 CRLF clone: 정규화'
    $r = New-CrlfClone 'clean'
    Assert-True 'CRLF 파일 2개로 시작' ((Get-CrlfCount $r) -eq 2)
    $result = Repair-GitLineEndings -RepoPath $r
    Assert-True 'Action=normalized, Count=2' ($result.Action -eq 'normalized' -and $result.Count -eq 2) "$($result.Action) $($result.Count) $($result.Reason)"
    Assert-True 'CRLF 0' ((Get-CrlfCount $r) -eq 0)
    Assert-True 'a.txt 내용 LF' ((Read-Text (Join-Path $r 'a.txt')) -eq "alpha 1`nalpha 2`n")
    Touch-All $r
    Assert-True '시각 변경 후에도 수정 0' ((Get-Modified $r).Count -eq 0) ((Get-Modified $r) -join '; ')
    $again = Repair-GitLineEndings -RepoPath $r
    Assert-True '재실행은 Action=none' ($again.Action -eq 'none')

    Write-Host '2) 실제 수정(CRLF 유지) + 다른 CRLF 파일: 건너뜀, 수정·인덱스 보존'
    $r = New-CrlfClone 'real-edit'
    Write-Bytes (Join-Path $r 'a.txt') "alpha 1`r`nalpha 2`r`nUSER EDIT`r`n"
    $indexBefore = Get-IndexHash $r
    $result = Repair-GitLineEndings -RepoPath $r
    Assert-True 'Action=skipped(수정)' ($result.Action -eq 'skipped' -and $result.Reason -match 'modified') "$($result.Action) $($result.Reason)"
    Assert-True 'a.txt 수정 보존' ((Read-Text (Join-Path $r 'a.txt')) -match 'USER EDIT')
    Assert-True 'b.txt 그대로 CRLF' ((Read-Text (Join-Path $r 'b.txt')) -eq "bravo 1`r`nbravo 2`r`n")
    Assert-True '인덱스 파일 불변' ((Get-IndexHash $r) -eq $indexBefore)

    Write-Host '3) assume-unchanged 파일의 실제 수정 + 다른 CRLF 파일 (Codex 재현 조건): 건너뜀, 보존'
    $r = New-CrlfClone 'assume-unchanged'
    Invoke-Git $r @('update-index', '--assume-unchanged', 'a.txt') | Out-Null
    Write-Bytes (Join-Path $r 'a.txt') "USER EDIT`r`n"
    $statusHidden = @(Invoke-Git $r @('-c', 'core.autocrlf=true', 'status', '--porcelain', '--untracked-files=no')).Count -eq 0
    Assert-True '상태 조회에는 수정이 보이지 않음(전제 확인)' $statusHidden
    # 전제 확인용 상태 조회가 인덱스 파일 정보를 갱신할 수 있으므로 그 뒤에 기준 해시를 잡는다.
    $indexBefore = Get-IndexHash $r
    $result = Repair-GitLineEndings -RepoPath $r
    Assert-True 'Action=skipped(assume-unchanged)' ($result.Action -eq 'skipped' -and $result.Reason -match 'assume-unchanged') "$($result.Action) $($result.Reason)"
    Assert-True 'a.txt 사용자 수정 보존' ((Read-Text (Join-Path $r 'a.txt')) -eq "USER EDIT`r`n")
    Assert-True '인덱스 파일 불변(플래그 유지)' ((Get-IndexHash $r) -eq $indexBefore)

    Write-Host '4) skip-worktree 파일의 실제 수정: 건너뜀, 보존'
    $r = New-CrlfClone 'skip-worktree'
    Invoke-Git $r @('update-index', '--skip-worktree', 'a.txt') | Out-Null
    Write-Bytes (Join-Path $r 'a.txt') "SKIP WORKTREE EDIT`r`n"
    $indexBefore = Get-IndexHash $r
    $result = Repair-GitLineEndings -RepoPath $r
    Assert-True 'Action=skipped(skip-worktree)' ($result.Action -eq 'skipped' -and $result.Reason -match 'skip-worktree') "$($result.Action) $($result.Reason)"
    Assert-True 'a.txt 수정 보존' ((Read-Text (Join-Path $r 'a.txt')) -eq "SKIP WORKTREE EDIT`r`n")
    Assert-True '인덱스 파일 불변' ((Get-IndexHash $r) -eq $indexBefore)

    Write-Host '5) sparse checkout 설정: 건너뜀'
    $r = New-CrlfClone 'sparse'
    Invoke-Git $r @('config', 'core.sparseCheckout', 'true') | Out-Null
    $indexBefore = Get-IndexHash $r
    $result = Repair-GitLineEndings -RepoPath $r
    Assert-True 'Action=skipped(sparse)' ($result.Action -eq 'skipped' -and $result.Reason -match 'sparse') "$($result.Action) $($result.Reason)"
    Assert-True 'CRLF 그대로' ((Get-CrlfCount $r) -eq 2)
    Assert-True '인덱스 파일 불변' ((Get-IndexHash $r) -eq $indexBefore)

    Write-Host '6) 진행 중인 merge 표시(MERGE_HEAD): 건너뜀'
    $r = New-CrlfClone 'merge-in-progress'
    $head = @(Invoke-Git $r @('rev-parse', 'HEAD'))[0]
    Set-Content -LiteralPath (Join-Path $r '.git\MERGE_HEAD') -Value $head -Encoding ascii
    $result = Repair-GitLineEndings -RepoPath $r
    Assert-True 'Action=skipped(MERGE_HEAD)' ($result.Action -eq 'skipped' -and $result.Reason -match 'MERGE_HEAD') "$($result.Action) $($result.Reason)"
    Assert-True 'CRLF 그대로' ((Get-CrlfCount $r) -eq 2)

    Write-Host '7) 스테이징된 변경: 건너뜀, 스테이징 보존'
    $r = New-CrlfClone 'staged'
    Write-Bytes (Join-Path $r 'b.txt') "bravo staged`r`n"
    Invoke-Git $r @('-c', 'core.autocrlf=true', 'add', 'b.txt') | Out-Null
    $result = Repair-GitLineEndings -RepoPath $r
    Assert-True 'Action=skipped(staged)' ($result.Action -eq 'skipped') "$($result.Action) $($result.Reason)"
    Assert-True '스테이징 보존' (@(Invoke-Git $r @('diff', '--cached', '--name-only')) -contains 'b.txt')

    Write-Host '8) 미추적 파일만 있음: 정규화, 미추적 보존'
    $r = New-CrlfClone 'untracked'
    Write-Bytes (Join-Path $r 'note.txt') "keep me`r`n"
    New-Item -ItemType Directory -Path (Join-Path $r 'scratch') | Out-Null
    Write-Bytes (Join-Path $r 'scratch\x.txt') "scratch`r`n"
    $result = Repair-GitLineEndings -RepoPath $r
    Assert-True 'Action=normalized' ($result.Action -eq 'normalized') "$($result.Action) $($result.Reason)"
    Assert-True '미추적 파일 내용 보존' ((Read-Text (Join-Path $r 'note.txt')) -eq "keep me`r`n" -and (Read-Text (Join-Path $r 'scratch\x.txt')) -eq "scratch`r`n")

    Write-Host '9) 시각·크기를 원래대로 맞춘 내용 수정(상태 조회가 못 잡는 경우): 내용 검증으로 건너뜀'
    $r = New-CrlfClone 'stat-hidden-edit'
    $p = Join-Path $r 'a.txt'
    # 파일 시각을 과거로 돌리고 인덱스를 갱신해, 이후 Git이 파일 정보만 보고 "변경 없음"으로 판단하게 만든다
    # (clone 직후에는 파일과 인덱스 시각이 가까워 Git이 내용을 다시 비교하므로 이 단계가 필요하다).
    $old = (Get-Date).ToUniversalTime().AddHours(-1)
    (Get-Item -LiteralPath $p).LastWriteTimeUtc = $old
    Invoke-Git $r @('-c', 'core.autocrlf=true', 'update-index', '-q', '--refresh') | Out-Null
    $edited = [System.IO.File]::ReadAllBytes($p)
    $edited[0] = [byte][char]'X'   # 같은 길이로 첫 글자만 바꿈
    [System.IO.File]::WriteAllBytes($p, $edited)
    (Get-Item -LiteralPath $p).LastWriteTimeUtc = $old
    $statusHidden = @(Invoke-Git $r @('-c', 'core.autocrlf=true', 'status', '--porcelain', '--untracked-files=no')).Count -eq 0
    Assert-True '상태 조회가 수정을 놓침(전제 확인)' $statusHidden
    $result = Repair-GitLineEndings -RepoPath $r
    Assert-True 'Action=skipped(줄바꿈 외 차이)' ($result.Action -eq 'skipped' -and $result.Reason -match 'beyond line endings') "$($result.Action) $($result.Reason)"
    Assert-True 'a.txt 수정 보존' ([System.IO.File]::ReadAllBytes($p)[0] -eq [byte][char]'X')
    Assert-True 'b.txt 그대로 CRLF(부분 정규화 없음)' ((Read-Text (Join-Path $r 'b.txt')) -eq "bravo 1`r`nbravo 2`r`n")

    Write-Host '10) blob 해시 계산이 git hash-object와 같음'
    $sample = Join-Path $workRoot 'sample.bin'
    [System.IO.File]::WriteAllBytes($sample, [System.Text.Encoding]::UTF8.GetBytes("한글 line`r`nsecond`r`nlone`rcr`n"))
    $lf = ConvertTo-LfBytes ([System.IO.File]::ReadAllBytes($sample))
    Assert-True 'CRLF만 LF로 바꾸고 단독 CR은 유지' ([System.Text.Encoding]::UTF8.GetString($lf) -eq "한글 line`nsecond`nlone`rcr`n")
    [System.IO.File]::WriteAllBytes($sample, $lf)
    $expected = @(Invoke-Git $workRoot @('hash-object', '--no-filters', $sample))[0].Trim()
    Assert-True 'Get-GitBlobSha1 = git hash-object' ((Get-GitBlobSha1 $lf) -eq $expected) "$(Get-GitBlobSha1 $lf) vs $expected"
} finally {
    Remove-Item -LiteralPath $workRoot -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ''
Write-Host "checks: $script:checks, failures: $script:failures"
if ($script:failures -gt 0) { exit 1 }
exit 0
