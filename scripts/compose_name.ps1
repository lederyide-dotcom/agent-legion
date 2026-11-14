# 印出 docker compose 專案名稱：一律用主 repo 資料夾名稱（git worktree 也一樣），
# 讓在 worktree 或其他資料夾跑 start.bat 時沿用同一個 legion-db 容器與資料 volume，不會另建同名容器。
# 正規化與 compose 預設相同：小寫、只留 a-z 0-9 _ -、去掉開頭的 _ 與 -。
# 不是 git repo、沒有 git、git 報錯時，退回用本資料夾名稱（與 compose 預設一致）。
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$dir = $root
if (Get-Command git -ErrorAction SilentlyContinue) {
    try {
        $common = & git -C $root rev-parse --path-format=absolute --git-common-dir 2>$null
        if ($LASTEXITCODE -eq 0 -and $common) { $dir = Split-Path -Parent ([string]$common).Trim() }
    } catch {
        $dir = $root
    }
}
$name = ((Split-Path -Leaf $dir).ToLowerInvariant() -creplace '[^a-z0-9_-]', '').TrimStart('_', '-')
if (-not $name) { exit 1 }
Write-Output $name