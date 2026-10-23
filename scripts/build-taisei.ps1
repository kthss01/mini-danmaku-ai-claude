[CmdletBinding()]
param(
    [string]$OutputDirectory = 'build/taisei-windows-x64',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$taiseiPath = Join-Path $repoRoot 'game\taisei'
$image = 'taiseiproject/linux-toolkit:20260804@sha256:1104b4a5bba4d7f03f7d03cd6990571b476afe276c97d9d8074c33b1834474b2'

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker is not installed or is not on PATH.'
}
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    throw 'Docker Desktop is not running.'
}
if (-not (Test-Path -LiteralPath $taiseiPath)) {
    throw 'game/taisei is missing. Run scripts/setup-taisei.ps1 first.'
}
if ($OutputDirectory -notmatch '^[A-Za-z0-9._/-]+$' -or [System.IO.Path]::IsPathRooted($OutputDirectory)) {
    throw 'OutputDirectory must be a simple path relative to the repository root.'
}

$outputPath = [System.IO.Path]::GetFullPath((Join-Path $repoRoot $OutputDirectory))
if (-not $outputPath.StartsWith($repoRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'OutputDirectory must stay inside the repository.'
}
if (Test-Path -LiteralPath $outputPath) {
    if (-not $Force) {
        throw "$OutputDirectory already exists. Use -Force to replace this generated directory."
    }
    Remove-Item -LiteralPath $outputPath -Recurse -Force
}

$commit = (git -C $taiseiPath rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[0-9a-f]{40}$') {
    throw 'Could not determine the Taisei commit.'
}
$containerOutput = $OutputDirectory.Replace('\', '/')
$containerCommand = @"
set -eu
git clone --recurse-submodules --no-local /workspace/game/taisei /tmp/taisei
cd /tmp/taisei
git checkout $commit
git submodule update --init --recursive
meson setup build/windows-x64 \
  --cross-file misc/ci/common-options.ini \
  --cross-file misc/ci/forcefallback.ini \
  --cross-file misc/ci/windows-llvm_mingw-x86_64-build-test-ci.ini \
  --prefix=/workspace/$containerOutput
meson compile -C build/windows-x64 --verbose
meson install -C build/windows-x64
"@

Push-Location $repoRoot
try {
    docker run --rm --volume "${repoRoot}:/workspace" $image sh -lc $containerCommand
    if ($LASTEXITCODE -ne 0) {
        throw "Taisei build failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}

$executable = Join-Path $outputPath 'taisei.exe'
if (-not (Test-Path -LiteralPath $executable)) {
    throw 'Build completed without producing taisei.exe.'
}

Write-Host "Built Taisei $commit"
Get-FileHash -Algorithm SHA256 -LiteralPath $executable
