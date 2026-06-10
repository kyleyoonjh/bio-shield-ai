# OpenBioShield 로컬 백엔드 시작 스크립트
# 실행: PowerShell 에서 `.\start-backend.ps1`

$Port = 8001

# 기존 Python 프로세스가 포트를 점유하고 있으면 종료
$existing = netstat -ano | Select-String ":$Port\s+.*LISTENING" | ForEach-Object {
    ($_ -split '\s+')[-1]
} | Select-Object -First 1

if ($existing) {
    Write-Host "포트 $Port 사용 중 (PID $existing) — 종료합니다..." -ForegroundColor Yellow
    Stop-Process -Id $existing -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

# 백엔드 디렉토리로 이동 후 uvicorn 시작
$backendDir = Join-Path $PSScriptRoot "backend"
Write-Host "백엔드 시작: http://127.0.0.1:$Port" -ForegroundColor Green
Set-Location $backendDir
uvicorn main:app --host 127.0.0.1 --port $Port
