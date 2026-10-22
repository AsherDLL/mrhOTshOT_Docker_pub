"""
Reset all PLCs to initial state by restarting their ICS simulation services.

Uses pyVmomi Guest Operations to run `systemctl restart ics-sim-<process>`
inside each VM - no SSH required, same mechanism used throughout the lab.
Requires ESXI_HOST, ESXI_USER, ESXI_PASS, PLC_USER, PLC_PASS env vars.
"""

import os
import re
import ssl
import sys
import time
import logging
import urllib.request

logging.basicConfig(level=logging.INFO, format='%(asctime)s [RESET] %(message)s')
log = logging.getLogger('reset')

PLCS = [
    ('PLC-1-WaterTreatment',   'water_treatment'),
    ('PLC-2-PowerSubstation',  'power_substation'),
    ('PLC-3-GasPipeline',      'gas_pipeline'),
    ('PLC-4-Manufacturing',    'centrifuge'),
    ('PLC-5-BuildingHVAC',     'building_hvac'),
    ('PLC-6-BoilerHouse',      'boiler_house'),
    ('PLC-7-HeatingDistrict',  'heating_district'),
    ('PLC-8-WaterUtilityDNP3', 'water_utility_dnp3'),
    ('PLC-9-SensorNetwork',    'sensor_network'),
    ('SIS-1-SafetySystem',     'safety_system'),
]


def _guest_exec(pm, fm, vm, creds, esxi_host, cmd, timeout=35):
    """Run a shell command inside a VM via VMware Guest Operations and return stdout."""
    from pyVmomi import vim
    out_file = '/tmp/_reset_out.txt'
    # Wrap cmd + redirect entirely inside the bash -lc string so the OS
    # doesn't split '>' as a separate argv entry.
    full_cmd = f'{{ {cmd}; }} > {out_file} 2>&1'
    prog = vim.vm.guest.ProcessManager.ProgramSpec(
        programPath='/bin/bash',
        arguments=f"-lc '{full_cmd}'"
    )
    pid = pm.StartProgramInGuest(vm, creds, prog)
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(2)
        procs = pm.ListProcessesInGuest(vm, creds, pids=[pid])
        if procs and procs[0].exitCode is not None:
            break

    try:
        fi  = fm.InitiateFileTransferFromGuest(vm, creds, out_file)
        # ESXi returns a URL with its own hostname; swap to the IP we connected to.
        url = re.sub(r'https://[^/]+/', f'https://{esxi_host}/', fi.url)
        ctx = ssl._create_unverified_context()
        return urllib.request.urlopen(url, context=ctx).read().decode().strip()
    except Exception as e:
        return f'ERROR reading output: {e}'


def reset_all():
    try:
        from pyVim.connect import SmartConnect, Disconnect
        from pyVmomi import vim
    except ImportError:
        log.error("pyVmomi not installed - cannot restart PLCs via Guest Operations")
        sys.exit(1)

    esxi_host = os.environ.get('ESXI_HOST', '10.3.229.3')
    esxi_user = os.environ.get('ESXI_USER', 'user')
    esxi_pass = os.environ.get('ESXI_PASS', 'LabPass123!')
    plc_user  = os.environ.get('PLC_USER',  'kalilinux')
    plc_pass  = os.environ.get('PLC_PASS',  'labpass123')

    log.info('=' * 60)
    log.info('RESETTING ALL 10 PLCs - restarting ICS services')
    log.info('=' * 60)

    ctx = ssl._create_unverified_context()
    si  = SmartConnect(host=esxi_host, user=esxi_user, pwd=esxi_pass, sslContext=ctx)
    content = si.RetrieveContent()
    container = content.viewManager.CreateContainerView(
        content.rootFolder, [vim.VirtualMachine], True)
    vms = {v.summary.config.name: v for v in container.view}
    container.Destroy()

    pm    = content.guestOperationsManager.processManager
    fm    = content.guestOperationsManager.fileManager
    creds = vim.vm.guest.NamePasswordAuthentication(username=plc_user, password=plc_pass)

    ok = 0
    for vm_name, process in PLCS:
        svc = f'ics-sim-{process}'
        vm  = vms.get(vm_name)
        if not vm:
            log.warning(f'  [!] {vm_name} not found in ESXi')
            continue
        if vm.guest.toolsRunningStatus != 'guestToolsRunning':
            log.warning(f'  [!] {vm_name} VMware Tools not running - skipping')
            continue

        log.info(f'Restarting {svc} on {vm_name}...')
        out = _guest_exec(pm, fm, vm, creds, esxi_host,
            f'echo {plc_pass} | sudo -S systemctl restart {svc} && sleep 4 && systemctl is-active {svc}',
            timeout=35)
        # 'active' appears in normal output; 'inactive'/'failed' indicate failure
        if 'active' in out and 'inactive' not in out and 'failed' not in out:
            log.info(f'  [+] {svc} restarted -> active')
            ok += 1
        else:
            tail = out.strip().split('\n')[-1].strip() if out else '(no output)'
            log.warning(f'  [!] {svc} unexpected status: {tail}')

    Disconnect(si)
    log.info('=' * 60)
    log.info(f'RESET COMPLETE - {ok}/{len(PLCS)} services restarted')
    log.info('Ready for next simulation')
    log.info('=' * 60)


if __name__ == '__main__':
    reset_all()
