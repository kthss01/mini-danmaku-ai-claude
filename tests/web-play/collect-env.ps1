[CmdletBinding()]
param(
    # 서빙 루트(예: build\web\site). 지정하면 산출물의 수정 시각·SHA-256·manifest 유무를 함께 출력한다.
    [string]$SiteDirectory
)

# 웹 플레이 검증 기록(EVIDENCE_TEMPLATE.md)을 채우기 위한 정보를 Markdown으로 출력한다.
# 환경·커밋뿐 아니라 작업 트리의 미커밋 변경과 산출물 출처(provenance)를 함께 남긴다.
# 읽기 전용이며 어떤 파일도 수정하지 않는다.

$ErrorActionPreference = 'Continue'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path

function Get-CommandVersion {
    param([string]$Name, [string[]]$Arguments)
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) { return '(없음)' }
    try {
        $out = & $cmd.Source @Arguments 2>$null | Select-Object -First 1
        if ($out) { return "$out" }
        return '(버전 확인 실패)'
    } catch {
        return '(버전 확인 실패)'
    }
}

function Get-BrowserVersion {
    param([string]$DisplayName, [string[]]$ExecutablePaths)
    # 실행 파일의 버전 정보를 읽는다. 레지스트리 설치 항목보다 설치 위치 차이에 덜 민감하다.
    foreach ($path in $ExecutablePaths) {
        if ($path -and (Test-Path -LiteralPath $path)) {
            $version = (Get-Item -LiteralPath $path).VersionInfo.ProductVersion
            if ($version) { return "$DisplayName $version" }
        }
    }
    return "$DisplayName (설치 확인 불가)"
}

function Write-Table {
    param([System.Collections.Specialized.OrderedDictionary]$Rows)
    Write-Output '| 항목 | 값 |'
    Write-Output '| --- | --- |'
    foreach ($key in $Rows.Keys) {
        Write-Output "| $key | $($Rows[$key]) |"
    }
}

$os = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$gpus = (Get-CimInstance Win32_VideoController | ForEach-Object { $_.Name }) -join ', '
Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue
$resolution = ([System.Windows.Forms.Screen]::AllScreens | ForEach-Object { "$($_.Bounds.Width)x$($_.Bounds.Height)" }) -join ', '

$mainCommit = (git -C $repoRoot rev-parse HEAD 2>$null)
$mainBranch = (git -C $repoRoot rev-parse --abbrev-ref HEAD 2>$null)
# submodule이 초기화되지 않으면 git이 상위 저장소 커밋을 돌려주므로 .git 존재를 먼저 확인한다.
$taiseiPath = Join-Path $repoRoot 'game\taisei'
if (Test-Path -LiteralPath (Join-Path $taiseiPath '.git')) {
    $taiseiCommit = (git -C $taiseiPath rev-parse HEAD 2>$null)
} else {
    $taiseiCommit = '(submodule 미초기화)'
}

$programFilesX86 = [Environment]::GetEnvironmentVariable('ProgramFiles(x86)')

$rows = [ordered]@{
    '검증일'           = (Get-Date -Format 'yyyy-MM-dd HH:mm')
    'OS'               = "$($os.Caption) $($os.Version)"
    'CPU'              = $cpu.Name
    'GPU'              = $gpus
    '해상도'           = $resolution
    'Chrome'           = Get-BrowserVersion 'Google Chrome' @(
        (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'),
        $(if ($programFilesX86) { Join-Path $programFilesX86 'Google\Chrome\Application\chrome.exe' }),
        (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe'))
    'Edge'             = Get-BrowserVersion 'Microsoft Edge' @(
        $(if ($programFilesX86) { Join-Path $programFilesX86 'Microsoft\Edge\Application\msedge.exe' }),
        (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'))
    'Git'              = Get-CommandVersion 'git' @('--version')
    'Docker'           = Get-CommandVersion 'docker' @('--version')
    'Python'           = Get-CommandVersion 'python' @('--version')
    '메인 브랜치'      = $mainBranch
    '메인 커밋'        = $mainCommit
    'game/taisei 커밋' = $taiseiCommit
}

Write-Output '## 환경'
Write-Output ''
Write-Table $rows

# 작업 트리 상태: 커밋 SHA만으로는 미커밋 변경이나 이전 산출물로 검증한 경우를 구분할 수 없다.
Write-Output ''
Write-Output '## 작업 트리'
Write-Output ''
Write-Output '```text'
$porcelain = @(git -C $repoRoot status --porcelain 2>$null)
Write-Output "git status --porcelain: $($porcelain.Count)개 항목"
foreach ($line in $porcelain) { Write-Output $line }
Write-Output 'git submodule status --recursive:'
$submodules = @(git -C $repoRoot submodule status --recursive 2>$null)
if ($submodules.Count -eq 0) { Write-Output '(출력 없음)' }
foreach ($line in $submodules) { Write-Output $line }
Write-Output '```'

if ($SiteDirectory) {
    Write-Output ''
    Write-Output '## 산출물 출처'
    Write-Output ''
    # 상대 경로는 현재 위치 기준, 절대 경로는 그대로 사용한다.
    if ([System.IO.Path]::IsPathRooted($SiteDirectory)) {
        $sitePath = [System.IO.Path]::GetFullPath($SiteDirectory)
    } else {
        $sitePath = [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $SiteDirectory))
    }
    if (-not (Test-Path -LiteralPath $sitePath)) {
        Write-Output "서빙 루트를 찾을 수 없음: $sitePath"
    } else {
        $site = [ordered]@{ '서빙 루트' = $sitePath }
        # 빌드 시각·버전을 남기는 manifest 종류의 파일이 있으면 경로를 기록한다. 없으면 '없음'으로 둔다.
        $manifest = Get-ChildItem -LiteralPath $sitePath -File -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match '^(manifest|build-info|version|BUILD)\.(json|txt|md)$' } |
            Select-Object -First 1
        if ($manifest) { $site['manifest'] = $manifest.Name } else { $site['manifest'] = '없음 (출처는 빌드 로그로 확인)' }
        foreach ($name in @('taisei.html', 'taisei.js', 'taisei.wasm')) {
            $file = Join-Path $sitePath $name
            if (Test-Path -LiteralPath $file) {
                $item = Get-Item -LiteralPath $file
                $hash = (Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()
                $site["$name 수정 시각"] = $item.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss')
                $site["$name 크기"] = "$($item.Length) bytes"
                $site["$name SHA-256"] = $hash
            } else {
                $site[$name] = '없음'
            }
        }
        $dataDir = Join-Path $sitePath 'data'
        if (Test-Path -LiteralPath $dataDir) {
            $dataFiles = Get-ChildItem -LiteralPath $dataDir -File -Recurse -ErrorAction SilentlyContinue
            $site['data/ 파일 수·용량'] = "$($dataFiles.Count)개, $([math]::Round(($dataFiles | Measure-Object Length -Sum).Sum / 1MB, 1)) MB"
        }
        Write-Table $site
    }
}
