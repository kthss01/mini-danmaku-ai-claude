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

    Write-Host "Taisei commit: $(git -C $taiseiPath rev-parse HEAD)"
    git -C $taiseiPath remote -v
    git submodule status --recursive
} finally {
    Pop-Location
}
