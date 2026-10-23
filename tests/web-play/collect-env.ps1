[CmdletBinding()]
param()

# 웹 플레이 검증 기록(EVIDENCE_TEMPLATE.md)의 환경 표를 채우기 위한 정보를 Markdown 표로 출력한다.
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
        if (Test-Path -LiteralPath $path) {
            $version = (Get-Item -LiteralPath $path).VersionInfo.ProductVersion
            if ($version) { return "$DisplayName $version" }
        }
    }
    return "$DisplayName (설치 확인 불가)"
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

$rows = [ordered]@{
    '검증일'           = (Get-Date -Format 'yyyy-MM-dd HH:mm')
    'OS'               = "$($os.Caption) $($os.Version)"
    'CPU'              = $cpu.Name
    'GPU'              = $gpus
    '해상도'           = $resolution
    'Chrome'           = Get-BrowserVersion 'Google Chrome' @(
        (Join-Path $env:ProgramFiles 'Google\Chrome\Application\chrome.exe'),
        (Join-Path ${env:ProgramFiles(x86)} 'Google\Chrome\Application\chrome.exe'),
        (Join-Path $env:LOCALAPPDATA 'Google\Chrome\Application\chrome.exe'))
    'Edge'             = Get-BrowserVersion 'Microsoft Edge' @(
        (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
        (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe'))
    'Git'              = Get-CommandVersion 'git' @('--version')
    'Docker'           = Get-CommandVersion 'docker' @('--version')
    'Python'           = Get-CommandVersion 'python' @('--version')
    '메인 브랜치'      = $mainBranch
    '메인 커밋'        = $mainCommit
    'game/taisei 커밋' = $taiseiCommit
}

Write-Output '| 항목 | 값 |'
Write-Output '| --- | --- |'
foreach ($key in $rows.Keys) {
    Write-Output "| $key | $($rows[$key]) |"
}
