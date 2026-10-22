# Stop all HMI displays
# Run on: HMI machine (Windows)

Write-Host "[*] Stopping all HMI processes..."
Get-Process python -ErrorAction SilentlyContinue | Stop-Process -Force
Write-Host "[*] All HMI displays stopped."
