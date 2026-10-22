# mrhOTshOT - HMI Machine Setup Script (PowerShell)
# Platform: Windows 10/11
# IP: 192.168.1.55
# Purpose: Setup HMI environment for attack simulation
###############################################################################

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "mrhOTshOT HMI Setup (Windows)" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan
Write-Host ""

# Check if running as Administrator
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host "[!] This script must be run as Administrator" -ForegroundColor Red
    Write-Host "[!] Right-click PowerShell and select 'Run as Administrator'" -ForegroundColor Red
    exit 1
}

Write-Host "[*] Checking Python installation..." -ForegroundColor Yellow

# Check if Python is installed
try {
    $pythonVersion = python --version 2>&1
    Write-Host "[+] Found: $pythonVersion" -ForegroundColor Green
} catch {
    Write-Host "[-] Python not found. Please install Python 3.9+ from https://www.python.org/" -ForegroundColor Red
    Write-Host "[!] Make sure to check 'Add Python to PATH' during installation" -ForegroundColor Yellow
    exit 1
}

Write-Host ""
Write-Host "[*] Installing Python packages..." -ForegroundColor Yellow
python -m pip install --upgrade pip
python -m pip install flask requests c104 pymodbus pypykatz impacket

Write-Host ""
Write-Host "[*] Enabling RDP..." -ForegroundColor Yellow
Set-ItemProperty -Path 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name "fDenyTSConnections" -Value 0
Enable-NetFirewallRule -DisplayGroup "Remote Desktop"
Write-Host "[+] RDP enabled" -ForegroundColor Green

Write-Host ""
Write-Host "[*] Configuring Windows Firewall..." -ForegroundColor Yellow
# Allow SMB
netsh advfirewall firewall set rule group="File and Printer Sharing" new enable=Yes

# Allow WinRM
Enable-PSRemoting -Force -SkipNetworkProfileCheck
Set-Item WSMan:\localhost\Client\TrustedHosts -Value "*" -Force
Restart-Service WinRM

Write-Host "[+] Firewall configured" -ForegroundColor Green

Write-Host ""
Write-Host "[*] Creating user account..." -ForegroundColor Yellow
$username = "operator"
$password = "labpass123"

# Check if user exists
$userExists = Get-LocalUser -Name $username -ErrorAction SilentlyContinue
if (-not $userExists) {
    $securePassword = ConvertTo-SecureString $password -AsPlainText -Force
    New-LocalUser -Name $username -Password $securePassword -FullName "Operator User" -Description "mrhOTshOT Lab User"
    Add-LocalGroupMember -Group "Administrators" -Member $username
    Write-Host "[+] Created user: $username (password: $password)" -ForegroundColor Green
} else {
    Write-Host "[*] User $username already exists" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "[*] Creating working directories..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path "C:\Temp" | Out-Null
New-Item -ItemType Directory -Force -Path "C:\Temp\industroyer2_payload" | Out-Null
New-Item -ItemType Directory -Force -Path "C:\Logs\mrhOTshOT" | Out-Null

# Set permissions
icacls "C:\Temp" /grant "Everyone:(OI)(CI)F" /T
icacls "C:\Logs\mrhOTshOT" /grant "Everyone:(OI)(CI)F" /T