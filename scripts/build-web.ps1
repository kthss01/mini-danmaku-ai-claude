[CmdletBinding()]
param(
    # 컴파일을 건너뛰고 기존 build/web/install 결과로 site만 다시 구성한다.
    [switch]$PackageOnly,
    # 기존 build/web/install 결과를 지우고 다시 컴파일한다.
    [switch]$Force
)

# Taisei를 Emscripten(WebAssembly)으로 빌드하고 서빙 가능한 사이트로 패키징한다.
#
# 산출물 계약 (이슈 #4):
#   build/web/install/   meson install 원본 (중간 산출물)
#   build/web/site/      최종 서빙 루트
#     ├── (web/의 정적 셸 파일, web/game/ 제외)
#     ├── COPYING.txt
#     ├── build-info.json
#     └── game/          taisei.html, taisei.js, taisei.wasm, data/ ... (+ web/game/ 덮어쓰기)
#
# 게임 리소스는 실행 HTML 문서 기준 상대 URL(data/<sha256>)로 내려받으므로
# createTaisei를 호출하는 페이지는 반드시 site/game/ 안에 있어야 한다.

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taiseiPath = Join-Path $repoRoot 'game\taisei'
$configDir = Join-Path $repoRoot 'configs\web-build'
$webSourceDir = Join-Path $repoRoot 'web'
$webBuildDir = Join-Path $repoRoot 'build\web'
$installPath = Join-Path $webBuildDir 'install'
$sitePath = Join-Path $webBuildDir 'site'
$siteGamePath = Join-Path $sitePath 'game'

# 공식 CI(.github/workflows/main.yml의 emscripten-test-build)와 같은 이미지·버전을 사용한다.
$image = 'taiseiproject/linux-toolkit:20260804@sha256:1104b4a5bba4d7f03f7d03cd6990571b476afe276c97d9d8074c33b1834474b2'
$emVersion = '5.0.3'
# emsdk 설치본은 재빌드 시간을 줄이기 위해 Docker named volume에 캐시한다.
$emsdkVolume = "taisei-emsdk-$emVersion"
$requiredGameFiles = @('taisei.html', 'taisei.js', 'taisei.wasm')

function Invoke-Native {
    # Windows PowerShell 5.1은 네이티브 명령의 stderr를 오류 레코드로 바꾸므로
    # 호출 구간에서만 오류 처리를 완화하고 종료 코드로 판단한다.
    # 출력은 바로 호스트에 표시하고(-Quiet이면 버림) 종료 코드만 반환한다.
    param([scriptblock]$Command, [switch]$Quiet)
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($Quiet) {
            & $Command *> $null
        } else {
            & $Command 2>&1 | ForEach-Object { Write-Host "$_" }
        }
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previous
    }
}

if (-not (Test-Path -LiteralPath (Join-Path $taiseiPath '.git'))) {
    throw 'game/taisei is missing. Run git submodule update --init --recursive and scripts/setup-taisei.ps1 first.'
}
$taiseiCommit = (git -C $taiseiPath rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $taiseiCommit -notmatch '^[0-9a-f]{40}$') {
    throw 'Could not determine the Taisei commit.'
}

# 1. 컴파일 및 meson install
if (-not $PackageOnly) {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker is not installed or is not on PATH.'
    }
    $dockerExit = Invoke-Native -Quiet { docker info }
    if ($dockerExit -ne 0) {
        throw 'Docker Desktop is not running.'
    }
    if (Test-Path -LiteralPath $installPath) {
        if (-not $Force) {
            throw 'build/web/install already exists. Use -Force to rebuild, or -PackageOnly to repackage it.'
        }
        Remove-Item -LiteralPath $installPath -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $webBuildDir | Out-Null

    # Windows 체크아웃에서 CRLF가 될 수 있으므로 LF로 정규화한 복사본을 실행한다.
    $containerScript = Join-Path $webBuildDir '.container-build.sh'
    $scriptText = [System.IO.File]::ReadAllText((Join-Path $configDir 'container-build.sh')).Replace("`r`n", "`n")
    [System.IO.File]::WriteAllText($containerScript, $scriptText, (New-Object System.Text.UTF8Encoding($false)))

    $buildExit = Invoke-Native {
        docker run --rm `
            --volume "${repoRoot}:/workspace" `
            --volume "${emsdkVolume}:/opt/emsdk" `
            --env "EM_VERSION=$emVersion" `
            --env "TAISEI_COMMIT=$taiseiCommit" `
            --env "INSTALL_PREFIX=/workspace/build/web/install" `
            $image sh /workspace/build/web/.container-build.sh
    }
    if ($buildExit -ne 0) {
        throw "Taisei web build failed with exit code $buildExit."
    }
}

foreach ($name in $requiredGameFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $installPath $name))) {
        throw "build/web/install/$name is missing. The web build did not complete."
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $installPath 'data'))) {
    throw 'build/web/install/data is missing. The web build did not complete.'
}

# 2. 패키징: site를 매번 새로 구성한다(생성 디렉터리이므로 안전하게 교체).
# 로컬 서버가 site를 작업 디렉터리로 잡고 있어도 동작하도록 디렉터리 자체가 아닌 내용물만 지운다.
if (Test-Path -LiteralPath $sitePath) {
    Get-ChildItem -LiteralPath $sitePath -Force | Remove-Item -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $siteGamePath | Out-Null
Copy-Item -Path (Join-Path $installPath '*') -Destination $siteGamePath -Recurse

# 세션 3의 정적 셸(web/)을 루트에, web/game/은 게임 디렉터리에 덮어쓴다.
if (Test-Path -LiteralPath $webSourceDir) {
    Get-ChildItem -LiteralPath $webSourceDir -Force |
        Where-Object { $_.Name -ne 'game' } |
        ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $sitePath -Recurse -Force }
    $webGameDir = Join-Path $webSourceDir 'game'
    if (Test-Path -LiteralPath $webGameDir) {
        Copy-Item -Path (Join-Path $webGameDir '*') -Destination $siteGamePath -Recurse -Force
    }
} else {
    Write-Host 'web/ not found; packaging the upstream game shell only.'
}

# Taisei 라이선스 고지(코드·음악·이미지별 조건 포함)를 루트와 게임 디렉터리 모두에 둔다.
$license = Join-Path $taiseiPath 'COPYING.txt'
Copy-Item -LiteralPath $license -Destination (Join-Path $sitePath 'COPYING.txt') -Force
Copy-Item -LiteralPath $license -Destination (Join-Path $siteGamePath 'COPYING.txt') -Force

# 3. 빌드 정보 기록
$mainCommit = (git -C $repoRoot rev-parse HEAD).Trim()
$siteFiles = Get-ChildItem -LiteralPath $sitePath -Recurse -File
$info = [ordered]@{
    taiseiCommit      = $taiseiCommit
    repositoryCommit  = $mainCommit
    emscriptenVersion = $emVersion
    buildImage        = $image
    fileCount         = $siteFiles.Count
    totalBytes        = ($siteFiles | Measure-Object -Property Length -Sum).Sum
    entry             = 'game/taisei.html'
}
$infoJson = $info | ConvertTo-Json
[System.IO.File]::WriteAllText((Join-Path $sitePath 'build-info.json'), $infoJson, (New-Object System.Text.UTF8Encoding($false)))

foreach ($name in $requiredGameFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $siteGamePath $name))) {
        throw "Packaging finished without site/game/$name."
    }
}

Write-Host "Packaged Taisei web $taiseiCommit (emscripten $emVersion) into build/web/site"
Write-Host $infoJson
