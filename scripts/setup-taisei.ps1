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
    git -C $taiseiPath config core.autocrlf false
    if ($LASTEXITCODE -ne 0) {
        throw 'Failed to set core.autocrlf=false for Taisei.'
    }

    # Windows Git 기본값(core.autocrlf=true)으로 clone하면 Taisei 작업 트리가 CRLF로 체크아웃된다.
    # core.autocrlf=false에서는 줄바꿈만 다른 파일이 수정됨으로 보여 빌드 출처에 " M game/taisei"가 남는다(이슈 #4).
    # 내용이 인덱스와 같음을 확인한 CRLF 파일만 LF로 다시 쓴다. 안전 조건은 scripts/lib/Repair-GitLineEndings.ps1 참고.
    . (Join-Path $PSScriptRoot 'lib\Repair-GitLineEndings.ps1')
    $repair = Repair-GitLineEndings -RepoPath $taiseiPath
    switch ($repair.Action) {
        'normalized' { Write-Host "game/taisei: rewrote $($repair.Count) CRLF file(s) with LF (content verified against the index)." }
        'none' { Write-Host 'game/taisei: working tree already matches the index line endings.' }
        'skipped' {
            $detail = if ($repair.Details.Count -gt 0) { " e.g. $($repair.Details -join ', ')" } else { '' }
            Write-Warning "game/taisei: skipped line-ending normalization because $($repair.Reason).$detail Nothing was changed. Build provenance may record game/taisei as dirty."
        }
    }

    Write-Host "Taisei commit: $(git -C $taiseiPath rev-parse HEAD)"
    git -C $taiseiPath remote -v
    git submodule status --recursive
} finally {
    Pop-Location
}
