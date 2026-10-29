[CmdletBinding()]
param(
    # 컴파일을 건너뛰고 기존 install 결과로 site만 다시 구성한다.
    [switch]$PackageOnly,
    # 기존 install 결과를 지우고 다시 컴파일한다.
    [switch]$Force,
    # release: 공개 배포용 빌드(build/web). developer: AI 실험용 개발자 빌드(build/web-dev, -Ddeveloper=true).
    [ValidateSet('release', 'developer')]
    [string]$Flavor = 'release'
)

# Taisei를 Emscripten(WebAssembly)으로 빌드하고 서빙 가능한 사이트로 패키징한다.
#
# 산출물 계약 (이슈 #4):
#   build/web/install/                meson install 원본 (중간 산출물). 개발자 빌드는 build/web-dev/ 아래에 같은 구조
#   build/web/install-provenance.json install을 만든 빌드의 출처 (컴파일 성공 시에만 기록)
#   build/web/site/                   최종 서빙 루트
#     ├── (web/의 정적 셸 파일, web/game/ 제외)
#     ├── COPYING.txt
#     ├── build-info.json   build: 빌드 출처, packaging: 패키징 정보, site: 파일 해시
#     └── game/          taisei.html, taisei.js, taisei.wasm, data/ ... (+ web/game/ 덮어쓰기)
#
# 개발자 빌드(-Flavor developer, 이슈 #20)는 같은 구조를 build/web-dev/ 아래에 만든다.
# 릴리스 산출물(build/web)과 출처 기록은 건드리지 않는다. 치트·디버그 인자(--sid 등)가 켜지므로
# 원본 규칙 보존 여부는 검증 전까지 미확정(build.rulesPreserved = "unverified")으로 기록한다.
#
# 게임 리소스는 실행 HTML 문서 기준 상대 URL(data/<sha256>)로 내려받으므로
# createTaisei를 호출하는 페이지는 반드시 site/game/ 안에 있어야 한다.

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
# 하위 경로는 '/'로 적는다. Windows와 Linux(GitHub Actions의 pwsh) 모두에서 같은 경로가 된다.
$taiseiPath = Join-Path $repoRoot 'game/taisei'
$configDir = Join-Path $repoRoot 'configs/web-build'
$webSourceDir = Join-Path $repoRoot 'web'
# 산출물 위치와 meson 옵션은 빌드 종류에 따라 정해진다.
$buildDirName = if ($Flavor -eq 'developer') { 'web-dev' } else { 'web' }
# 공통 옵션(-Dbuild.cpp_std)은 container-build.sh가 넣고, 여기서는 빌드 종류별 추가 옵션만 정한다.
$extraMesonOptions = @()
if ($Flavor -eq 'developer') { $extraMesonOptions += '-Ddeveloper=true' }
$mesonOptions = @('-Dbuild.cpp_std=gnu++14') + $extraMesonOptions
$webBuildDir = Join-Path $repoRoot "build/$buildDirName"
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

function Get-DataManifest {
    # install/data의 파일 이름 → {bytes, sha256} 목록. 이름순으로 정렬해 비교가 결정적이도록 한다.
    param([string]$DataPath)
    $manifest = [ordered]@{}
    foreach ($file in @(Get-ChildItem -LiteralPath $DataPath -File | Sort-Object Name)) {
        $manifest[$file.Name] = [ordered]@{
            bytes  = $file.Length
            sha256 = Get-Sha256 $file.FullName
        }
    }
    return $manifest
}

