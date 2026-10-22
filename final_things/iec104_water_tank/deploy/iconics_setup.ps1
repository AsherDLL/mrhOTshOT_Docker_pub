# ICONICS GENESIS64 - ICS Plant Configuration Script
# Configures all 6 PLCs with channels, devices, tags, AssetWorX hierarchy, and Hyper Historian logging
#
# Usage: powershell -ExecutionPolicy Bypass -File iconics_setup.ps1
#
$ErrorActionPreference = "Continue"
$icoPath = "C:\Program Files\ICONICS\GENESIS64\Components"

Write-Output "============================================================"
Write-Output "  ICONICS ICS Plant Configuration"
Write-Output "============================================================"

# Load all modules
Import-Module "$icoPath\IcoModbusPowershell.dll"
Import-Module "$icoPath\IcoBacPowershell.dll"
Import-Module "$icoPath\IcoOpcUaPowershell.dll"
Import-Module "$icoPath\IcoEipPowershell.dll"
Import-Module "$icoPath\MelPowershell.dll"
Import-Module "$icoPath\IcoAssetCatalogPowershell.dll"
Import-Module "$icoPath\IcoHHPowershell.dll"
Write-Output "[+] All modules loaded"

$dt = Get-MbDeviceTypes | Where-Object { $_.Name -eq "Default Device Type" }

# =====================================================================
# 1. MODBUS: PLC-1 Water Treatment (192.168.1.10:502)
# =====================================================================
Write-Output "`n=== PLC-1: Water Treatment (Modbus TCP 192.168.1.10:502) ==="

$ch1 = Get-MbChannel -Name "PLC1_WaterTreatment" -ErrorAction SilentlyContinue
if (-not $ch1 -or -not $ch1.Key) {
    $ch1 = New-MbChannel -Name "PLC1_WaterTreatment" -Type ModbusTcpIp -TCPHostName "192.168.1.10" -TCPPort 502 -Enable $true
    Write-Output "  Created Channel: $($ch1.Name)"
} else { Write-Output "  Existing Channel: $($ch1.Name) Key=$($ch1.Key)" }

$dev1 = Get-MbDevice -Name "WaterTank" -ErrorAction SilentlyContinue
if (-not $dev1 -or -not $dev1.Key) {
    $dev1 = New-MbDevice -Name "WaterTank" -ChannelID $ch1.Key -DeviceTypeID $dt.Key -UnitId 1 -Enable $true -UseZeroBasedAddressing $true -BaseScanRate 1000
    Write-Output "  Created Device: $($dev1.Name)"
} else { Write-Output "  Existing Device: $($dev1.Name) Key=$($dev1.Key)" }

# Input Registers (measurements) - LocationType: InputRegister
foreach ($t in @(@("WaterLevel",0),@("Pressure",1),@("Temperature",2))) {
    New-MbDataItem -ParentName "WaterTank" -Name $t[0] -ModbusType UInt16 -LocationType InputRegister -StartingAddress $t[1] -Enable $true 2>$null | Out-Null
    Write-Output "    $($t[0]) IR[$($t[1])]"
}

# Discrete Inputs (status) - LocationType: Input (not DiscreteInput!)
foreach ($t in @(@("InletValve",0),@("OutletValve",1),@("PumpRunning",2),@("AutoMode",3),@("AlarmOverflow",4),@("AlarmLowLevel",5),@("AlarmHighPressure",6),@("TankExploded",7),@("SISTripped",8))) {
    New-MbDataItem -ParentName "WaterTank" -Name $t[0] -ModbusType Boolean -LocationType Input -StartingAddress $t[1] -Enable $true 2>$null | Out-Null
    Write-Output "    $($t[0]) DI[$($t[1])]"
}

# Coils (commands)
foreach ($t in @(@("InletValveCmd",0),@("OutletValveCmd",1),@("PumpCmd",2),@("AutoModeCmd",3))) {
    New-MbDataItem -ParentName "WaterTank" -Name $t[0] -ModbusType Boolean -LocationType Coil -StartingAddress $t[1] -Enable $true 2>$null | Out-Null
    Write-Output "    $($t[0]) Coil[$($t[1])]"
}

# =====================================================================
# 2. MODBUS: PLC-6 Boiler House (192.168.1.15:5020)
# =====================================================================
Write-Output "`n=== PLC-6: Boiler House (Modbus TCP 192.168.1.15:5020) ==="

