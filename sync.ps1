# --- sync.ps1 ---
Write-Host "📝 本日の作業記録を作成します..." -ForegroundColor Cyan

# 1. 保存先フォルダとファイル名の設定
$date = Get-Date -Format "yyyy-MM-dd"
$time = Get-Date -Format "HH:mm"
$logDir = "docs/logs"
if (!(Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force }
$filename = "${logDir}/${date}.md"

# 2. ユーザーへの質問（ポートフォリオのネタになります）
Write-Host "--- 今日の振り返り ---" -ForegroundColor Yellow
$title = Read-Host "【1/4】今日実装した主な機能やトピックは？"
$done  = Read-Host "【2/4】具体的な作業内容は？"
$stuck = Read-Host "【3/4】つまずいた点や、どう解決した？"
$next  = Read-Host "【4/4】次回やりたいことは？"

# 3. Markdownファイルの生成
$template = @"
# AlgoLens 開発日報 ($date)

## 🕒 完了時刻
- $time

## ✅ 実装内容: $title
$done

## 🚧 つまずいた点・学んだこと
$stuck

## 🚀 次回の目標
$next

---
"@

# 既存のファイルがある場合は追記、なければ新規作成
if (Test-Path $filename) {
    $template = "`n" + $template
    Add-Content -Path $filename -Value $template -Encoding utf8
} else {
    $template | Out-File -FilePath $filename -Encoding utf8
}

# 4. GitHubへ送信
Write-Host "`n🚀 GitHubに同期しています..." -ForegroundColor Cyan
git add .
git commit -m "docs: Add progress log for $date - $title"
git push origin main

Write-Host "`n✅ すべて完了しました！お疲れ様でした！" -ForegroundColor Green