function Test-InstallData {
    # install/data가 빌드 출처에 기록된 목록과 정확히 같은지(누락·추가·크기·내용) 확인한다.
    # 약 207 MiB를 모두 읽어 해시하므로 수 초가 걸리지만, 잘못된 산출물을 성공으로 패키징하는 것보다 낫다.
    param([string]$DataPath, $Recorded)
    if (-not (Test-Path -LiteralPath $DataPath -PathType Container)) {
        throw "build/$buildDirName/install/data is missing or is not a directory. Rebuild with -Force."
    }
    # 이전 형식의 출처 기록에는 data 목록이 없다. 출처 미확인으로 보고 거부한다.
    if ($null -eq $Recorded) {
        throw "install-provenance.json has no data manifest (older format), so build/$buildDirName/install/data cannot be verified. Rebuild with -Force."
    }
    $expected = @($Recorded.PSObject.Properties | ForEach-Object { $_.Name })
    if ($expected.Count -eq 0) {
        throw 'install-provenance.json has an empty data manifest. Rebuild with -Force.'
    }
    $actual = @(Get-ChildItem -LiteralPath $DataPath -File | Sort-Object Name)
    $actualNames = @($actual | ForEach-Object { $_.Name })
    $missing = @($expected | Where-Object { $actualNames -notcontains $_ })
    $extra = @($actualNames | Where-Object { $expected -notcontains $_ })
    if ($missing.Count -gt 0 -or $extra.Count -gt 0) {
        $detail = @()
        if ($missing.Count -gt 0) { $detail += "missing $($missing.Count) (e.g. $($missing[0]))" }
        if ($extra.Count -gt 0) { $detail += "unexpected $($extra.Count) (e.g. $($extra[0]))" }
        throw "build/$buildDirName/install/data does not match install-provenance.json: $($detail -join '; '). Rebuild with -Force."
    }
    foreach ($file in $actual) {
        $record = $Recorded.($file.Name)
        if ($file.Length -ne $record.bytes) {
            throw "build/$buildDirName/install/data/$($file.Name) size differs from install-provenance.json. Rebuild with -Force."
        }
        if ((Get-Sha256 $file.FullName) -ne $record.sha256) {
            throw "build/$buildDirName/install/data/$($file.Name) content differs from install-provenance.json. Rebuild with -Force."
        }
    }
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
            throw "build/$buildDirName/install already exists. Use -Force to rebuild, or -PackageOnly to repackage it."
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
            --env "INSTALL_PREFIX=/workspace/build/$buildDirName/install" `
            --env "MESON_EXTRA_OPTS=$($extraMesonOptions -join ' ')" `
            $image sh "/workspace/build/$buildDirName/.container-build.sh"
    }
    if ($buildExit -ne 0) {
        throw "Taisei web build failed with exit code $buildExit."
    }
    foreach ($name in $trackedInstallFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $installPath $name))) {
            throw "build/$buildDirName/install/$name is missing. The web build did not complete."
        }
    }
    $installDataPath = Join-Path $installPath 'data'
    if (-not (Test-Path -LiteralPath $installDataPath)) {
        throw "build/$buildDirName/install/data is missing. The web build did not complete."
    }

    $installOutputs = [ordered]@{}
    foreach ($name in $trackedInstallFiles) {
        $installOutputs[$name] = Get-Sha256 (Join-Path $installPath $name)
    }
    # data/는 콘텐츠 주소 방식(파일 이름 = 내용 SHA-256)이지만, 이름에 의존하지 않고 전체 목록과 해시를 그대로 기록한다.
    $dataManifest = Get-DataManifest $installDataPath
    $dataContentAddressed = $true
    # Windows PowerShell 5.1의 Measure-Object는 해시테이블 키를 속성으로 읽지 못하므로 직접 합산한다.
    [long]$dataTotalBytes = 0
    foreach ($entry in $dataManifest.GetEnumerator()) {
        if ($entry.Key -ne $entry.Value.sha256) { $dataContentAddressed = $false }
        $dataTotalBytes += $entry.Value.bytes
    }
    # 컴파일에 성공한 경우에만 install과 짝을 이루는 빌드 출처를 기록한다.
    $buildRecord = [ordered]@{
        schema                     = 1
        flavor                     = $Flavor
        mesonOptions               = $mesonOptions
        rulesPreserved             = $(if ($Flavor -eq 'developer') { 'unverified' } else { 'original' })
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
        dataFileCount              = $dataManifest.Count
        dataTotalBytes             = $dataTotalBytes
        dataContentAddressed       = $dataContentAddressed
        dataSha256                 = $dataManifest
    }
    Write-JsonFile $provenancePath $buildRecord | Out-Null
}