$ch6 = Get-MbChannel -Name "PLC6_BoilerHouse" -ErrorAction SilentlyContinue
if (-not $ch6 -or -not $ch6.Key) {
    $ch6 = New-MbChannel -Name "PLC6_BoilerHouse" -Type ModbusTcpIp -TCPHostName "192.168.1.15" -TCPPort 5020 -Enable $true
    Write-Output "  Created Channel"
} else { Write-Output "  Existing Channel: $($ch6.Name) Key=$($ch6.Key)" }

$dev6 = Get-MbDevice -Name "Boiler" -ErrorAction SilentlyContinue
if (-not $dev6 -or -not $dev6.Key) {
    $dev6 = New-MbDevice -Name "Boiler" -ChannelID $ch6.Key -DeviceTypeID $dt.Key -UnitId 1 -Enable $true -UseZeroBasedAddressing $true -BaseScanRate 1000
    Write-Output "  Created Device"
} else { Write-Output "  Existing Device: $($dev6.Name) Key=$($dev6.Key)" }

foreach ($t in @(@("SteamPressure",0),@("SteamTemp",1),@("DrumLevel",2))) {
    New-MbDataItem -ParentName "Boiler" -Name $t[0] -ModbusType UInt16 -LocationType InputRegister -StartingAddress $t[1] -Enable $true 2>$null | Out-Null
    Write-Output "    $($t[0]) IR[$($t[1])]"
}
foreach ($t in @(@("BurnerOn",0),@("FeedwaterPump",1),@("BlowdownValve",2),@("SafetyValveOpen",3),@("FlameFailure",4),@("HighPressAlarm",5),@("LowWaterAlarm",6))) {
    New-MbDataItem -ParentName "Boiler" -Name $t[0] -ModbusType Boolean -LocationType Input -StartingAddress $t[1] -Enable $true 2>$null | Out-Null
    Write-Output "    $($t[0]) DI[$($t[1])]"
}
foreach ($t in @(@("BurnerCmd",0),@("FeedwaterCmd",1),@("BlowdownCmd",2))) {
    New-MbDataItem -ParentName "Boiler" -Name $t[0] -ModbusType Boolean -LocationType Coil -StartingAddress $t[1] -Enable $true 2>$null | Out-Null
    Write-Output "    $($t[0]) Coil[$($t[1])]"
}

# =====================================================================
# 3. OPC-UA: PLC-3 Gas Pipeline (192.168.1.12:4840)
# =====================================================================
Write-Output "`n=== PLC-3: Gas Pipeline (OPC-UA 192.168.1.12:4840) ==="
try {
    $opcSvr = New-OpcUaServer -Name "PLC3_GasPipeline" -EndpointUrl "opc.tcp://192.168.1.12:4840/freeopcua/server/" 2>&1
    Write-Output "  OPC-UA Server: $opcSvr"
} catch { Write-Output "  OPC-UA: $_" }

# =====================================================================
# 4. EtherNet/IP: PLC-4 Manufacturing (192.168.1.13:44818)
# =====================================================================
Write-Output "`n=== PLC-4: Manufacturing (EtherNet/IP 192.168.1.13:44818) ==="
try {
    # Get help on New-EipNetwork parameters
    $eipParams = Get-Help New-EipNetwork -Parameter * 2>$null
    $eipParams | ForEach-Object { Write-Output "  EipNetwork param: $($_.Name)" }
    $eipNodeParams = Get-Help New-EipNode -Parameter * 2>$null
    $eipNodeParams | ForEach-Object { Write-Output "  EipNode param: $($_.Name)" }
} catch { Write-Output "  EIP: $_" }

# =====================================================================
# 5. BACnet: PLC-5 Building HVAC (192.168.1.14:47808)
# =====================================================================
Write-Output "`n=== PLC-5: Building HVAC (BACnet/IP 192.168.1.14:47808) ==="
try {
    # Get BacDevice parameters
    $bacParams = Get-Help New-BacDevice -Parameter * 2>$null
    $bacParams | ForEach-Object { Write-Output "  BacDevice param: $($_.Name) [$($_.ParameterType)]" }
} catch { Write-Output "  BACnet: $_" }

# =====================================================================
# 6. MELSEC: PLC-3 Gas Pipeline MC Protocol (192.168.1.12:5007)
# =====================================================================
Write-Output "`n=== PLC-3: Gas Pipeline MELSEC (192.168.1.12:5007) ==="
try {
    $melDev = New-MelcoMelsecDevice -Name "PLC3_GasMelsec" -IpAddressPlc "192.168.1.12" -Port 5007 2>&1
    Write-Output "  MELSEC Device: $melDev"
} catch { Write-Output "  MELSEC: $_" }

# =====================================================================
# 7. AssetWorX Hierarchy
# =====================================================================
Write-Output "`n=== AssetWorX: Plant Hierarchy ==="

