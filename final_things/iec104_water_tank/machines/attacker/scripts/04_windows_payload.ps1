# Windows Payload Script
# Executes calc.exe using multiple techniques to generate Cortex XDR alerts
# Educational purpose: Demonstrate Windows attack TTPs for security testing

# Banner
Write-Host "╔═══════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║          Windows Payload Execution Framework                 ║" -ForegroundColor Cyan
Write-Host "║            Multi-Technique calc.exe Launcher                 ║" -ForegroundColor Cyan
Write-Host "╚═══════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# Configuration
$TargetExecutable = "calc.exe"
$LogFile = "$env:TEMP\payload_execution_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"

# Logging function
function Write-Log {
    param([string]$Message, [string]$Level = "INFO")

    $Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $LogMessage = "[$Timestamp] [$Level] $Message"

    Write-Host $LogMessage -ForegroundColor $(
        switch ($Level) {
            "SUCCESS" { "Green" }
            "ERROR" { "Red" }
            "WARNING" { "Yellow" }
            default { "White" }
        }
    )

    Add-Content -Path $LogFile -Value $LogMessage
}

# Initial reconnaissance
Write-Log "Starting payload execution sequence..." "INFO"
Write-Log "Target: $TargetExecutable" "INFO"
Write-Log "Hostname: $env:COMPUTERNAME" "INFO"
Write-Log "Username: $env:USERNAME" "INFO"
Write-Log "Domain: $env:USERDOMAIN" "INFO"

# Technique 1: Direct Process Creation (baseline)
function Invoke-DirectExecution {
    Write-Log "TECHNIQUE 1: Direct Process Execution" "INFO"

    try {
        $Process = Start-Process -FilePath $TargetExecutable -PassThru
        Write-Log "Process started with PID: $($Process.Id)" "SUCCESS"
        Write-Log "[ALERT] Direct process creation - Low suspicion" "WARNING"

        Start-Sleep -Seconds 3
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        Write-Log "Process terminated" "INFO"

    } catch {
        Write-Log "Direct execution failed: $_" "ERROR"
    }
}

# Technique 2: WMI Process Creation (generates WMI alerts)
function Invoke-WMIExecution {
    Write-Log "TECHNIQUE 2: WMI Process Creation" "INFO"

    try {
        $Result = Invoke-WmiMethod -Class Win32_Process -Name Create -ArgumentList $TargetExecutable
        Write-Log "WMI process created with return value: $($Result.ReturnValue)" "SUCCESS"
        Write-Log "[ALERT] WMI-based process creation - Medium suspicion" "WARNING"

        Start-Sleep -Seconds 3

        # Find and kill the process
        $Processes = Get-WmiObject Win32_Process | Where-Object { $_.Name -eq $TargetExecutable }
        foreach ($Proc in $Processes) {
            $Proc.Terminate() | Out-Null
        }
        Write-Log "WMI process terminated" "INFO"

    } catch {
        Write-Log "WMI execution failed: $_" "ERROR"
    }
}

# Technique 3: PowerShell Invoke-Expression (generates script execution alerts)
function Invoke-IEXExecution {
    Write-Log "TECHNIQUE 3: Invoke-Expression Execution" "INFO"

    try {
        $Command = "Start-Process -FilePath '$TargetExecutable'"
        $ScriptBlock = [ScriptBlock]::Create($Command)

        Write-Log "Executing via IEX..." "INFO"
        Invoke-Expression -Command $Command

        Write-Log "[ALERT] Invoke-Expression usage - High suspicion" "WARNING"

        Start-Sleep -Seconds 3
        Stop-Process -Name "CalculatorApp" -Force -ErrorAction SilentlyContinue
        Stop-Process -Name "win32calc" -Force -ErrorAction SilentlyContinue

    } catch {
        Write-Log "IEX execution failed: $_" "ERROR"
    }
}

# Technique 4: Base64 Encoded Command (obfuscation detection)
function Invoke-EncodedExecution {
    Write-Log "TECHNIQUE 4: Base64 Encoded Execution" "INFO"

    try {
        $Command = "Start-Process -FilePath '$TargetExecutable'"
        $Bytes = [System.Text.Encoding]::Unicode.GetBytes($Command)
        $EncodedCommand = [Convert]::ToBase64String($Bytes)

        Write-Log "Encoded command length: $($EncodedCommand.Length)" "INFO"

        # Execute encoded command
        powershell.exe -EncodedCommand $EncodedCommand

        Write-Log "[ALERT] Base64 encoded PowerShell - High suspicion" "WARNING"

        Start-Sleep -Seconds 3
        Stop-Process -Name "CalculatorApp" -Force -ErrorAction SilentlyContinue
        Stop-Process -Name "win32calc" -Force -ErrorAction SilentlyContinue

    } catch {
        Write-Log "Encoded execution failed: $_" "ERROR"
    }
}

