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
#   build/web/install/                meson install 원본 (중간 산출물)
#   build/web/install-provenance.json install을 만든 빌드의 출처 (컴파일 성공 시에만 기록)
#   build/web/site/                   최종 서빙 루트
#     ├── (web/의 정적 셸 파일, web/game/ 제외)
#     ├── COPYING.txt
#     ├── build-info.json   build: 빌드 출처, packaging: 패키징 정보, site: 파일 해시
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
$provenancePath = Join-Path $webBuildDir 'install-provenance.json'
$sitePath = Join-Path $webBuildDir 'site'
$siteGamePath = Join-Path $sitePath 'game'

# 공식 CI(.github/workflows/main.yml의 emscripten-test-build)와 같은 이미지·버전을 사용한다.
$image = 'taiseiproject/linux-toolkit:20260804@sha256:1104b4a5bba4d7f03f7d03cd6990571b476afe276c97d9d8074c33b1834474b2'
$emVersion = '5.0.3'
# emsdk 설치본은 재빌드 시간을 줄이기 위해 Docker named volume에 캐시한다.
$emsdkVolume = "taisei-emsdk-$emVersion"
$requiredGameFiles = @('taisei.html', 'taisei.js', 'taisei.wasm')
# 빌드 출처에 해시를 남겨 install 변조·교체를 감지하는 파일
$trackedInstallFiles = $requiredGameFiles + @('COPYING.txt')
# 빌드 결과에 영향을 주는 메인 저장소 입력 파일
$buildInputFiles = @('scripts/build-web.ps1', 'configs/web-build/container-build.sh', 'configs/web-build/emscripten-toolchain.ini')

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

function Get-Sha256 {
    param([string]$Path)
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
}

function Get-GitCommit {
    param([string]$RepoPath)
    $commit = (git -C $RepoPath rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[0-9a-f]{40}$') {
        throw "Could not determine the commit of $RepoPath."
    }
    return $commit
}

function Get-GitDirtyEntries {
    # 미커밋 변경 목록(git status --porcelain)을 반환한다. 경로를 주면 해당 경로로 한정한다.
    param([string]$RepoPath, [string[]]$Paths = @())
    $lines = @(git -C $RepoPath status --porcelain -- @Paths)
    if ($LASTEXITCODE -ne 0) {
        throw "git status failed in $RepoPath."
    }
    return , @($lines | Where-Object { $_ })
}

function Write-JsonFile {
    param([string]$Path, $Value)
    $json = $Value | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText($Path, $json, (New-Object System.Text.UTF8Encoding($false)))
    return $json
}

if (-not (Test-Path -LiteralPath (Join-Path $taiseiPath '.git'))) {
    throw 'game/taisei is missing. Run git submodule update --init --recursive and scripts/setup-taisei.ps1 first.'
}

# 1. 컴파일 및 meson install
if (-not $PackageOnly) {
    $taiseiCommit = Get-GitCommit $taiseiPath
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
    # 이전 빌드의 출처 기록이 새 install에 남지 않도록 컴파일 전에 지운다.
    if (Test-Path -LiteralPath $provenancePath) {
        Remove-Item -LiteralPath $provenancePath -Force
    }
    New-Item -ItemType Directory -Force -Path $webBuildDir | Out-Null

    # 빌드 입력 상태는 컴파일 시작 시점 기준으로 기록한다.
    $buildStartedAt = [DateTime]::UtcNow.ToString('o')
    $repositoryCommit = Get-GitCommit $repoRoot
    $repositoryDirty = Get-GitDirtyEntries $repoRoot
    # 컨테이너는 커밋된 Taisei 소스만 빌드하므로 submodule 작업 트리 변경은 참고용으로만 기록한다.
    $taiseiDirty = Get-GitDirtyEntries $taiseiPath
    $buildInputs = [ordered]@{}
    foreach ($relative in $buildInputFiles) {
        $buildInputs[$relative] = Get-Sha256 (Join-Path $repoRoot $relative)
    }

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
    foreach ($name in $trackedInstallFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $installPath $name))) {
            throw "build/web/install/$name is missing. The web build did not complete."
        }
    }
    $installDataPath = Join-Path $installPath 'data'
    if (-not (Test-Path -LiteralPath $installDataPath)) {
        throw 'build/web/install/data is missing. The web build did not complete.'
    }

    $installOutputs = [ordered]@{}
    foreach ($name in $trackedInstallFiles) {
        $installOutputs[$name] = Get-Sha256 (Join-Path $installPath $name)
    }
    # 컴파일에 성공한 경우에만 install과 짝을 이루는 빌드 출처를 기록한다.
    $buildRecord = [ordered]@{
        schema                     = 1
        buildStartedAtUtc          = $buildStartedAt
        buildFinishedAtUtc         = [DateTime]::UtcNow.ToString('o')
        taiseiCommit               = $taiseiCommit
        taiseiWorktreeDirtyEntries = $taiseiDirty
        repositoryCommit           = $repositoryCommit
        repositoryDirtyEntries     = $repositoryDirty
        buildInputsSha256          = $buildInputs
        emscriptenVersion          = $emVersion
        buildImage                 = $image
        installSha256              = $installOutputs
        dataFileCount              = @(Get-ChildItem -LiteralPath $installDataPath -File).Count
    }
    Write-JsonFile $provenancePath $buildRecord | Out-Null
}

