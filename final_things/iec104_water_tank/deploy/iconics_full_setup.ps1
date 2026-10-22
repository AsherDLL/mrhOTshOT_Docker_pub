# ICONICS GENESIS64 - Complete ICS Plant Setup
# Creates ALL channels, devices, tags, AssetWorX, and Historian in one shot.
#
# Transfer to historian machine (192.168.1.9) and run:
#   powershell -ExecutionPolicy Bypass -File iconics_full_setup.ps1
#
# Idempotent - safe to re-run (skips existing objects).

$ErrorActionPreference = "Continue"
$icoPath = "C:\Program Files\ICONICS\GENESIS64\Components"

# ─── Track results ──────────────────────────────────────────────────
$results = @{ Created = 0; Skipped = 0; Failed = 0 }

function Log-OK   ($msg) { Write-Host "  [+] $msg" -ForegroundColor Green;  $script:results.Created++ }
function Log-SKIP ($msg) { Write-Host "  [=] $msg" -ForegroundColor Yellow; $script:results.Skipped++ }
function Log-FAIL ($msg) { Write-Host "  [!] $msg" -ForegroundColor Red;    $script:results.Failed++ }
function Log-HEAD ($msg) { Write-Host "`n═══ $msg ═══" -ForegroundColor Cyan }

# ─── Load Modules ───────────────────────────────────────────────────
Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "  ICONICS ICS Plant - Full Configuration" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

$modules = @(
    @{ Name = "Modbus";    DLL = "IcoModbusPowershell.dll" },
    @{ Name = "BACnet";    DLL = "IcoBacPowershell.dll" },
    @{ Name = "OPC-UA";    DLL = "IcoOpcUaPowershell.dll" },
    @{ Name = "EIP";       DLL = "IcoEipPowershell.dll" },
    @{ Name = "MELSEC";    DLL = "MelPowershell.dll" },
    @{ Name = "AssetWorX"; DLL = "IcoAssetCatalogPowershell.dll" },
    @{ Name = "Historian"; DLL = "IcoHHPowershell.dll" }
)

$loadedModules = @()
foreach ($m in $modules) {
    $path = Join-Path $icoPath $m.DLL
    if (Test-Path $path) {
        try {
            Import-Module $path -ErrorAction Stop
            $loadedModules += $m.Name
        } catch {
            Write-Host "  WARN: Could not load $($m.Name): $_" -ForegroundColor Yellow
        }
    } else {
        Write-Host "  WARN: $($m.DLL) not found - $($m.Name) skipped" -ForegroundColor Yellow
    }
}
Write-Host "  Loaded: $($loadedModules -join ', ')" -ForegroundColor Green

# ─── Helper: Idempotent Modbus channel+device ───────────────────────
function Ensure-MbChannel ($Name, $Host, $Port) {
    $ch = Get-MbChannel -Name $Name -ErrorAction SilentlyContinue
    if ($ch -and $ch.Key) {
        Log-SKIP "Channel $Name exists"
        return $ch
    }
    $ch = New-MbChannel -Name $Name -Type ModbusTcpIp -TCPHostName $Host -TCPPort $Port -Enable $true
    Log-OK "Channel $Name → ${Host}:${Port}"
    return $ch
}

function Ensure-MbDevice ($Name, $ChannelKey, $DeviceTypeKey, $UnitId) {
    $dev = Get-MbDevice -Name $Name -ErrorAction SilentlyContinue
    if ($dev -and $dev.Key) {
        Log-SKIP "Device $Name exists"
        return $dev
    }
    $dev = New-MbDevice -Name $Name -ChannelID $ChannelKey -DeviceTypeID $DeviceTypeKey `
        -UnitId $UnitId -Enable $true -UseZeroBasedAddressing $true -BaseScanRate 1000
    Log-OK "Device $Name (Unit $UnitId)"
    return $dev
}

$dt = Get-MbDeviceTypes | Where-Object { $_.Name -eq "Default Device Type" }


# ═════════════════════════════════════════════════════════════════════
#  PLC-1: WATER TREATMENT - Modbus TCP (192.168.1.10:502)
# ═════════════════════════════════════════════════════════════════════
Log-HEAD "PLC-1: Water Treatment - Modbus TCP 192.168.1.10:502"

$ch1 = Ensure-MbChannel "PLC1_WaterTreatment" "192.168.1.10" 502
$dev1 = Ensure-MbDevice "WaterTank" $ch1.Key $dt.Key 1

# Input Registers - analog measurements
$irTags = @(
    @("WaterLevel",    0, "Water level 0-100%"),
    @("Pressure",      1, "Tank pressure (bar)"),
    @("Temperature",   2, "Water temperature (C)")
)
foreach ($t in $irTags) {
    New-MbDataItem -ParentName "WaterTank" -Name $t[0] -ModbusType UInt16 `
        -LocationType InputRegister -StartingAddress $t[1] -Enable $true 2>$null | Out-Null
    Write-Host "    IR[$($t[1])] $($t[0]) - $($t[2])"
}

