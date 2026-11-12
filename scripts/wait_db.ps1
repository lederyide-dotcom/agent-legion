# 等待 legion-db 變成 healthy，印出耗時；超過上限回傳 exit 1
param([int]$TimeoutSeconds = 30)
$t = [Diagnostics.Stopwatch]::StartNew()
do {
  Start-Sleep -Milliseconds 500
  $s = docker inspect -f '{{.State.Health.Status}}' legion-db 2>$null
} while ($s -ne 'healthy' -and $t.Elapsed.TotalSeconds -lt $TimeoutSeconds)
if ($s -ne 'healthy') { Write-Output "DB 在 $TimeoutSeconds 秒內未 healthy（狀態：$s）"; exit 1 }
Write-Output ('DB healthy，耗時 {0:N1} 秒' -f $t.Elapsed.TotalSeconds)
exit 0
