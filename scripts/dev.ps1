param(
    [switch]$Analytics,
    [switch]$Build
)

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $projectRoot

$arguments = @("compose")
if ($Analytics) {
    $arguments += @("--profile", "analytics")
}
$arguments += "up"
if ($Build) {
    $arguments += "--build"
}

& docker @arguments
