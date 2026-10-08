param(
    [switch]$Run,
    [switch]$PrepareModel
)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'Project virtual-environment Python not found. No packages were installed.'
}
$taskArgs = @((Join-Path $PSScriptRoot 'memory_launch.py'))
if ($Run -or $PrepareModel) {
    $taskArgs += '--confirm-interactively'
}
if ($Run) { $taskArgs += '--run' }
if ($PrepareModel) { $taskArgs += '--prepare-model' }
& $taskPython @taskArgs
exit $LASTEXITCODE
