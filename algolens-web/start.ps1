# AlgoLens Startup Script
# Usage: .\start.ps1

$root = $PSScriptRoot
$venv = "$root\.venv\Scripts"

# Backend
Start-Process powershell -ArgumentList "-NoExit", "-Command",
  "cd '$root\backend'; & '$venv\uvicorn.exe' app.main:app --reload --port 8000"

# Frontend
Start-Process powershell -ArgumentList "-NoExit", "-Command",
  "cd '$root\frontend'; & '$venv\streamlit.exe' run app.py --server.port 8501"

Write-Host "Server Started Successfully!"
Write-Host "  API:       http://localhost:8000/docs"
Write-Host "  Frontend:  http://localhost:8501"