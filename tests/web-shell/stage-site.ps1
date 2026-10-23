[CmdletBinding()]
param(
    # 검증용 사이트를 만들 디렉터리(저장소 밖 임시 경로 권장). 기존 내용은 지운다.
    [Parameter(Mandatory = $true)][string]$Out,
    # 실제 빌드 산출물 디렉터리(taisei.js/taisei.wasm/data/ 포함). -Mock과 함께 쓰지 않는다.
    [string]$Game,
    # 가짜 로더(mock-taisei.js)를 taisei.js로 배치한다.
    [switch]$Mock
)

# web/ 셸과 게임 산출물(또는 mock)을 한 디렉터리에 모아 로컬 HTTP로 검증할 수 있게 한다.
# 세션 1의 패키징 명령을 대체하지 않으며 셸 검증 전용이다.

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$webDir = Join-Path $repoRoot 'web'

if ($Mock -and $Game) { throw 'Use either -Mock or -Game, not both.' }
if (-not $Mock -and -not $Game) { throw 'Specify -Mock or -Game <build directory>.' }

if (Test-Path -LiteralPath $Out) {
    Remove-Item -LiteralPath $Out -Recurse -Force
}
New-Item -ItemType Directory -Path $Out | Out-Null
$Out = (Resolve-Path -LiteralPath $Out).Path

# 세션 1의 패키징 규칙(docs/web/BUILD.md)과 같은 배치: web/game/ 제외 파일은 루트로, web/game/*는 game/으로.
$gameOut = Join-Path $Out 'game'
New-Item -ItemType Directory -Path $gameOut | Out-Null
Get-ChildItem -LiteralPath $webDir -Force |
    Where-Object { $_.Name -ne 'game' } |
    ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $Out -Recurse -Force }
Copy-Item -Path (Join-Path $webDir 'game\*') -Destination $gameOut -Recurse -Force

if ($Mock) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'mock-taisei.js') -Destination (Join-Path $gameOut 'taisei.js')
    Set-Content -LiteralPath (Join-Path $gameOut 'COPYING.txt') -Value 'mock license placeholder' -Encoding utf8
    Write-Host "Staged mock site at $Out"
} else {
    $Game = (Resolve-Path -LiteralPath $Game).Path
    foreach ($required in @('taisei.js', 'taisei.wasm', 'data')) {
        if (-not (Test-Path -LiteralPath (Join-Path $Game $required))) {
            throw "Game build is missing $required in $Game"
        }
    }
    foreach ($name in @('taisei.js', 'taisei.wasm', 'background.webp', 'scythe.webp', 'favicon.ico', 'COPYING.txt', 'README.txt')) {
        $src = Join-Path $Game $name
        if (Test-Path -LiteralPath $src) { Copy-Item -LiteralPath $src -Destination $gameOut }
    }
    Copy-Item -LiteralPath (Join-Path $Game 'data') -Destination (Join-Path $gameOut 'data') -Recurse
    Write-Host "Staged real game site at $Out (from $Game)"
}

Get-ChildItem -LiteralPath $gameOut -File | Select-Object Name, Length
Write-Host "Serve with: python -m http.server 8090 --bind 127.0.0.1 --directory `"$Out`"  (open /index.html)"
