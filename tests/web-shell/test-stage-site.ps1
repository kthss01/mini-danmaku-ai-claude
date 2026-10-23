[CmdletBinding()]
param()

# stage-site.ps1의 원본 삭제 방지 규칙을 임시 fixture로 검증한다. 실제 저장소·빌드 산출물은 건드리지 않는다.
# 실행: powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\web-shell\test-stage-site.ps1  (모두 통과하면 종료 코드 0)

$ErrorActionPreference = 'Stop'
$stage = Join-Path $PSScriptRoot 'stage-site.ps1'
$tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("taisei-shell-test-" + [System.Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $tmp | Out-Null
$failures = @()

function Assert-True($cond, $message) {
    if ($cond) { Write-Host "PASS  $message" } else { Write-Host "FAIL  $message"; $script:failures += $message }
}

function Invoke-Stage {
    param([hashtable]$Arguments)
    # 예외 메시지를 돌려주고, 성공하면 $null
    try {
        & $stage @Arguments *> $null
        return $null
    } catch {
        return $_.Exception.Message
    }
}

try {
    # 가짜 게임 산출물
    $game = Join-Path $tmp 'game-src'
    New-Item -ItemType Directory -Path (Join-Path $game 'data') | Out-Null
    Set-Content -LiteralPath (Join-Path $game 'taisei.js') -Value 'window.createTaisei = async () => ({});'
    Set-Content -LiteralPath (Join-Path $game 'taisei.wasm') -Value 'wasm'
    Set-Content -LiteralPath (Join-Path $game 'data\abc') -Value 'abc'

    # 1. Out == Game: 거부, 원본 보존
    $err = Invoke-Stage @{ Out = $game; Game = $game }
    Assert-True ($err -match 'overlap') "Out == Game is refused ($err)"
    Assert-True (Test-Path (Join-Path $game 'taisei.wasm')) 'Game sources preserved after Out == Game'

    # 2. Out이 Game의 조상: 거부, 원본 보존
    $err = Invoke-Stage @{ Out = $tmp; Game = $game }
    Assert-True ($err -match 'overlap') "Out as ancestor of Game is refused ($err)"
    Assert-True (Test-Path (Join-Path $game 'data\abc')) 'Game data preserved after ancestor Out'

    # 3. Out이 Game의 자손: 거부
    $err = Invoke-Stage @{ Out = (Join-Path $game 'data'); Game = $game }
    Assert-True ($err -match 'overlap') "Out inside Game is refused ($err)"
    Assert-True (Test-Path (Join-Path $game 'data\abc')) 'Game data preserved after descendant Out'

    # 4. Out이 저장소 안(web/): 거부, web/ 보존
    $repoWeb = Join-Path $PSScriptRoot '..\..\web'
    $err = Invoke-Stage @{ Out = $repoWeb; Mock = $true }
    Assert-True ($err -match 'outside the repository') "Out inside repository is refused ($err)"
    Assert-True (Test-Path (Join-Path $repoWeb 'game\index.html')) 'web/game/index.html preserved'

    # 5. 기존 임의 디렉터리(marker 없음): 거부, 내용 보존
    $foreign = Join-Path $tmp 'foreign'
    New-Item -ItemType Directory -Path $foreign | Out-Null
    Set-Content -LiteralPath (Join-Path $foreign 'keep.txt') -Value 'keep'
    $err = Invoke-Stage @{ Out = $foreign; Mock = $true }
    Assert-True ($err -match 'not created by this tool') "Existing directory without marker is refused ($err)"
    Assert-True ((Get-Content (Join-Path $foreign 'keep.txt')) -eq 'keep') 'Foreign directory content preserved'

    # 6. 정상 경로: 새 Out 생성, marker와 game/ 배치
    $out = Join-Path $tmp 'out'
    $err = Invoke-Stage @{ Out = $out; Game = $game }
    Assert-True ($null -eq $err) "Fresh Out with valid Game succeeds ($err)"
    Assert-True (Test-Path (Join-Path $out '.taisei-shell-stage')) 'Marker written'
    Assert-True (Test-Path (Join-Path $out 'index.html')) 'Root index.html staged'
    Assert-True (Test-Path (Join-Path $out 'game\index.html')) 'game/index.html staged'
    Assert-True (Test-Path (Join-Path $out 'game\shell.js')) 'game/shell.js staged'
    Assert-True (Test-Path (Join-Path $out 'game\taisei.wasm')) 'game/taisei.wasm staged'
    Assert-True (Test-Path (Join-Path $out 'game\data\abc')) 'game/data staged'
    Assert-True (-not (Test-Path (Join-Path $out 'shell.js'))) 'shell.js not at root'

    # 7. 입력 누락(Game에 wasm 없음): 기존 marker Out은 보존(검증이 삭제보다 먼저)
    $badGame = Join-Path $tmp 'game-bad'
    New-Item -ItemType Directory -Path (Join-Path $badGame 'data') | Out-Null
    Set-Content -LiteralPath (Join-Path $badGame 'taisei.js') -Value 'x'
    if (Test-Path (Join-Path $out 'game')) {
        Set-Content -LiteralPath (Join-Path $out 'game\sentinel.txt') -Value 'still here'
    }
    $err = Invoke-Stage @{ Out = $out; Game = $badGame }
    Assert-True ($err -match 'missing taisei.wasm') "Invalid Game is refused ($err)"
    Assert-True (Test-Path (Join-Path $out 'game\sentinel.txt')) 'Existing Out untouched when input validation fails'

    # 8. marker 있는 Out 재실행: 내용 교체(sentinel 제거), mock 배치
    $err = Invoke-Stage @{ Out = $out; Mock = $true }
    Assert-True ($null -eq $err) "Re-staging a tool-created Out succeeds ($err)"
    Assert-True (-not (Test-Path (Join-Path $out 'game\sentinel.txt'))) 'Previous content replaced'
    Assert-True ((Get-Content (Join-Path $out 'game\taisei.js') -Raw) -match 'createTaisei') 'Mock loader staged as game/taisei.js'

    # 9. 드라이브 루트: 거부
    $err = Invoke-Stage @{ Out = ([System.IO.Path]::GetPathRoot($tmp)); Mock = $true }
    Assert-True ($err -match 'drive root') "Drive root is refused ($err)"
} finally {
    Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
}

if ($failures.Count) {
    Write-Host "$($failures.Count) failure(s)"
    exit 1
}
Write-Host 'All stage-site safety checks passed'
exit 0