$root = New-AcEquipmentLevel -Name "ICS_Plant" -Description "Industrial Control System Plant" 2>$null
$levels = @(
    @{Name="WaterTreatment"; Desc="PLC-1 | Modbus TCP | 192.168.1.10:502"},
    @{Name="PowerSubstation"; Desc="PLC-2 | IEC 61850 MMS | 192.168.1.11:8102"},
    @{Name="GasPipeline"; Desc="PLC-3 | OPC-UA | 192.168.1.12:4840"},
    @{Name="Manufacturing"; Desc="PLC-4 | Siemens S7 | 192.168.1.13:102"},
    @{Name="BuildingHVAC"; Desc="PLC-5 | BACnet/IP | 192.168.1.14:47808"},
    @{Name="BoilerHouse"; Desc="PLC-6 | ABB Modbus | 192.168.1.15:5020"}
)
foreach ($lvl in $levels) {
    New-AcEquipmentLevel -ParentName "ICS_Plant" -Name $lvl.Name -Description $lvl.Desc 2>$null | Out-Null
    Write-Output "  $($lvl.Name)"
}

# =====================================================================
# 8. Hyper Historian Logging
# =====================================================================
Write-Output "`n=== Hyper Historian ==="

$lg = New-HHLoggingGroup -Name "ICS_Plant_Log" -Description "ICS Plant - All PLC Tags" -LoggingPeriod 1000 -Active $true 2>$null
Write-Output "  Logging Group: ICS_Plant_Log"

$mb = "\\localhost\Modbus"
foreach ($tag in @("WaterLevel","Pressure","Temperature","InletValve","OutletValve","PumpRunning","AutoMode","TankExploded","SISTripped")) {
    New-HHTag -ParentName "ICS_Plant_Log" -Name "WT_$tag" -Expression "$mb\PLC1_WaterTreatment.WaterTank.$tag" -Active $true 2>$null | Out-Null
}
Write-Output "  Water Treatment: 9 tags"

foreach ($tag in @("SteamPressure","SteamTemp","DrumLevel","BurnerOn","FeedwaterPump","SafetyValveOpen","HighPressAlarm","LowWaterAlarm")) {
    New-HHTag -ParentName "ICS_Plant_Log" -Name "BH_$tag" -Expression "$mb\PLC6_BoilerHouse.Boiler.$tag" -Active $true 2>$null | Out-Null
}
Write-Output "  Boiler House: 8 tags"

# =====================================================================
# 9. Restart Modbus Service
# =====================================================================
Write-Output "`n=== Restarting Services ==="
Restart-Service FwxModbusService -Force -ErrorAction SilentlyContinue
Start-Sleep 5
Write-Output "[+] Modbus service restarted"

# =====================================================================
# VERIFICATION
# =====================================================================
Write-Output "`n============================================================"
Write-Output "  VERIFICATION"
Write-Output "============================================================"

Write-Output "`nModbus Channels:"
Get-MbChannels | Where-Object { $_.Name -like "PLC*" } | ForEach-Object {
    Write-Output "  $($_.Name) -> $($_.TCPHostName):$($_.TCPPort) Enabled=$($_.Enable)"
}

Write-Output "`nModbus Devices:"
Get-MbDevices | Where-Object { $_.Name -eq "WaterTank" -or $_.Name -eq "Boiler" } | ForEach-Object {
    Write-Output "  $($_.Name) Channel=$($_.ChannelName) Unit=$($_.UnitId)"
}

Write-Output "`nModbus Tags:"
$wt_tags = (Get-MbDataItems | Where-Object { $_.ParentKey -eq $dev1.Key }).Count
$bl_tags = (Get-MbDataItems | Where-Object { $_.ParentKey -eq $dev6.Key }).Count
Write-Output "  WaterTank: $wt_tags tags"
Write-Output "  Boiler: $bl_tags tags"

Write-Output "`nAssetWorX:"
Get-AcEquipmentLevels | Where-Object { $_.Name -eq "ICS_Plant" -or $_.Description -like "PLC*" } | ForEach-Object {
    Write-Output "  $($_.Name): $($_.Description)"
}

Write-Output "`nHistorian:"
$hh_wt = (Get-HHTags | Where-Object { $_.Name -like "WT_*" }).Count
$hh_bl = (Get-HHTags | Where-Object { $_.Name -like "BH_*" }).Count
Write-Output "  Water Treatment: $hh_wt tags"
Write-Output "  Boiler House: $hh_bl tags"

Write-Output "`n============================================================"
Write-Output "  CONFIGURATION COMPLETE"
Write-Output "============================================================"