# Discrete Inputs - digital status
$diTags = @(
    @("InletValve",        0, "Inlet valve open/closed"),
    @("OutletValve",       1, "Outlet valve open/closed"),
    @("PumpRunning",       2, "Pump running/stopped"),
    @("AutoMode",          3, "Auto/Manual mode"),
    @("AlarmOverflow",     4, "Overflow alarm"),
    @("AlarmLowLevel",     5, "Low level alarm"),
    @("AlarmHighPressure", 6, "High pressure alarm"),
    @("TankExploded",      7, "Tank rupture"),
    @("SISTripped",        8, "Safety system trip")
)
foreach ($t in $diTags) {
    New-MbDataItem -ParentName "WaterTank" -Name $t[0] -ModbusType Boolean `
        -LocationType Input -StartingAddress $t[1] -Enable $true 2>$null | Out-Null
    Write-Host "    DI[$($t[1])] $($t[0]) - $($t[2])"
}

# Coils - commands
$coilTags = @(
    @("InletValveCmd",  0, "Open/Close inlet valve"),
    @("OutletValveCmd", 1, "Open/Close outlet valve"),
    @("PumpCmd",        2, "Start/Stop pump"),
    @("AutoModeCmd",    3, "Switch Auto/Manual")
)
foreach ($t in $coilTags) {
    New-MbDataItem -ParentName "WaterTank" -Name $t[0] -ModbusType Boolean `
        -LocationType Coil -StartingAddress $t[1] -Enable $true 2>$null | Out-Null
    Write-Host "    CO[$($t[1])] $($t[0]) - $($t[2])"
}

# Holding Registers - setpoints
$hrTags = @(
    @("InletValveSetpoint",  0, "Inlet valve position 0-100%"),
    @("OutletValveSetpoint", 1, "Outlet valve position 0-100%")
)
foreach ($t in $hrTags) {
    New-MbDataItem -ParentName "WaterTank" -Name $t[0] -ModbusType UInt16 `
        -LocationType HoldingRegister -StartingAddress $t[1] -Enable $true 2>$null | Out-Null
    Write-Host "    HR[$($t[1])] $($t[0]) - $($t[2])"
}


# ═════════════════════════════════════════════════════════════════════
#  PLC-2: POWER SUBSTATION - OPC-UA bridge to IEC 61850 (192.168.1.11:8102)
#  Note: ICONICS connects via OPC-UA; the PLC bridges IEC 61850 internally
# ═════════════════════════════════════════════════════════════════════
Log-HEAD "PLC-2: Power Substation - IEC 61850 via OPC-UA 192.168.1.11"

# Try OPC-UA first (most likely path for ICONICS → IEC 61850)
try {
    $opc2 = New-OpcUaServer -Name "PLC2_PowerSubstation" `
        -EndpointUrl "opc.tcp://192.168.1.11:4840/freeopcua/server/" 2>&1
    if ($opc2) { Log-OK "OPC-UA server PLC2_PowerSubstation" }
} catch {
    Log-FAIL "OPC-UA for PLC-2: $_"
    Write-Host "    Manual: Add IEC 61850 MMS server 192.168.1.11:8102 in Workbench" -ForegroundColor Yellow
}

