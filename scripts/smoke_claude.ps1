# 未查證事項 2、3 的實測：在工作排程器（使用者層級、不需管理員）下跑一次極小的 claude -p，跑完即刪除排程
# 驗證：訂閱登入可用、JSON 輸出欄位、--tools 限縮、deny 規則（以 canary 檔代替 .env）、Bash 白名單外指令被拒
# 用法：powershell -ExecutionPolicy Bypass -File scripts\smoke_claude.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$work = Join-Path $root '.legion_tmp\smoke'
New-Item -ItemType Directory -Force $work | Out-Null
Set-Content -Path (Join-Path $work 'canary_secret.txt') -Value 'CANARY-7f3a-DO-NOT-LEAK' -Encoding ascii

$settings = @{
  permissions = @{
    deny  = @('Read(**/canary_secret.txt)', 'Read(**/.env)', 'Read(**/.env.*)', 'Bash(*.env*)', 'Bash(*canary_secret*)')
    allow = @('Read', 'Glob', 'Grep', 'Bash(git status *)')
  }
} | ConvertTo-Json -Depth 5
Set-Content -Path (Join-Path $work 'smoke_settings.json') -Value $settings -Encoding ascii

$py = Join-Path $root '.venv\Scripts\python.exe'
$script = Join-Path $root 'scripts\smoke_run.py'
$taskName = 'legion-smoke-once'
$action = New-ScheduledTaskAction -Execute $py -Argument "`"$script`"" -WorkingDirectory $work
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$trigger = New-ScheduledTaskTrigger -Once -At ((Get-Date).AddMinutes(30))
Remove-Item (Join-Path $work 'done.txt') -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Trigger $trigger -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
$deadline = (Get-Date).AddMinutes(4)
while (-not (Test-Path (Join-Path $work 'done.txt')) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 3 }
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
if (-not (Test-Path (Join-Path $work 'done.txt'))) { Write-Output 'TIMEOUT: 排程工作 4 分鐘內未完成'; exit 1 }
Get-Content (Join-Path $work 'done.txt')
