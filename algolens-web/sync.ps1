Write-Host "📝 本日の作業記録を作成します..." -ForegroundColor Cyan
$date = Get-Date -Format "yyyy-MM-dd"; $time = Get-Date -Format "HH:mm"
$logDir = "docs/logs"; if (!(Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force }
$filename = "${logDir}/${date}.md"
Write-Host "--- 今日の振り返り ---" -ForegroundColor Yellow
$title = Read-Host "【1/4】今日実装した主な機能やトピックは？"
$done  = Read-Host "【2/4】具体的な作業内容は？"
$stuck = Read-Host "【3/4】つまずいた点や、どう解決した？"
$next  = Read-Host "【4/4】次回やりたいことは？"
$template = "`n# AlgoLens 開発日報 ($date)`n`n## 🕒 完了時刻`n- $time`n`n## ✅ 実装内容: $title`n$done`n`n## 🚧 つまずいた点・学んだこと`n$stuck`n`n## 🚀 次回の目標`n$next`n`n---`n"
if (Test-Path $filename) { Add-Content -Path $filename -Value $template -Encoding utf8 } else { $template | Out-File -FilePath $filename -Encoding utf8 }
Write-Host "`n🚀 GitHubに同期しています..." -ForegroundColor Cyan
git add .; git commit -m "docs: Add progress log for $date - $title"; git push origin main
Write-Host "`n✅ すべて完了しました！お疲れ様でした！" -ForegroundColor Green
