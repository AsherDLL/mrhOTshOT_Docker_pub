#!/usr/bin/env python3
"""
Pull latest from origin/main on every lab machine via pyVmomi Guest Operations.
Run from your Mac: python3 deploy/pull_all.py
"""

import os, ssl, time
from pyVim.connect import SmartConnect, Disconnect
from pyVmomi import vim

ESXI_HOST = os.environ.get('ESXI_HOST', '10.3.229.3')
ESXI_USER = os.environ.get('ESXI_USER', 'user')
ESXI_PASS = os.environ.get('ESXI_PASS', 'LabPass123!')

# (vm_name_substr, guest_user, guest_pass, repo_path)
MACHINES = [
    ('PLC-1-WaterTreat',    'kalilinux', 'labpass123', '/home/kalilinux/v3/mrhOTshOT'),
    ('PLC-2-PowerSub',      'kalilinux', 'labpass123', '/home/kalilinux/v3/mrhOTshOT'),
    ('PLC-3-GasPipeline',   'kalilinux', 'labpass123', '/home/kalilinux/v3/mrhOTshOT'),
    ('PLC-4-Manufactur',    'kalilinux', 'labpass123', '/home/kalilinux/v3/mrhOTshOT'),
    ('PLC-5-BuildingHVAC',  'kalilinux', 'labpass123', '/home/kalilinux/v3/mrhOTshOT'),
    ('PLC-6-BoilerHouse',   'kalilinux', 'labpass123', '/home/kalilinux/v3/mrhOTshOT'),
    ('PLC-7-HeatingDist',   'kalilinux', 'labpass123', '/home/kalilinux/v3/mrhOTshOT'),
    ('PLC-8-WaterUtil',     'kalilinux', 'labpass123', '/home/kalilinux/v3/mrhOTshOT'),
    ('SIS-1-SafetySystem',  'kalilinux', 'labpass123', '/home/kalilinux/v3/mrhOTshOT'),
    ('Attacker Machine',    'kali',      'labpass123', '/home/kali/v3/mrhOTshOT'),
    ('emulated router',     'operator',   'labpass123', '/home/operator/v2/mrhOTshOT'),
    ('OTSOC HMI',           'operator',     'labpass123', None),   # Windows - handled separately
]


def get_vm(content, substr):
    for dc in content.rootFolder.childEntity:
        for v in dc.vmFolder.childEntity:
            if substr.lower() in v.name.lower():
                return v
    return None


def gexec(pm, vm, user, pwd, cmd, timeout=60):
    cr = vim.vm.guest.NamePasswordAuthentication(username=user, password=pwd)
    sp = vim.vm.guest.ProcessManager.ProgramSpec(
        programPath='/bin/bash', arguments=f"-lc '{cmd}'"
    )
    pid = pm.StartProgramInGuest(vm, cr, sp)
    t0 = time.time()
    while time.time() - t0 < timeout:
        procs = pm.ListProcessesInGuest(vm, cr, [pid])
        if procs and procs[0].exitCode is not None:
            return procs[0].exitCode
        time.sleep(2)
    return -1


def gexec_win(pm, vm, user, pwd, cmd_arg, timeout=60):
    """Run a cmd.exe command on a Windows guest."""
    cr = vim.vm.guest.NamePasswordAuthentication(username=user, password=pwd)
    sp = vim.vm.guest.ProcessManager.ProgramSpec(
        programPath=r'C:\Windows\System32\cmd.exe',
        arguments=f'/c {cmd_arg}'
    )
    pid = pm.StartProgramInGuest(vm, cr, sp)
    t0 = time.time()
    while time.time() - t0 < timeout:
        procs = pm.ListProcessesInGuest(vm, cr, [pid])
        if procs and procs[0].exitCode is not None:
            return procs[0].exitCode
        time.sleep(2)
    return -1


def main():
    ctx = ssl._create_unverified_context()
    si  = SmartConnect(host=ESXI_HOST, user=ESXI_USER, pwd=ESXI_PASS, sslContext=ctx)
    content = si.RetrieveContent()
    pm = content.guestOperationsManager.processManager

    print('=' * 60)
    print('  GIT PULL - all lab machines')
    print('=' * 60)

    ok = fail = skip = 0

    for name_substr, user, pwd, repo in MACHINES:
        vm = get_vm(content, name_substr)
        if not vm:
            print(f'  MISS  {name_substr}')
            skip += 1
            continue
        if vm.guest.toolsRunningStatus != 'guestToolsRunning':
            print(f'  SKIP  {vm.name}  (VMware Tools not running)')
            skip += 1
            continue

        # Windows HMI - use cmd.exe
        if name_substr == 'OTSOC HMI':
            repo_win = r'C:\Users\operator\v3\mrhOTshOT'
            rc = gexec_win(pm, vm, user, pwd,
                           f'cd {repo_win} && git pull origin main', timeout=60)
        else:
            rc = gexec(pm, vm, user, pwd,
                       f'cd {repo} && git pull origin main 2>&1 | tail -2', timeout=60)

        status = 'OK' if rc == 0 else f'FAIL(rc={rc})'
        icon   = '[+]' if rc == 0 else '[-]'
        print(f'  {icon}  {vm.name:<35} {status}')
        if rc == 0: ok += 1
        else:       fail += 1

    Disconnect(si)
    print('=' * 60)
    print(f'  {ok} OK  |  {fail} failed  |  {skip} skipped')
    print('=' * 60)


if __name__ == '__main__':
    main()
