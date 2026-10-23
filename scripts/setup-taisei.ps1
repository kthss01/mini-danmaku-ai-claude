[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taiseiPath = Join-Path $repoRoot 'game\taisei'
$forkUrl = 'https://github.com/kthss01/taisei.git'
$upstreamUrl = 'https://github.com/taisei-project/taisei.git'

Push-Location $repoRoot
try {
    git submodule update --init --recursive
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to initialize Taisei submodules.'
    }

    $origin = git -C $taiseiPath remote get-url origin
    if ($LASTEXITCODE -ne 0 -or $origin -ne $forkUrl) {
        throw "Unexpected Taisei origin: $origin"
    }

    $upstreamExists = git -C $taiseiPath remote | Where-Object { $_ -eq 'upstream' }
    if ($upstreamExists) {
        git -C $taiseiPath remote set-url upstream $upstreamUrl
    } else {
        git -C $taiseiPath remote add upstream $upstreamUrl
    }
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to configure the Taisei upstream remote.'
    }

    # Keep executable scripts usable inside the Linux build container.
    # Windows Git 기본값(core.autocrlf=true)으로 clone하면 Taisei 작업 트리가 CRLF로 체크아웃된다.
    # 여기서 core.autocrlf=false로 바꾸면 Git이 줄바꿈만 다른 파일을 수정됨으로 보고,
    # 빌드 출처(build-info.json)에 " M game/taisei"가 남는다(이슈 #4).
    # 그래서 실제 내용 변경이 없을 때만 추적 파일 전체를 커밋과 같은 LF로 다시 체크아웃한다.
    # core.autocrlf=true 기준 상태는 줄바꿈 차이를 무시하므로 실제 수정만 드러난다.
    $realChanges = @(git -C $taiseiPath -c core.autocrlf=true status --porcelain --untracked-files=no --ignore-submodules=all)
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to inspect the Taisei working tree.'
    }
    git -C $taiseiPath config core.autocrlf false
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to set core.autocrlf=false for Taisei.'
    }
    if ($realChanges.Count -gt 0) {
        Write-Warning "game/taisei has $($realChanges.Count) locally modified file(s); skipped LF re-checkout to keep them. Build provenance will record them as dirty."
    } else {
        $crlfCount = @(git -C $taiseiPath ls-files --eol | Where-Object { $_ -match '^i/lf\s+w/crlf\s' }).Count
        if ($LASTEXITCODE -ne 0) {
            throw 'Failed to list Taisei line endings.'
        }
        if ($crlfCount -gt 0) {
            # 위 상태 조회가 인덱스에 CRLF 파일의 시각·크기를 "깨끗함"으로 캐시하므로,
            # 파일만 다시 써서는 크기 불일치로 계속 수정됨으로 보인다. 인덱스를 지우고 HEAD에서 다시 만든다.
            # reset --hard는 추적 파일만 LF로 다시 쓰며 미추적 파일과 하위 submodule은 건드리지 않는다.
            # 실제 수정·스테이징이 없음을 위에서 확인했으므로 잃는 내용은 없다.
            $indexPath = (git -C $taiseiPath rev-parse --path-format=absolute --git-path index).Trim()
            if ($LASTEXITCODE -ne 0 -or -not $indexPath) {
                throw 'Failed to locate the Taisei index.'
            }
            Remove-Item -LiteralPath $indexPath -Force
            git -C $taiseiPath reset --hard --quiet HEAD
            if ($LASTEXITCODE -ne 0) {
                throw 'Failed to re-checkout Taisei files with LF line endings.'
            }
        }
        $stillCrlf = @(git -C $taiseiPath ls-files --eol | Where-Object { $_ -match '^i/lf\s+w/crlf\s' })
        $remaining = @(git -C $taiseiPath status --porcelain --untracked-files=no --ignore-submodules=all)
        if ($stillCrlf.Count -gt 0 -or $remaining.Count -gt 0) {
            throw "game/taisei still has $($stillCrlf.Count) CRLF file(s) and $($remaining.Count) modified file(s) after LF re-checkout."
        }
        Write-Host "game/taisei working tree uses LF line endings (re-checked out $crlfCount CRLF file(s), no local changes)."
    }

    Write-Host "Taisei commit: $(git -C $taiseiPath rev-parse HEAD)"
    git -C $taiseiPath remote -v
    git submodule status --recursive
} finally {
    Pop-Location
}
