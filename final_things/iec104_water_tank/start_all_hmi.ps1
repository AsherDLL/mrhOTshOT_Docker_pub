# Start all HMI displays for the water tank lab
# Run on: HMI machine (192.168.1.55, Windows)
#
# Usage:
#   .\start_all_hmi.ps1
#   .\start_all_hmi.ps1 -PlcIp 192.168.1.6
#   .\start_all_hmi.ps1 -PlcIp 192.168.1.6 -NoSIS -NoMBus

param(
    [string]$PlcIp = "192.168.1.6",
    [string]$SisIp = "",
    [string]$MbusIp = "",
    [int]$SisPort = 1502,
    [int]$MbusPort = 5000,
    [switch]$NoSIS,
    [switch]$NoMBus
)

# Default SIS and M-Bus to PLC IP unless disabled
if (-not $NoSIS -and $SisIp -eq "") { $SisIp = $PlcIp }
if (-not $NoMBus -and $MbusIp -eq "") { $MbusIp = $PlcIp }

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "======================================================================"
Write-Host "  STARTING ALL HMI DISPLAYS"
Write-Host "======================================================================"
Write-Host "  PLC Host: $PlcIp"
Write-Host "  SIS:      $(if ($NoSIS) { 'DISABLED' } else { "${SisIp}:${SisPort}" })"
Write-Host "  M-Bus:    $(if ($NoMBus) { 'DISABLED' } else { "${MbusIp}:${MbusPort}" })"
Write-Host "======================================================================"
Write-Host ""

# Build common SIS/M-Bus args
$extraArgs = @()
if (-not $NoSIS) {
    $extraArgs += "--sis-ip", $SisIp, "--sis-port", $SisPort
}
if (-not $NoMBus) {
    $extraArgs += "--mbus-ip", $MbusIp, "--mbus-port", $MbusPort
}

# IEC-104 HMI (Industroyer2, CosmicEnergy, BlackEnergy3, Triton)
Write-Host "[*] Starting IEC-104 HMI (port 2404)..."
Start-Process python -ArgumentList (@("-m", "hmi.multiprotocol_hmi", "--protocol", "iec104", "--host", $PlcIp) + $extraArgs) -WorkingDirectory $ScriptDir

Start-Sleep -Seconds 2

# Modbus HMI (FrostyGoop)
Write-Host "[*] Starting Modbus HMI (port 502)..."
Start-Process python -ArgumentList @("-m", "hmi.multiprotocol_hmi", "--protocol", "modbus", "--host", $PlcIp) -WorkingDirectory $ScriptDir

Start-Sleep -Seconds 2

# S7 HMI (Stuxnet)
Write-Host "[*] Starting S7 HMI (port 102)..."
Start-Process python -ArgumentList @("-m", "hmi.multiprotocol_hmi", "--protocol", "s7", "--host", $PlcIp) -WorkingDirectory $ScriptDir

Start-Sleep -Seconds 2

# OPC-UA HMI (PIPEDREAM) - uses its own multi-process HMI
$PipedreamHmi = Join-Path $ScriptDir "..\pipedream_opcua_demo\machines\hmi\opcua_hmi"
if (Test-Path $PipedreamHmi) {
    Write-Host "[*] Starting PIPEDREAM OPC-UA HMI (port 4840)..."
    Start-Process python -ArgumentList @("multi_protocol_hmi.py", "--host", $PlcIp) -WorkingDirectory $PipedreamHmi
} else {
    Write-Host "[*] Starting OPC-UA HMI (port 4840)..."
    Start-Process python -ArgumentList @("-m", "hmi.multiprotocol_hmi", "--protocol", "opcua", "--host", $PlcIp) -WorkingDirectory $ScriptDir
}

Write-Host ""
Write-Host "======================================================================"
Write-Host "  ALL HMI DISPLAYS LAUNCHED"
Write-Host "======================================================================"
Write-Host "  IEC-104:  port 2404  (+ SIS + M-Bus + KillDisk panels)"
Write-Host "  Modbus:   port 502"
Write-Host "  S7:       port 102"
Write-Host "  OPC-UA:   port 4840"
Write-Host "======================================================================"
Write-Host ""
Write-Host "  To stop all: Get-Process python | Stop-Process"
Write-Host ""