# Technique 5: Scheduled Task Creation (persistence simulation)
function Invoke-ScheduledTaskExecution {
    Write-Log "TECHNIQUE 5: Scheduled Task Execution" "INFO"

    $TaskName = "SystemMaintenanceTask_" + (Get-Random -Maximum 9999)

    try {
        # Create scheduled task
        $Action = New-ScheduledTaskAction -Execute $TargetExecutable
        $Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddSeconds(5)
        $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

        Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Force | Out-Null

        Write-Log "Scheduled task created: $TaskName" "SUCCESS"
        Write-Log "[ALERT] Scheduled task creation - Medium suspicion" "WARNING"

        Start-Sleep -Seconds 8

        # Cleanup
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
        Write-Log "Scheduled task removed" "INFO"

        Stop-Process -Name "CalculatorApp" -Force -ErrorAction SilentlyContinue
        Stop-Process -Name "win32calc" -Force -ErrorAction SilentlyContinue

    } catch {
        Write-Log "Scheduled task execution failed: $_" "ERROR"
    }
}

# Technique 6: Registry Run Key (persistence simulation)
function Invoke-RegistryPersistence {
    Write-Log "TECHNIQUE 6: Registry Run Key Persistence" "INFO"

    $RegPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run"
    $RegName = "SystemUpdate_" + (Get-Random -Maximum 9999)

    try {
        # Add registry run key
        Set-ItemProperty -Path $RegPath -Name $RegName -Value $TargetExecutable -Force

        Write-Log "Registry run key created: $RegName" "SUCCESS"
        Write-Log "[ALERT] Registry persistence - High suspicion" "WARNING"

        # Execute the target
        Start-Process -FilePath $TargetExecutable

        Start-Sleep -Seconds 3

        # Cleanup
        Remove-ItemProperty -Path $RegPath -Name $RegName -ErrorAction SilentlyContinue
        Write-Log "Registry key removed" "INFO"

        Stop-Process -Name "CalculatorApp" -Force -ErrorAction SilentlyContinue
        Stop-Process -Name "win32calc" -Force -ErrorAction SilentlyContinue

    } catch {
        Write-Log "Registry persistence failed: $_" "ERROR"
    }
}

# Technique 7: COM Object Execution
function Invoke-COMExecution {
    Write-Log "TECHNIQUE 7: COM Object Execution" "INFO"

    try {
        $Shell = New-Object -ComObject WScript.Shell
        $Shell.Run($TargetExecutable)

        Write-Log "COM object execution successful" "SUCCESS"
        Write-Log "[ALERT] COM-based execution - Medium suspicion" "WARNING"

        Start-Sleep -Seconds 3

        Stop-Process -Name "CalculatorApp" -Force -ErrorAction SilentlyContinue
        Stop-Process -Name "win32calc" -Force -ErrorAction SilentlyContinue

    } catch {
        Write-Log "COM execution failed: $_" "ERROR"
    }
}

# Technique 8: Reflective Loading Simulation (advanced)
function Invoke-ReflectiveExecution {
    Write-Log "TECHNIQUE 8: Process Hollowing Simulation" "INFO"

    try {
        # Start a suspended process (notepad as hollow target)
        $StartInfo = New-Object System.Diagnostics.ProcessStartInfo
        $StartInfo.FileName = "notepad.exe"
        $StartInfo.WindowStyle = "Hidden"

        $Process = [System.Diagnostics.Process]::Start($StartInfo)

        Write-Log "Hollow process created: notepad.exe (PID: $($Process.Id))" "SUCCESS"
        Write-Log "[ALERT] Suspicious process creation pattern - High suspicion" "WARNING"

        # Now start the actual payload
        Start-Process -FilePath $TargetExecutable

        Start-Sleep -Seconds 3

        # Cleanup
        Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        Stop-Process -Name "CalculatorApp" -Force -ErrorAction SilentlyContinue
        Stop-Process -Name "win32calc" -Force -ErrorAction SilentlyContinue

    } catch {
        Write-Log "Reflective execution failed: $_" "ERROR"
    }
}

# Technique 9: Network-based Execution Simulation
function Invoke-NetworkExecution {
    Write-Log "TECHNIQUE 9: Network Download and Execute Simulation" "INFO"

    try {
        # Simulate downloading payload (actually just copying local file)
        $RemoteURL = "http://malicious-c2-server.evil/payload.exe"
        $LocalPath = "$env:TEMP\downloaded_payload.exe"

        Write-Log "Simulating download from: $RemoteURL" "INFO"

        # Copy calc.exe to temp location to simulate download
        Copy-Item -Path "C:\Windows\System32\calc.exe" -Destination $LocalPath -Force

        Write-Log "File 'downloaded' to: $LocalPath" "SUCCESS"
        Write-Log "[ALERT] Network download - Wildfire analysis triggered" "WARNING"

        # Execute the 'downloaded' file
        Start-Process -FilePath $LocalPath

        Start-Sleep -Seconds 3

        # Cleanup
        Stop-Process -Name "CalculatorApp" -Force -ErrorAction SilentlyContinue
        Stop-Process -Name "win32calc" -Force -ErrorAction SilentlyContinue
        Remove-Item -Path $LocalPath -Force -ErrorAction SilentlyContinue

    } catch {
        Write-Log "Network execution failed: $_" "ERROR"
    }
}