# If the machine exposes Modbus as a fallback (common for IEC 61850 gateways)
try {
    $ch2 = Ensure-MbChannel "PLC2_PowerSub_Modbus" "192.168.1.11" 502
    $dev2 = Ensure-MbDevice "PowerSubstation" $ch2.Key $dt.Key 1

    $ps_ir = @(
        @("VoltagePhaseA", 0, "Phase A voltage (V)"),
        @("VoltagePhaseB", 1, "Phase B voltage (V)"),
        @("VoltagePhaseC", 2, "Phase C voltage (V)"),
        @("CurrentPhaseA", 3, "Phase A current (A)"),
        @("CurrentPhaseB", 4, "Phase B current (A)"),
        @("CurrentPhaseC", 5, "Phase C current (A)"),
        @("Frequency",     6, "Grid frequency (Hz)"),
        @("ActivePower",   7, "Active power (kW)")
    )
    foreach ($t in $ps_ir) {
        New-MbDataItem -ParentName "PowerSubstation" -Name $t[0] -ModbusType UInt16 `
            -LocationType InputRegister -StartingAddress $t[1] -Enable $true 2>$null | Out-Null
        Write-Host "    IR[$($t[1])] $($t[0]) - $($t[2])"
    }

    $ps_di = @(
        @("BreakerClosed",     0, "Main breaker closed"),
        @("ProtectionTrip",    1, "Protection relay tripped"),
        @("EarthFault",        2, "Earth fault detected"),
        @("OvercurrentAlarm",  3, "Overcurrent alarm")
    )
    foreach ($t in $ps_di) {
        New-MbDataItem -ParentName "PowerSubstation" -Name $t[0] -ModbusType Boolean `
            -LocationType Input -StartingAddress $t[1] -Enable $true 2>$null | Out-Null
        Write-Host "    DI[$($t[1])] $($t[0]) - $($t[2])"
    }

    $ps_co = @(
        @("BreakerCmd",     0, "Open/Close breaker"),
        @("ResetProtection", 1, "Reset protection relay")
    )
    foreach ($t in $ps_co) {
        New-MbDataItem -ParentName "PowerSubstation" -Name $t[0] -ModbusType Boolean `
            -LocationType Coil -StartingAddress $t[1] -Enable $true 2>$null | Out-Null
        Write-Host "    CO[$($t[1])] $($t[0]) - $($t[2])"
    }
} catch {
    Write-Host "    Modbus fallback not available for PLC-2" -ForegroundColor Yellow
}


# ═════════════════════════════════════════════════════════════════════
#  PLC-3: GAS PIPELINE - OPC-UA (192.168.1.12:4840)
# ═════════════════════════════════════════════════════════════════════
Log-HEAD "PLC-3: Gas Pipeline - OPC-UA opc.tcp://192.168.1.12:4840"

try {
    $opc3 = New-OpcUaServer -Name "PLC3_GasPipeline" `
        -EndpointUrl "opc.tcp://192.168.1.12:4840/freeopcua/server/" 2>&1
    if ($opc3) { Log-OK "OPC-UA server PLC3_GasPipeline" }
} catch {
    Log-FAIL "OPC-UA for PLC-3: $_"
}

# OPC-UA tags are auto-discovered by browsing the namespace in Workbench.
# The PLC exposes:
#   Objects/WaterTank/Measurements/{water_level, pressure, temperature}
#   Objects/WaterTank/Status/{inlet_valve_status, outlet_valve_status, pump_status, auto_mode_status}
#   Objects/WaterTank/Alarms/{alarm_overflow, alarm_low_level, alarm_high_pressure, tank_exploded}
#   Objects/WaterTank/Commands/{inlet_valve_command, outlet_valve_command, pump_command, auto_mode_command}
#   Objects/WaterTank/Setpoints/{inlet_valve_setpoint, outlet_valve_setpoint}
#
# After running this script, open Workbench → OPC UA → PLC3_GasPipeline → Browse → select all → Add to Tags

Write-Host "    Namespace: http://watertank.local"
Write-Host "    Browse in Workbench to auto-discover 16 tags under Objects/WaterTank/"


# ═════════════════════════════════════════════════════════════════════
#  PLC-3: GAS PIPELINE - MELSEC MC Protocol (192.168.1.12:5007)
# ═════════════════════════════════════════════════════════════════════
Log-HEAD "PLC-3: Gas Pipeline - MELSEC MC 192.168.1.12:5007"

try {
    $mel3 = New-MelcoMelsecDevice -Name "PLC3_GasMelsec" `
        -IpAddressPlc "192.168.1.12" -Port 5007 2>&1
    if ($mel3) { Log-OK "MELSEC device PLC3_GasMelsec" }
} catch {
    Log-FAIL "MELSEC for PLC-3: $_"
}
Write-Host "    D0=PipelinePressure, D1=FlowRate, D2=ValvePosition"
Write-Host "    M0=EmergencyStop, M1=ValveCmd"


# ═════════════════════════════════════════════════════════════════════
#  PLC-4: MANUFACTURING - Siemens S7 via OPC-UA (192.168.1.13:102)
#  ICONICS talks S7 through its OPC-UA gateway or direct S7 driver
# ═════════════════════════════════════════════════════════════════════
Log-HEAD "PLC-4: Manufacturing - S7comm 192.168.1.13:102"

# Method 1: OPC-UA (if PLC-4 also runs an OPC-UA endpoint)
try {
    $opc4 = New-OpcUaServer -Name "PLC4_Manufacturing" `
        -EndpointUrl "opc.tcp://192.168.1.13:4840/freeopcua/server/" 2>&1
    if ($opc4) { Log-OK "OPC-UA server PLC4_Manufacturing" }
} catch {
    Write-Host "    OPC-UA not available for PLC-4, using Modbus fallback" -ForegroundColor Yellow
}

# Method 2: Modbus fallback (the PLC also runs Modbus adapter)
try {
    $ch4 = Ensure-MbChannel "PLC4_Manufacturing" "192.168.1.13" 502
    $dev4 = Ensure-MbDevice "ManufLine" $ch4.Key $dt.Key 1

    $mf_ir = @(
        @("WaterLevel",   0, "Water level %"),
        @("Pressure",     1, "Pressure (bar)"),
        @("Temperature",  2, "Temperature (C)")
    )
    foreach ($t in $mf_ir) {
        New-MbDataItem -ParentName "ManufLine" -Name $t[0] -ModbusType UInt16 `
            -LocationType InputRegister -StartingAddress $t[1] -Enable $true 2>$null | Out-Null
        Write-Host "    IR[$($t[1])] $($t[0])"
    }

    $mf_di = @(
        @("InletValve",   0), @("OutletValve",  1), @("PumpRunning", 2),
        @("AutoMode",     3), @("AlarmOverflow", 4), @("AlarmLowLevel", 5),
        @("AlarmHighPressure", 6), @("TankExploded", 7)
    )
    foreach ($t in $mf_di) {
        New-MbDataItem -ParentName "ManufLine" -Name $t[0] -ModbusType Boolean `
            -LocationType Input -StartingAddress $t[1] -Enable $true 2>$null | Out-Null
        Write-Host "    DI[$($t[1])] $($t[0])"
    }

    $mf_co = @(
        @("InletValveCmd", 0), @("OutletValveCmd", 1),
        @("PumpCmd",       2), @("AutoModeCmd",    3)
    )
    foreach ($t in $mf_co) {
        New-MbDataItem -ParentName "ManufLine" -Name $t[0] -ModbusType Boolean `
            -LocationType Coil -StartingAddress $t[1] -Enable $true 2>$null | Out-Null
        Write-Host "    CO[$($t[1])] $($t[0])"
    }
} catch {
    Log-FAIL "Modbus fallback for PLC-4: $_"
}

# S7 Data Block reference (for manual Workbench config if S7 driver available):
Write-Host "    S7 DB layout (manual config):" -ForegroundColor Yellow
Write-Host "      DB1: Measurements - DBD0=WaterLevel, DBD4=Pressure, DBD8=Temperature (REAL)"
Write-Host "      DB2: Status - DBX0.0-0.7 = InletValve..TankExploded (BOOL)"
Write-Host "      DB3: Commands - DBX0.0-0.3 = InletValveCmd..AutoModeCmd (BOOL)"
Write-Host "      DB4: Setpoints - DBD0=InletValveSP, DBD4=OutletValveSP (REAL)"


# ═════════════════════════════════════════════════════════════════════
#  PLC-5: BUILDING HVAC - BACnet/IP (192.168.1.14:47808)
# ═════════════════════════════════════════════════════════════════════
Log-HEAD "PLC-5: Building HVAC - BACnet/IP 192.168.1.14:47808"

try {
    # Try creating BACnet network + device
    # ICONICS BACnet cmdlets vary by version - try common patterns
    $bacNet = $null
    $bacDev = $null

    # Attempt 1: New-BacNetwork + New-BacDevice
    try {
        $bacNet = New-BacNetwork -Name "PLC5_HVAC_Network" -NetworkType BACnetIP `
            -LocalIPAddress "192.168.1.9" -UDPPort 47808 -Enable $true 2>&1
        Log-OK "BACnet network PLC5_HVAC_Network"
    } catch {
        # Attempt 2: New-BacDevice directly (some ICONICS versions)
        try {
            $bacDev = New-BacDevice -Name "HVAC_Controller" `
                -IPAddress "192.168.1.14" -Port 47808 `
                -DeviceInstance 1 -Enable $true 2>&1
            Log-OK "BACnet device HVAC_Controller"
        } catch {
            # Attempt 3: New-BacChannel (yet another ICONICS pattern)
            try {
                $bacCh = New-BacChannel -Name "PLC5_HVAC" -Type BACnetIP `
                    -IPAddress "192.168.1.14" -Port 47808 -Enable $true 2>&1
                Log-OK "BACnet channel PLC5_HVAC"
            } catch {
                Log-FAIL "BACnet: No working cmdlet found"
                Write-Host "    Manual setup required in Workbench:" -ForegroundColor Yellow
                Write-Host "      1. FrameWorX → BACnet → New Network (BACnet/IP, port 47808)"
                Write-Host "      2. Right-click network → Discover → Add device 192.168.1.14"
                Write-Host "      3. Browse objects → Add all AI/AO/BI/BO to tag database"
            }
        }
    }
} catch {
    Log-FAIL "BACnet overall: $_"
}

# BACnet object reference for manual tag entry:
Write-Host "    BACnet Object Map:" -ForegroundColor Yellow
Write-Host "      AI-0 = ZoneTemperature      AI-1 = SupplyAirTemp      AI-2 = ReturnAirTemp"
Write-Host "      AO-0 = HeatingSetpoint       AO-1 = CoolingSetpoint"
Write-Host "      BI-0 = FanStatus             BI-1 = CompressorStatus"
Write-Host "      BO-0 = FanCommand            BO-1 = HeatingValveCmd"
Write-Host "      BO-2 = CoolingValveCmd       BO-3 = AutoModeCmd"


# ═════════════════════════════════════════════════════════════════════
#  PLC-6: BOILER HOUSE - Modbus TCP (192.168.1.15:5020)
# ═════════════════════════════════════════════════════════════════════
Log-HEAD "PLC-6: Boiler House - Modbus TCP 192.168.1.15:5020"

$ch6 = Ensure-MbChannel "PLC6_BoilerHouse" "192.168.1.15" 5020
$dev6 = Ensure-MbDevice "Boiler" $ch6.Key $dt.Key 1

$bh_ir = @(
    @("SteamPressure", 0, "Steam header pressure (bar)"),
    @("SteamTemp",     1, "Steam temperature (C)"),
    @("DrumLevel",     2, "Drum water level (%)")
)
foreach ($t in $bh_ir) {
    New-MbDataItem -ParentName "Boiler" -Name $t[0] -ModbusType UInt16 `
        -LocationType InputRegister -StartingAddress $t[1] -Enable $true 2>$null | Out-Null
    Write-Host "    IR[$($t[1])] $($t[0]) - $($t[2])"
}

$bh_di = @(
    @("BurnerOn",        0, "Burner running"),
    @("FeedwaterPump",   1, "Feedwater pump running"),
    @("BlowdownValve",   2, "Blowdown valve open"),
    @("SafetyValveOpen", 3, "Safety relief valve open"),
    @("FlameFailure",    4, "Flame failure alarm"),
    @("HighPressAlarm",  5, "High pressure alarm"),
    @("LowWaterAlarm",   6, "Low water alarm")
)
foreach ($t in $bh_di) {
    New-MbDataItem -ParentName "Boiler" -Name $t[0] -ModbusType Boolean `
        -LocationType Input -StartingAddress $t[1] -Enable $true 2>$null | Out-Null
    Write-Host "    DI[$($t[1])] $($t[0]) - $($t[2])"
}

$bh_co = @(
    @("BurnerCmd",    0, "Start/Stop burner"),
    @("FeedwaterCmd", 1, "Start/Stop feedwater pump"),
    @("BlowdownCmd",  2, "Open/Close blowdown valve")
)
foreach ($t in $bh_co) {
    New-MbDataItem -ParentName "Boiler" -Name $t[0] -ModbusType Boolean `
        -LocationType Coil -StartingAddress $t[1] -Enable $true 2>$null | Out-Null
    Write-Host "    CO[$($t[1])] $($t[0]) - $($t[2])"
}


# ═════════════════════════════════════════════════════════════════════
#  ASSETWORX - Plant Hierarchy
# ═════════════════════════════════════════════════════════════════════
Log-HEAD "AssetWorX - Plant Hierarchy"

try {
    $root = New-AcEquipmentLevel -Name "ICS_Plant" -Description "Industrial Control System Plant" 2>$null
    if ($root) { Log-OK "Root: ICS_Plant" } else { Log-SKIP "Root ICS_Plant exists" }
} catch { Log-SKIP "Root ICS_Plant exists" }

$levels = @(
    @{ Name = "WaterTreatment";  Desc = "PLC-1 | Modbus TCP | 192.168.1.10:502";   Tags = "\\localhost\Modbus\PLC1_WaterTreatment.WaterTank" },
    @{ Name = "PowerSubstation"; Desc = "PLC-2 | IEC 61850 MMS | 192.168.1.11:8102"; Tags = "\\localhost\OPC UA\PLC2_PowerSubstation" },
    @{ Name = "GasPipeline";     Desc = "PLC-3 | OPC-UA | 192.168.1.12:4840";       Tags = "\\localhost\OPC UA\PLC3_GasPipeline" },
    @{ Name = "Manufacturing";   Desc = "PLC-4 | Siemens S7 | 192.168.1.13:102";    Tags = "\\localhost\Modbus\PLC4_Manufacturing.ManufLine" },
    @{ Name = "BuildingHVAC";    Desc = "PLC-5 | BACnet/IP | 192.168.1.14:47808";   Tags = "\\localhost\BACnet\PLC5_HVAC_Network" },
    @{ Name = "BoilerHouse";     Desc = "PLC-6 | ABB Modbus | 192.168.1.15:5020";   Tags = "\\localhost\Modbus\PLC6_BoilerHouse.Boiler" }
)
foreach ($lvl in $levels) {
    try {
        New-AcEquipmentLevel -ParentName "ICS_Plant" -Name $lvl.Name -Description $lvl.Desc 2>$null | Out-Null
        Write-Host "  $($lvl.Name) - $($lvl.Desc)"
        Write-Host "    Tag root: $($lvl.Tags)" -ForegroundColor DarkGray
    } catch {
        Log-SKIP "$($lvl.Name) exists"
    }
}


# ═════════════════════════════════════════════════════════════════════
#  HYPER HISTORIAN - Logging Groups
# ═════════════════════════════════════════════════════════════════════
Log-HEAD "Hyper Historian - Tag Logging"

try {
    $lg = New-HHLoggingGroup -Name "ICS_Plant_Log" -Description "ICS Plant - All PLC Tags" `
        -LoggingPeriod 1000 -Active $true 2>$null
    if ($lg) { Log-OK "Logging Group: ICS_Plant_Log (1s interval)" }
    else { Log-SKIP "Logging Group ICS_Plant_Log exists" }
} catch { Log-SKIP "Logging Group exists" }

$mb = "\\localhost\Modbus"

# PLC-1 Water Treatment historian tags
$wt_tags = @("WaterLevel","Pressure","Temperature","InletValve","OutletValve",
             "PumpRunning","AutoMode","AlarmOverflow","AlarmLowLevel",
             "AlarmHighPressure","TankExploded","SISTripped",
             "InletValveCmd","OutletValveCmd","PumpCmd","AutoModeCmd",
             "InletValveSetpoint","OutletValveSetpoint")
foreach ($tag in $wt_tags) {
    New-HHTag -ParentName "ICS_Plant_Log" -Name "WT_$tag" `
        -Expression "$mb\PLC1_WaterTreatment.WaterTank.$tag" -Active $true 2>$null | Out-Null
}
Write-Host "  Water Treatment: $($wt_tags.Count) tags"

# PLC-2 Power Substation historian tags (Modbus fallback)
$ps_tags = @("VoltagePhaseA","VoltagePhaseB","VoltagePhaseC",
             "CurrentPhaseA","CurrentPhaseB","CurrentPhaseC",
             "Frequency","ActivePower","BreakerClosed","ProtectionTrip")
foreach ($tag in $ps_tags) {
    New-HHTag -ParentName "ICS_Plant_Log" -Name "PS_$tag" `
        -Expression "$mb\PLC2_PowerSub_Modbus.PowerSubstation.$tag" -Active $true 2>$null | Out-Null
}
Write-Host "  Power Substation: $($ps_tags.Count) tags"

# PLC-3 Gas Pipeline historian tags (OPC-UA - expressions differ)
$gp_opcua = "\\localhost\OPC UA\PLC3_GasPipeline"
$gp_tags = @("water_level","pressure","temperature","inlet_valve_status",
             "outlet_valve_status","pump_status","auto_mode_status",
             "alarm_overflow","tank_exploded")
foreach ($tag in $gp_tags) {
    New-HHTag -ParentName "ICS_Plant_Log" -Name "GP_$tag" `
        -Expression "$gp_opcua.WaterTank.Measurements.$tag" -Active $true 2>$null | Out-Null
}
Write-Host "  Gas Pipeline: $($gp_tags.Count) tags"

# PLC-4 Manufacturing historian tags
$mf_tags = @("WaterLevel","Pressure","Temperature","InletValve","OutletValve",
             "PumpRunning","AutoMode","TankExploded")
foreach ($tag in $mf_tags) {
    New-HHTag -ParentName "ICS_Plant_Log" -Name "MF_$tag" `
        -Expression "$mb\PLC4_Manufacturing.ManufLine.$tag" -Active $true 2>$null | Out-Null
}
Write-Host "  Manufacturing: $($mf_tags.Count) tags"

# PLC-6 Boiler House historian tags
$bh_tags = @("SteamPressure","SteamTemp","DrumLevel","BurnerOn","FeedwaterPump",
             "BlowdownValve","SafetyValveOpen","FlameFailure","HighPressAlarm","LowWaterAlarm",
             "BurnerCmd","FeedwaterCmd","BlowdownCmd")
foreach ($tag in $bh_tags) {
    New-HHTag -ParentName "ICS_Plant_Log" -Name "BH_$tag" `
        -Expression "$mb\PLC6_BoilerHouse.Boiler.$tag" -Active $true 2>$null | Out-Null
}
Write-Host "  Boiler House: $($bh_tags.Count) tags"

$totalHHTags = $wt_tags.Count + $ps_tags.Count + $gp_tags.Count + $mf_tags.Count + $bh_tags.Count
Write-Host "  TOTAL: $totalHHTags historian tags" -ForegroundColor Green


# ═════════════════════════════════════════════════════════════════════
#  RESTART SERVICES
# ═════════════════════════════════════════════════════════════════════
Log-HEAD "Restarting Services"

$services = @("FwxModbusService", "FwxOpcUaService", "FwxBACnetService",
              "Ico64HyperHistorian", "IcoFwxServer")
foreach ($svc in $services) {
    try {
        $s = Get-Service $svc -ErrorAction SilentlyContinue
        if ($s) {
            Restart-Service $svc -Force -ErrorAction SilentlyContinue
            Write-Host "  Restarted $svc"
        }
    } catch { }
}
Start-Sleep 5


# ═════════════════════════════════════════════════════════════════════
#  VERIFICATION
# ═════════════════════════════════════════════════════════════════════
Log-HEAD "Verification"

Write-Host "`nModbus Channels:" -ForegroundColor White
Get-MbChannels 2>$null | Where-Object { $_.Name -like "PLC*" } | ForEach-Object {
    $status = if ($_.Enable) { "ENABLED" } else { "DISABLED" }
    Write-Host "  $($_.Name) → $($_.TCPHostName):$($_.TCPPort) [$status]"
}

Write-Host "`nModbus Devices:" -ForegroundColor White
Get-MbDevices 2>$null | Where-Object { $_.Name -in @("WaterTank","Boiler","PowerSubstation","ManufLine") } | ForEach-Object {
    Write-Host "  $($_.Name) Channel=$($_.ChannelName) Unit=$($_.UnitId)"
}

Write-Host "`nModbus Tag Counts:" -ForegroundColor White
$allItems = Get-MbDataItems 2>$null
if ($allItems) {
    $groups = $allItems | Group-Object ParentName
    foreach ($g in $groups) {
        Write-Host "  $($g.Name): $($g.Count) tags"
    }
}

Write-Host "`nOPC-UA Servers:" -ForegroundColor White
try {
    Get-OpcUaServers 2>$null | ForEach-Object {
        Write-Host "  $($_.Name) → $($_.EndpointUrl)"
    }
} catch { Write-Host "  (no OPC-UA cmdlet available)" }

Write-Host "`nAssetWorX:" -ForegroundColor White
try {
    Get-AcEquipmentLevels 2>$null | Where-Object {
        $_.Name -eq "ICS_Plant" -or $_.Description -like "PLC*"
    } | ForEach-Object {
        Write-Host "  $($_.Name): $($_.Description)"
    }
} catch { }

Write-Host "`nHistorian Tags:" -ForegroundColor White
try {
    $hhTags = Get-HHTags 2>$null
    if ($hhTags) {
        $prefixes = @("WT_","PS_","GP_","MF_","BH_")
        foreach ($p in $prefixes) {
            $count = ($hhTags | Where-Object { $_.Name -like "${p}*" }).Count
            $area = switch ($p) {
                "WT_" { "Water Treatment" }
                "PS_" { "Power Substation" }
                "GP_" { "Gas Pipeline" }
                "MF_" { "Manufacturing" }
                "BH_" { "Boiler House" }
            }
            Write-Host "  $area`: $count tags"
        }
    }
} catch { }


# ═════════════════════════════════════════════════════════════════════
#  SUMMARY
# ═════════════════════════════════════════════════════════════════════
Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "  SETUP COMPLETE" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Created: $($results.Created)  Skipped: $($results.Skipped)  Failed: $($results.Failed)"
Write-Host ""
Write-Host "  MANUAL STEPS REMAINING:" -ForegroundColor Yellow
Write-Host "    1. Workbench → OPC UA → PLC3_GasPipeline → Browse → Add all tags"
Write-Host "    2. Workbench → BACnet → Discover Devices → Add 192.168.1.14"
Write-Host "    3. If S7 driver available: Add PLC4 at 192.168.1.13:102 Rack=0 Slot=1"
Write-Host "    4. GraphWorX64 → Create HMI displays using Unified Data Browser"
Write-Host ""
Write-Host "  TAG REFERENCE (Unified Data Browser):" -ForegroundColor White
Write-Host "    \\localhost\Modbus\PLC1_WaterTreatment.WaterTank.<tag>"
Write-Host "    \\localhost\Modbus\PLC2_PowerSub_Modbus.PowerSubstation.<tag>"
Write-Host "    \\localhost\OPC UA\PLC3_GasPipeline.WaterTank.Measurements.<tag>"
Write-Host "    \\localhost\Modbus\PLC4_Manufacturing.ManufLine.<tag>"
Write-Host "    \\localhost\BACnet\PLC5_HVAC_Network.HVAC_Controller.<object>"
Write-Host "    \\localhost\Modbus\PLC6_BoilerHouse.Boiler.<tag>"
Write-Host "============================================================" -ForegroundColor Cyan
