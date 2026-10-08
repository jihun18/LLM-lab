param(
    [ValidateSet('qwen3:1.7b', 'qwen3:4b-instruct', 'qwen2.5:7b-instruct')]
    [string]$Model = 'qwen3:1.7b',
    [switch]$Run,
    [switch]$PrepareModel,
    [switch]$ProfileTimings
)
$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw 'Project virtual-environment Python not found. No packages were installed.'
}
$taskArgs = @((Join-Path $PSScriptRoot 'memory_launch.py'))
$taskArgs += @('--model', $Model)
if ($Run -or $PrepareModel) {
    $taskArgs += '--confirm-interactively'
}
if ($Run) { $taskArgs += '--run' }
if ($PrepareModel) { $taskArgs += '--prepare-model' }
if ($ProfileTimings) { $taskArgs += '--profile-timings' }
& $taskPython @taskArgs
exit $LASTEXITCODE
