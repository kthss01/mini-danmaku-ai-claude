[CmdletBinding()]
param(
    [ValidateSet('gl33', 'null')]
    [string]$Renderer = 'gl33'
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$installPath = Join-Path $repoRoot 'build\taisei-windows-x64'
$executable = Join-Path $installPath 'taisei.exe'
$storagePath = Join-Path $installPath 'runtime-data'

if (-not (Test-Path -LiteralPath $executable)) {
    throw 'Taisei is not built. Run scripts/build-taisei.ps1 first.'
}

New-Item -ItemType Directory -Force -Path $storagePath | Out-Null
$env:TAISEI_STORAGE_PATH = $storagePath
$env:TAISEI_CACHE_PATH = Join-Path $storagePath 'cache'

Push-Location $installPath
try {
    & $executable --renderer $Renderer
} finally {
    Pop-Location
}