# Technique 10: Fileless Execution Simulation
function Invoke-FilelessExecution {
    Write-Log "TECHNIQUE 10: Fileless Attack Simulation" "INFO"

    try {
        # Execute command directly from memory-like pattern
        $Command = @"
`$bytes = [System.IO.File]::ReadAllBytes('C:\Windows\System32\calc.exe')
`$assembly = [System.Reflection.Assembly]::Load(`$bytes)
Start-Process -FilePath 'calc.exe'
"@

        $ScriptBlock = [ScriptBlock]::Create($Command)
        Invoke-Command -ScriptBlock $ScriptBlock

        Write-Log "[ALERT] Fileless execution pattern - Critical suspicion" "WARNING"

        Start-Sleep -Seconds 3

        Stop-Process -Name "CalculatorApp" -Force -ErrorAction SilentlyContinue
        Stop-Process -Name "win32calc" -Force -ErrorAction SilentlyContinue

    } catch {
        Write-Log "Fileless execution failed: $_" "ERROR"
    }
}

# Technique 11: Living off the Land (LOLBin)
function Invoke-LOLBinExecution {
    Write-Log "TECHNIQUE 11: Living off the Land Binary" "INFO"

    try {
        # Use rundll32 to execute
        Write-Log "Using rundll32.exe for execution..." "INFO"

        # Alternative: use cmd.exe
        cmd.exe /c start calc.exe

        Write-Log "[ALERT] LOLBin usage detected - Medium suspicion" "WARNING"

        Start-Sleep -Seconds 3

        Stop-Process -Name "CalculatorApp" -Force -ErrorAction SilentlyContinue
        Stop-Process -Name "win32calc" -Force -ErrorAction SilentlyContinue

    } catch {
        Write-Log "LOLBin execution failed: $_" "ERROR"
    }
}

# Execute all techniques sequentially
Write-Log "═══════════════════════════════════════════" "INFO"
Write-Log "   EXECUTING MULTI-TECHNIQUE ATTACK CHAIN   " "INFO"
Write-Log "═══════════════════════════════════════════" "INFO"
Write-Host ""

# Delay between techniques to allow alerts to be generated distinctly
$TechniqueDelay = 5

Write-Host "[*] Executing 11 different attack techniques..."
Write-Host "[*] Each technique will trigger different alert patterns"
Write-Host "[*] Monitor Cortex XDR, XSIAM, and Device Security for alerts"
Write-Host ""

Start-Sleep -Seconds 3

Invoke-DirectExecution
Start-Sleep -Seconds $TechniqueDelay

Invoke-WMIExecution
Start-Sleep -Seconds $TechniqueDelay

Invoke-IEXExecution
Start-Sleep -Seconds $TechniqueDelay

Invoke-EncodedExecution
Start-Sleep -Seconds $TechniqueDelay

Invoke-ScheduledTaskExecution
Start-Sleep -Seconds $TechniqueDelay

Invoke-RegistryPersistence
Start-Sleep -Seconds $TechniqueDelay

Invoke-COMExecution
Start-Sleep -Seconds $TechniqueDelay

Invoke-ReflectiveExecution
Start-Sleep -Seconds $TechniqueDelay

Invoke-NetworkExecution
Start-Sleep -Seconds $TechniqueDelay

Invoke-FilelessExecution
Start-Sleep -Seconds $TechniqueDelay

Invoke-LOLBinExecution

# Final summary
Write-Host ""
Write-Log "═══════════════════════════════════════════" "INFO"
Write-Log "     ATTACK CHAIN EXECUTION COMPLETE        " "SUCCESS"
Write-Log "═══════════════════════════════════════════" "INFO"
Write-Host ""

Write-Host "[+] All techniques executed successfully" -ForegroundColor Green
Write-Host "[+] Expected Alerts Generated:" -ForegroundColor Yellow
Write-Host "    - Process creation events (Cortex XDR)" -ForegroundColor White
Write-Host "    - WMI activity (XDR Behavioral Analytics)" -ForegroundColor White
Write-Host "    - Script execution (PowerShell logging)" -ForegroundColor White
Write-Host "    - Base64 encoded commands (obfuscation detection)" -ForegroundColor White
Write-Host "    - Scheduled task creation (persistence detection)" -ForegroundColor White
Write-Host "    - Registry modification (persistence detection)" -ForegroundColor White
Write-Host "    - COM object abuse (behavioral detection)" -ForegroundColor White
Write-Host "    - Process hollowing patterns (injection detection)" -ForegroundColor White
Write-Host "    - Network downloads (Wildfire analysis)" -ForegroundColor White
Write-Host "    - Fileless execution (in-memory threat detection)" -ForegroundColor White
Write-Host "    - LOLBin abuse (living-off-the-land detection)" -ForegroundColor White
Write-Host ""
Write-Host "[+] Log file: $LogFile" -ForegroundColor Cyan
Write-Host ""

# Display log file content
Write-Host "════════════════════════ EXECUTION LOG ════════════════════════" -ForegroundColor Cyan
Get-Content -Path $LogFile
Write-Host "══════════════════════════════════════════════════════════════" -ForegroundColor Cyan