# 2. 빌드 출처 확인: 출처가 기록되지 않았거나 install이 바뀐 경우 패키징하지 않는다.
if (-not (Test-Path -LiteralPath $installPath)) {
    throw "build/$buildDirName/install is missing. Run scripts/build-web.ps1 -Flavor $Flavor first."
}
if (-not (Test-Path -LiteralPath $provenancePath)) {
    throw "build/$buildDirName/install-provenance.json is missing, so the origin of build/$buildDirName/install is unknown. Rebuild with -Force."
}
$provenance = Get-Content -LiteralPath $provenancePath -Raw -Encoding UTF8 | ConvertFrom-Json
# flavor가 없는 출처 기록은 이 변경 이전에 만든 릴리스 빌드다. 개발자 빌드는 항상 flavor를 기록한다.
$recordedFlavor = if ($provenance.PSObject.Properties.Name -contains 'flavor') { $provenance.flavor } else { 'release' }
if ($recordedFlavor -ne $Flavor) {
    throw "build/$buildDirName/install-provenance.json records flavor '$recordedFlavor', not '$Flavor'. Rebuild with -Force."
}
foreach ($name in $trackedInstallFiles) {
    $file = Join-Path $installPath $name
    if (-not (Test-Path -LiteralPath $file)) {
        throw "build/$buildDirName/install/$name is missing. Rebuild with -Force."
    }
    if ((Get-Sha256 $file) -ne $provenance.installSha256.$name) {
        throw "build/$buildDirName/install/$name does not match install-provenance.json. Rebuild with -Force."
    }
}
# data/ 누락·추가·변조를 모두 확인한다. 실패하면 기존 site는 그대로 남는다.
Test-InstallData (Join-Path $installPath 'data') $provenance.dataSha256

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
# 진입점: 세션 3의 게임 셸(game/index.html)이 있으면 그것, 없으면 업스트림 셸(game/taisei.html).
$entry = 'game/taisei.html'
if (Test-Path -LiteralPath (Join-Path $siteGamePath 'index.html')) {
    $entry = 'game/index.html'
}
$siteHashes = [ordered]@{}
foreach ($relative in @('index.html', 'COPYING.txt', 'game/index.html', 'game/shell.js', 'game/shell.css', 'game/shell-config.js', 'game/taisei.html', 'game/taisei.js', 'game/taisei.wasm', 'game/COPYING.txt')) {
    $file = Join-Path $sitePath $relative
    if (Test-Path -LiteralPath $file) {
        $siteHashes[$relative] = Get-Sha256 $file
    }
}
# web/에서 복사한 셸 파일 전체의 해시. web/와 site/의 상대 경로가 같으므로 그대로 대응한다.
$shellHashes = [ordered]@{}
$webShellDirty = @()
if ($webShellPresent) {
    $webShellDirty = Get-GitDirtyEntries $repoRoot @('web')
    foreach ($file in @(Get-ChildItem -LiteralPath $webSourceDir -Recurse -File | Sort-Object FullName)) {
        $relative = $file.FullName.Substring($webSourceDir.Length + 1).Replace('\', '/')
        $shellHashes[$relative] = Get-Sha256 (Join-Path $sitePath $relative)
    }
}
$siteFiles = @(Get-ChildItem -LiteralPath $sitePath -Recurse -File)
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
        webShellSha256         = $shellHashes
    }
    site      = [ordered]@{
        entry                        = $entry
        fileCountExcludingBuildInfo  = $siteFiles.Count
        totalBytesExcludingBuildInfo = ($siteFiles | Measure-Object -Property Length -Sum).Sum
        sha256                       = $siteHashes
    }
}
$infoJson = Write-JsonFile (Join-Path $sitePath 'build-info.json') $info

Write-Host "Packaged Taisei web $($provenance.taiseiCommit) (emscripten $($provenance.emscriptenVersion)) into build/$buildDirName/site (entry: $entry)"
# data 목록은 길어서 콘솔에는 요약만 출력한다. 전체 내용은 build-info.json에 있다.
$summary = [ordered]@{
    build     = [ordered]@{
        flavor = $recordedFlavor; taiseiCommit = $provenance.taiseiCommit; repositoryCommit = $provenance.repositoryCommit
        buildStartedAtUtc = $provenance.buildStartedAtUtc; emscriptenVersion = $provenance.emscriptenVersion
        dataFileCount = $provenance.dataFileCount; dataTotalBytes = $provenance.dataTotalBytes
        installSha256 = $provenance.installSha256
    }
    packaging = $info.packaging
    site      = $info.site
}
Write-Host ($summary | ConvertTo-Json -Depth 8)
