# 註冊 Windows 工作排程器：每 10 分鐘（暫定）跑一次 `legion tick`（真實 agent）
# 使用者層級、「只在使用者登入時執行」、不需管理員權限（2026-11-11 已實測此模式可用訂閱登入，見 02_data/env_check.md）
# 已知限制：電腦關機或 Claude 未登入時不會動。
# 用法：
#   powershell -ExecutionPolicy Bypass -File scripts\register_schedule.ps1            # 註冊
#   powershell -ExecutionPolicy Bypass -File scripts\register_schedule.ps1 -Unregister # 移除
param(
  [int]$IntervalMinutes = 10,
  [string]$Backend = 'claude',
  [switch]$Unregister
)
$ErrorActionPreference = 'Stop'
$taskName = 'agent-legion-tick'
if ($Unregister) {
  Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
  Write-Output "已移除排程 $taskName"
  exit 0
}
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root '.venv\Scripts\python.exe'
$log = Join-Path $root '.legion_tmp\tick.log'
New-Item -ItemType Directory -Force (Split-Path $log) | Out-Null
$cmd = "/c `"`"$py`" -m legion tick --backend $Backend >> `"$log`" 2>&1`""
$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument $cmd -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes) -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
  -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings `
  -Force | Out-Null
Write-Output "已註冊排程 $taskName：每 $IntervalMinutes 分鐘執行一次（log：$log）"