# 2. 빌드 출처 확인: 출처가 기록되지 않았거나 install이 바뀐 경우 패키징하지 않는다.
if (-not (Test-Path -LiteralPath $installPath)) {
    throw 'build/web/install is missing. Run scripts/build-web.ps1 first.'
}
if (-not (Test-Path -LiteralPath $provenancePath)) {
    throw 'build/web/install-provenance.json is missing, so the origin of build/web/install is unknown. Rebuild with -Force.'
}
$provenance = Get-Content -LiteralPath $provenancePath -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($name in $trackedInstallFiles) {
    $file = Join-Path $installPath $name
    if (-not (Test-Path -LiteralPath $file)) {
        throw "build/web/install/$name is missing. Rebuild with -Force."
    }
    if ((Get-Sha256 $file) -ne $provenance.installSha256.$name) {
        throw "build/web/install/$name does not match install-provenance.json. Rebuild with -Force."
    }
}

# 3. 패키징: site를 매번 새로 구성한다(생성 디렉터리이므로 안전하게 교체).
# 로컬 서버가 site를 작업 디렉터리로 잡고 있어도 동작하도록 디렉터리 자체가 아닌 내용물만 지운다.
if (Test-Path -LiteralPath $sitePath) {
    Get-ChildItem -LiteralPath $sitePath -Force | Remove-Item -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $siteGamePath | Out-Null
Copy-Item -Path (Join-Path $installPath '*') -Destination $siteGamePath -Recurse

# 세션 3의 정적 셸(web/)을 루트에, web/game/은 게임 디렉터리에 덮어쓴다.
$webShellPresent = Test-Path -LiteralPath $webSourceDir
if ($webShellPresent) {
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

# 라이선스 고지는 현재 작업 트리가 아니라 해당 빌드의 install에 포함된 COPYING.txt를 사용한다.
$buildLicense = Join-Path $installPath 'COPYING.txt'
Copy-Item -LiteralPath $buildLicense -Destination (Join-Path $sitePath 'COPYING.txt') -Force
Copy-Item -LiteralPath $buildLicense -Destination (Join-Path $siteGamePath 'COPYING.txt') -Force

foreach ($name in $requiredGameFiles) {
    if (-not (Test-Path -LiteralPath (Join-Path $siteGamePath $name))) {
        throw "Packaging finished without site/game/$name."
    }
}

# 4. 빌드 정보 기록: 빌드 출처(build)와 이번 패키징 정보(packaging)를 분리한다.
$siteHashes = [ordered]@{}
foreach ($relative in @('index.html', 'COPYING.txt', 'game/taisei.html', 'game/taisei.js', 'game/taisei.wasm', 'game/COPYING.txt')) {
    $file = Join-Path $sitePath $relative
    if (Test-Path -LiteralPath $file) {
        $siteHashes[$relative] = Get-Sha256 $file
    }
}
$siteFiles = @(Get-ChildItem -LiteralPath $sitePath -Recurse -File)
$webShellDirty = @()
if ($webShellPresent) {
    $webShellDirty = Get-GitDirtyEntries $repoRoot @('web')
}
$info = [ordered]@{
    schema    = 1
    build     = $provenance
    packaging = [ordered]@{
        packagedAtUtc          = [DateTime]::UtcNow.ToString('o')
        mode                   = $(if ($PackageOnly) { 'PackageOnly' } else { 'BuildAndPackage' })
        repositoryCommit       = Get-GitCommit $repoRoot
        repositoryDirtyEntries = Get-GitDirtyEntries $repoRoot
        webShellPresent        = $webShellPresent
        webShellDirtyEntries   = $webShellDirty
    }
    site      = [ordered]@{
        entry               = 'game/taisei.html'
        fileCountExcludingBuildInfo = $siteFiles.Count
        totalBytesExcludingBuildInfo = ($siteFiles | Measure-Object -Property Length -Sum).Sum
        sha256              = $siteHashes
    }
}
$infoJson = Write-JsonFile (Join-Path $sitePath 'build-info.json') $info

Write-Host "Packaged Taisei web $($provenance.taiseiCommit) (emscripten $($provenance.emscriptenVersion)) into build/web/site"
Write-Host $infoJson
