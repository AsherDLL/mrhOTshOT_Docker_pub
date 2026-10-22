#!/usr/bin/env python3
"""
ESXi & VM Management Helpers for mrhOTshOT ICS Plant

All credentials are read from environment variables:
  ESXI_HOST       - ESXi host IP (default: 10.3.229.3)
  ESXI_USER       - ESXi login user
  ESXI_PASS       - ESXi login password
  PLC_USER        - PLC VM guest OS username
  PLC_PASS        - PLC VM guest OS password
  HMI_USER        - HMI VM guest OS username
  HMI_PASS        - HMI VM guest OS password
  HIST_USER       - Historian VM guest OS username
  HIST_PASS       - Historian VM guest OS password

Usage:
  export ESXI_HOST=10.3.229.3 ESXI_USER=user ESXI_PASS=xxx
  export PLC_USER=kalilinux PLC_PASS=xxx
  export HMI_USER=operator HMI_PASS=xxx
  export HIST_USER=operator HIST_PASS=xxx

  python deploy/esxi_helpers.py status          # Show all VM status
  python deploy/esxi_helpers.py verify          # Verify PLCs, HMI, Historian
  python deploy/esxi_helpers.py pull            # Git pull on all VMs
  python deploy/esxi_helpers.py restart-plcs    # Restart all PLC services
  python deploy/esxi_helpers.py restart-hmi     # Restart HMI
  python deploy/esxi_helpers.py deploy-plcs     # Full deploy: pull + copy + restart
"""

import os
import ssl
import sys
import time
import threading
import urllib.request
from typing import Optional, Dict, Any

try:
    from pyVim.connect import SmartConnect, Disconnect
    from pyVmomi import vim
except ImportError:
    print("ERROR: pyvmomi not installed. Run: pip install pyvmomi")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

def get_env(name: str, default: str = None) -> str:
    val = os.environ.get(name, default)
    if not val:
        print(f"ERROR: Environment variable {name} not set")
        sys.exit(1)
    return val


def esxi_creds():
    return get_env('ESXI_HOST', '10.3.229.3'), get_env('ESXI_USER'), get_env('ESXI_PASS')


def plc_creds():
    return get_env('PLC_USER'), get_env('PLC_PASS')


def hmi_creds():
    return get_env('HMI_USER'), get_env('HMI_PASS')


def hist_creds():
    return get_env('HIST_USER'), get_env('HIST_PASS')


# ---------------------------------------------------------------------------
# ESXi connection
# ---------------------------------------------------------------------------

def connect_esxi():
    host, user, pwd = esxi_creds()
    ctx = ssl._create_unverified_context()
    si = SmartConnect(host=host, user=user, pwd=pwd, sslContext=ctx)
    return si


def get_vms(si, name_filter=None):
    content = si.RetrieveContent()
    container = content.viewManager.CreateContainerView(
        content.rootFolder, [vim.VirtualMachine], True
    )
    vms = {}
    for vm in container.view:
        name = vm.summary.config.name
        if name_filter is None or name_filter(name):
            vms[name] = vm
    container.Destroy()
    return vms


# ---------------------------------------------------------------------------
# Guest operations
# ---------------------------------------------------------------------------

def guest_exec(si, vm, user, pwd, cmd, timeout=30, is_windows=False):
    """Execute a command inside a VM via VMware Guest Operations. Returns output."""
    content = si.RetrieveContent()
    pm = content.guestOperationsManager.processManager
    fmgr = content.guestOperationsManager.fileManager
    creds = vim.vm.guest.NamePasswordAuthentication(username=user, password=pwd)

    if is_windows:
        out_file = 'C:\\temp\\cmd_out.txt'
        prog = vim.vm.guest.ProcessManager.ProgramSpec(
            programPath='C:\\Windows\\System32\\cmd.exe',
            arguments=f'/c {cmd} > {out_file} 2>&1'
        )
    else:
        out_file = '/tmp/cmd_out.txt'
        prog = vim.vm.guest.ProcessManager.ProgramSpec(
            programPath='/bin/bash',
            arguments=f'-c "{cmd}" > {out_file} 2>&1'
        )

    pid = pm.StartProgramInGuest(vm, creds, prog)

    for _ in range(timeout // 2):
        time.sleep(2)
        procs = pm.ListProcessesInGuest(vm, creds, pids=[pid])
        if procs and procs[0].endTime:
            break

    try:
        fi = fmgr.InitiateFileTransferFromGuest(vm, creds, out_file)
        host, _, _ = esxi_creds()
        url = fi.url.replace("*", host)
        ctx = ssl._create_unverified_context()
        resp = urllib.request.urlopen(url, context=ctx)
        return resp.read().decode().strip()
    except Exception as e:
        return f"ERROR reading output: {e}"


def guest_upload(si, vm, user, pwd, local_data: bytes, remote_path: str):
    """Upload data to a file inside a VM."""
    content = si.RetrieveContent()
    fmgr = content.guestOperationsManager.fileManager
    creds = vim.vm.guest.NamePasswordAuthentication(username=user, password=pwd)
    attr = vim.vm.guest.FileManager.FileAttributes()
    url = fmgr.InitiateFileTransferToGuest(vm, creds, remote_path, attr, len(local_data), True)
    host, _, _ = esxi_creds()
    url = url.replace("*", host)
    req = urllib.request.Request(url, data=local_data, method='PUT')
    req.add_header('Content-Type', 'application/octet-stream')
    ctx = ssl._create_unverified_context()
    urllib.request.urlopen(req, context=ctx)


# ---------------------------------------------------------------------------
# VM layout
# ---------------------------------------------------------------------------

PLC_VMS = {
    "PLC-1-WaterTreatment":  ("192.168.1.10", "water_treatment"),
    "PLC-2-PowerSubstation": ("192.168.1.11", "power_substation"),
    "PLC-3-GasPipeline":     ("192.168.1.12", "gas_pipeline"),
    "PLC-4-Centrifuge":      ("192.168.1.13", "centrifuge"),
    "PLC-5-BuildingHVAC":    ("192.168.1.14", "building_hvac"),
    "PLC-6-BoilerHouse":     ("192.168.1.15", "boiler_house"),
    "PLC-7-HeatingDistrict": ("192.168.1.16", "heating_district"),
    "PLC-8-WaterUtilityDNP3":("192.168.1.17", "water_utility_dnp3"),
    "PLC-9-SensorNetwork":   ("192.168.1.18", "sensor_network"),
    "SIS-1-SafetySystem":    ("192.168.1.19", "safety_system"),
}

HMI_VM = "Windows 10 - OTSOC HMI"
HIST_VM = "historian ot"
ATTACKER_VM = "Attacker Machine - Kali Linux"

REPO_PATH_LINUX = "/home/{user}/v3/mrhOTshOT"
REPO_PATH_WINDOWS = "C:\\Users\\{user}\\v3\\mrhOTshOT"
ICS_DIR = "final_things/iec104_water_tank"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_status():
    """Show status of all project VMs."""
    si = connect_esxi()
    vms = get_vms(si)

    print(f"{'VM Name':<35} {'Power':<12} {'IP':<18} {'Tools'}")
    print("-" * 85)

    targets = list(PLC_VMS.keys()) + [HMI_VM, HIST_VM, ATTACKER_VM]
    for name in sorted(vms.keys()):
        if name in targets or name.startswith("PLC-"):
            vm = vms[name]
            ip = vm.guest.ipAddress or 'N/A'
            print(f"  {name:<33} {vm.runtime.powerState:<12} {ip:<18} {vm.guest.toolsRunningStatus}")

    Disconnect(si)


def cmd_verify():
    """Verify all PLCs are running, HMI is up, and check git commits."""
    si = connect_esxi()
    vms = get_vms(si)
    plc_user, plc_pass = plc_creds()
    hmi_user, hmi_pass = hmi_creds()

    results = {}

    def check_plc(name, vm):
        if vm.guest.toolsRunningStatus != "guestToolsRunning":
            results[name] = f"Tools not running (power: {vm.runtime.powerState})"
            return
        ip, proc = PLC_VMS[name]
        out = guest_exec(si, vm, plc_user, plc_pass,
                         f"systemctl is-active ics-sim-{proc} && git -C {REPO_PATH_LINUX.format(user=plc_user)} log --oneline -1",
                         timeout=10)
        results[name] = f"IP:{ip} | {out}"

    def check_hmi():
        vm = vms.get(HMI_VM)
        if not vm or vm.guest.toolsRunningStatus != "guestToolsRunning":
            results[HMI_VM] = "Not running"
            return
        out = guest_exec(si, vm, hmi_user, hmi_pass,
                         f'cd /d {REPO_PATH_WINDOWS.format(user=hmi_user)} & git log --oneline -1',
                         timeout=10, is_windows=True)
        results[HMI_VM] = out

    threads = []
    for name in PLC_VMS:
        if name in vms:
            t = threading.Thread(target=check_plc, args=(name, vms[name]))
            t.start()
            threads.append(t)

    t = threading.Thread(target=check_hmi)
    t.start()
    threads.append(t)

    for t in threads:
        t.join()

    print(f"\n{'Machine':<35} {'Status'}")
    print("-" * 90)
    for name in sorted(results.keys()):
        print(f"  {name:<33} {results[name]}")

    Disconnect(si)


def cmd_pull():
    """Git pull on all PLCs, HMI, and Attacker."""
    si = connect_esxi()
    vms = get_vms(si)
    plc_user, plc_pass = plc_creds()
    hmi_user, hmi_pass = hmi_creds()

    results = {}

    def pull_linux(name, vm, user, pwd):
        repo = REPO_PATH_LINUX.format(user=user)
        out = guest_exec(si, vm, user, pwd,
                         f"export GIT_SSH_COMMAND='ssh -o StrictHostKeyChecking=no' && cd {repo} && git pull && git log --oneline -1",
                         timeout=30)
        results[name] = out.strip().split('\n')[-1]

    def pull_windows(name, vm, user, pwd):
        repo = REPO_PATH_WINDOWS.format(user=user)
        out = guest_exec(si, vm, user, pwd,
                         f'cd /d {repo} & git pull & git log --oneline -1',
                         timeout=30, is_windows=True)
        results[name] = out.strip().split('\n')[-1] if out else "ERROR"

    threads = []
    for name in PLC_VMS:
        if name in vms and vms[name].guest.toolsRunningStatus == "guestToolsRunning":
            t = threading.Thread(target=pull_linux, args=(name, vms[name], plc_user, plc_pass))
            t.start()
            threads.append(t)

    if HMI_VM in vms and vms[HMI_VM].guest.toolsRunningStatus == "guestToolsRunning":
        t = threading.Thread(target=pull_windows, args=(HMI_VM, vms[HMI_VM], hmi_user, hmi_pass))
        t.start()
        threads.append(t)

    if ATTACKER_VM in vms and vms[ATTACKER_VM].guest.toolsRunningStatus == "guestToolsRunning":
        t = threading.Thread(target=pull_linux, args=(ATTACKER_VM, vms[ATTACKER_VM], 'kali', plc_pass))
        t.start()
        threads.append(t)

    for t in threads:
        t.join()

    for name in sorted(results.keys()):
        print(f"  {name:<35} {results[name]}")

    Disconnect(si)


def cmd_restart_plcs():
    """Restart all PLC systemd services."""
    si = connect_esxi()
    vms = get_vms(si)
    plc_user, plc_pass = plc_creds()

    results = {}

    def restart(name, vm):
        _, proc = PLC_VMS[name]
        out = guest_exec(si, vm, plc_user, plc_pass,
                         f"echo {plc_pass} | sudo -S systemctl restart ics-sim-{proc} && sleep 2 && systemctl is-active ics-sim-{proc}",
                         timeout=15)
        results[name] = out.strip().split('\n')[-1]

    threads = []
    for name in PLC_VMS:
        if name in vms and vms[name].guest.toolsRunningStatus == "guestToolsRunning":
            t = threading.Thread(target=restart, args=(name, vms[name]))
            t.start()
            threads.append(t)

    for t in threads:
        t.join()

    for name in sorted(results.keys()):
        print(f"  {name:<30} {results[name]}")

    Disconnect(si)


def cmd_restart_hmi():
    """Kill and restart HMI on Windows."""
    si = connect_esxi()
    vms = get_vms(si)
    hmi_user, hmi_pass = hmi_creds()

    vm = vms.get(HMI_VM)
    if not vm:
        print("HMI VM not found")
        return

    guest_exec(si, vm, hmi_user, hmi_pass,
               'taskkill /F /IM python.exe 2>nul',
               timeout=5, is_windows=True)
    time.sleep(2)

    content = si.RetrieveContent()
    pm = content.guestOperationsManager.processManager
    creds = vim.vm.guest.NamePasswordAuthentication(username=hmi_user, password=hmi_pass)

    repo = REPO_PATH_WINDOWS.format(user=hmi_user)
    python = f"C:\\Users\\{hmi_user}\\AppData\\Local\\Programs\\Python\\Python311\\python.exe"
    prog = vim.vm.guest.ProcessManager.ProgramSpec(
        programPath=python,
        arguments=f'{repo}\\{ICS_DIR}\\hmi\\unified_hmi.py --config {repo}\\{ICS_DIR}\\deploy\\hmi_config.json'
    )
    pid = pm.StartProgramInGuest(vm, creds, prog)
    time.sleep(3)
    procs = pm.ListProcessesInGuest(vm, creds, pids=[pid])
    status = "RUNNING" if procs and not procs[0].endTime else "FAILED"
    print(f"  HMI: {status} (PID {pid})")

    Disconnect(si)


def cmd_snapshot():
    """Take VMware snapshots of all project VMs (rollback safety net)."""
    from datetime import datetime
    snap_name = f"pre-refactor-{datetime.now().strftime('%Y-%m-%d-%H%M')}"
    si = connect_esxi()
    vms = get_vms(si)

    targets = list(PLC_VMS.keys()) + [HMI_VM, HIST_VM, ATTACKER_VM, "openplc"]
    results = {}

    def snap(name, vm):
        try:
            desc = f"Automated snapshot before attack-realism refactor"
            task = vm.CreateSnapshot_Task(name=snap_name, description=desc,
                                          memory=False, quiesce=False)
            while task.info.state in ('queued', 'running'):
                time.sleep(2)
            if task.info.state == 'success':
                results[name] = f"OK  snapshot={snap_name}"
            else:
                results[name] = f"FAIL  {task.info.error}"
        except Exception as e:
            results[name] = f"ERROR  {e}"

    threads = []
    for name in targets:
        if name in vms:
            t = threading.Thread(target=snap, args=(name, vms[name]))
            t.start()
            threads.append(t)
        else:
            results[name] = "NOT FOUND"

    for t in threads:
        t.join()

    print(f"\nSnapshot: {snap_name}")
    print(f"{'VM':<35} {'Result'}")
    print("-" * 70)
    for name in sorted(results.keys()):
        print(f"  {name:<33} {results[name]}")

    Disconnect(si)


def cmd_deploy_plcs():
    """Full deploy: git pull, copy server files to /opt/ics-sim, restart services."""
    si = connect_esxi()
    vms = get_vms(si)
    plc_user, plc_pass = plc_creds()

    results = {}

    def deploy(name, vm):
        _, proc = PLC_VMS[name]
        repo = REPO_PATH_LINUX.format(user=plc_user)
        cmd = (
            f"export GIT_SSH_COMMAND='ssh -o StrictHostKeyChecking=no' && "
            f"cd {repo} && git pull && "
            f"echo {plc_pass} | sudo -S cp -a {ICS_DIR}/server/* /opt/ics-sim/server/ && "
            f"echo {plc_pass} | sudo -S cp -f {ICS_DIR}/water_tank_server.py /opt/ics-sim/ && "
            f"echo {plc_pass} | sudo -S systemctl restart ics-sim-{proc} && "
            f"sleep 2 && systemctl is-active ics-sim-{proc}"
        )
        out = guest_exec(si, vm, plc_user, plc_pass, cmd, timeout=30)
        results[name] = out.strip().split('\n')[-1]

    threads = []
    for name in PLC_VMS:
        if name in vms and vms[name].guest.toolsRunningStatus == "guestToolsRunning":
            t = threading.Thread(target=deploy, args=(name, vms[name]))
            t.start()
            threads.append(t)

    for t in threads:
        t.join()

    for name in sorted(results.keys()):
        print(f"  {name:<30} {results[name]}")

    Disconnect(si)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
# New PLC definitions - the 4 VMs to clone
# ---------------------------------------------------------------------------

NEW_PLCS = {
    "PLC-7-HeatingDistrict":  {"ip": "192.168.1.16", "process": "heating_district",   "last_octet": 16},
    "PLC-8-WaterUtilityDNP3": {"ip": "192.168.1.17", "process": "water_utility_dnp3", "last_octet": 17},
    "PLC-9-SensorNetwork":    {"ip": "192.168.1.18", "process": "sensor_network",     "last_octet": 18},
    "SIS-1-SafetySystem":     {"ip": "192.168.1.19", "process": "safety_system",      "last_octet": 19},
}

# Base VM to clone from - must exist and be powered off before cloning
BASE_VM_NAME = "PLC-6-BoilerHouse"  # Same Kali base as existing PLCs

# Datastore where VMs live (adjust if your ESXi uses a different name)
DATASTORE_NAME = "datastore1"


def _wait_task(task, label="task", timeout=300):
    """Poll a vSphere task until complete or timeout."""
    import time as _time
    deadline = _time.time() + timeout
    while _time.time() < deadline:
        if task.info.state == 'success':
            return True
        if task.info.state == 'error':
            print(f"  [!] {label} FAILED: {task.info.error.msg}")
            return False
        _time.sleep(3)
    print(f"  [!] {label} TIMED OUT after {timeout}s")
    return False


def cmd_clone_new_plcs():
    """
    Clone 4 new PLC VMs from base image via ESXi datastore file copy.

    Steps per VM:
      1. File-copy VMDK + VMX on ESXi datastore
      2. Register new VMX as a new VM
      3. Answer UUID question ('I copied it')
      4. Set unique MAC address (00:50:56:3F:xx:xx)
      5. Power on
      6. Wait for VMware Tools → set static IP via nmcli
      7. Run setup_vm.sh <process> inside the guest
    """
    import re as _re

    si = connect_esxi()
    content = si.RetrieveContent()
    vms = get_vms(si)

    # Resolve base VM
    base_vm = vms.get(BASE_VM_NAME)
    if not base_vm:
        print(f"[ERROR] Base VM '{BASE_VM_NAME}' not found. Available: {list(vms.keys())}")
        Disconnect(si); return

    base_files = base_vm.config.files
    base_vmx_path = base_files.vmPathName  # e.g. "[datastore1] PLC-6-BoilerHouse/PLC-6-BoilerHouse.vmx"
    base_ds_name  = base_vmx_path.split(']')[0].lstrip('[')
    base_vm_dir   = base_vmx_path.split('] ')[1].rsplit('/', 1)[0]

    print(f"\nBase VM       : {BASE_VM_NAME}")
    print(f"Base VMX path : {base_vmx_path}")
    print(f"Datastore     : {base_ds_name}")
    print()

    # Resolve datastore and datacenter
    dc = content.rootFolder.childEntity[0]
    ds_obj = next((d for d in dc.datastore if d.name == base_ds_name), None)
    if not ds_obj:
        print(f"[ERROR] Datastore '{base_ds_name}' not found.")
        Disconnect(si); return

    fb = content.fileManager          # DatastoreFileManager for copies/moves
    plc_user, plc_pass = plc_creds()
    results = {}

    for vm_name, cfg in NEW_PLCS.items():
        proc    = cfg["process"]
        new_ip  = cfg["ip"]
        octet   = cfg["last_octet"]
        mac     = f"00:50:56:3F:00:{octet:02x}"

        print(f"{'='*60}")
        print(f"Cloning {vm_name}  ({new_ip})  [{proc}]")
        print(f"{'='*60}")

        # ── 1. Check if VM already exists ───────────────────────────────
        if vm_name in vms:
            print(f"  [~] VM already exists - skipping clone, will reprovision")
            target_vm = vms[vm_name]
        else:
            # ── 2. File-copy VMX + VMDK on datastore ────────────────────
            new_dir = vm_name
            new_vmx = f"[{base_ds_name}] {new_dir}/{vm_name}.vmx"

            # CopyDatastoreFile_Task creates the destination dir automatically.
            # Do NOT call MakeDirectory first - ESXi refuses to copy into an existing dir.
            print(f"  [*] Copying base VM files to [{base_ds_name}] {new_dir}/")
            task = fb.CopyDatastoreFile_Task(
                sourceName=f"[{base_ds_name}] {base_vm_dir}",
                sourceDatacenter=dc,
                destinationName=f"[{base_ds_name}] {new_dir}",
                destinationDatacenter=dc,
                force=False,
            )
            if not _wait_task(task, f"copy {vm_name}"):
                results[vm_name] = "FAILED (file copy)"
                continue

            # ── 3. Patch the copied VMX: displayName + MAC ───────────────
            print(f"  [*] Patching VMX for {vm_name}")
            browser = ds_obj.browser
            search_spec = vim.host.DatastoreBrowser.SearchSpec()
            search_spec.matchPattern = ["*.vmx"]
            search_task = browser.SearchDatastoreSubFolders_Task(
                datastorePath=f"[{base_ds_name}] {new_dir}",
                searchSpec=search_spec,
            )
            _wait_task(search_task, "VMX search")
            copied_vmx = None
            for res in search_task.info.result or []:
                for f in (res.file or []):
                    copied_vmx = f"{res.folderPath}{f.path}"
                    break

            if not copied_vmx:
                print(f"  [!] Could not find copied VMX - using assumed path {new_vmx}")
                copied_vmx = new_vmx

            # ── 4. Register VM ───────────────────────────────────────────
            print(f"  [*] Registering {copied_vmx}")
            resource_pool = dc.hostFolder.childEntity[0].resourcePool
            register_task = dc.hostFolder.RegisterVM_Task(
                path=copied_vmx,
                name=vm_name,
                asTemplate=False,
                pool=resource_pool,
            )
            if not _wait_task(register_task, f"register {vm_name}"):
                results[vm_name] = "FAILED (register)"
                continue
            target_vm = register_task.info.result

            # ── 5. Answer UUID question (I copied it) ────────────────────
            print(f"  [*] Answering VM question (I copied it)")
            time.sleep(2)
            if target_vm.runtime.question:
                choices = target_vm.runtime.question.choice.choiceInfo
                # Pick the 'I copied it' choice (usually index 1)
                copy_choice = next(
                    (c for c in choices if 'copy' in c.label.lower()), choices[0])
                target_vm.AnswerVM(
                    questionId=target_vm.runtime.question.id,
                    answerChoice=copy_choice.key,
                )

            # ── 6. Update MAC address ────────────────────────────────────
            print(f"  [*] Setting MAC {mac}")
            nic = next((d for d in target_vm.config.hardware.device
                        if isinstance(d, vim.vm.device.VirtualEthernetCard)), None)
            if nic:
                nic.addressType = 'manual'
                nic.macAddress  = mac
                spec = vim.vm.ConfigSpec()
                dev_change = vim.vm.device.VirtualDeviceConfigSpec()
                dev_change.operation = vim.vm.device.VirtualDeviceConfigSpec.Operation.edit
                dev_change.device = nic
                spec.deviceChange = [dev_change]
                target_vm.ReconfigVM_Task(spec=spec)

        # ── 7. Power on ──────────────────────────────────────────────────
        if target_vm.runtime.powerState != 'poweredOn':
            print(f"  [*] Powering on {vm_name}")
            task = target_vm.PowerOn()
            _wait_task(task, f"power on {vm_name}")

        # ── 8. Wait for VMware Tools ─────────────────────────────────────
        print(f"  [*] Waiting for VMware Tools on {vm_name}...")
        deadline = time.time() + 120
        while time.time() < deadline:
            if target_vm.guest.toolsRunningStatus == 'guestToolsRunning':
                break
            time.sleep(5)
        else:
            print(f"  [!] VMware Tools not ready after 120s - skipping guest ops")
            results[vm_name] = "PARTIAL (no tools)"
            continue
        print(f"  [+] VMware Tools running - guest IP: {target_vm.guest.ipAddress}")

        # ── 9. Set static IP via nmcli ───────────────────────────────────
        print(f"  [*] Configuring static IP {new_ip}/24 via nmcli")
        # Find the connection name used by this VM's NIC
        ip_cmd = (
            f"CON=$(nmcli -t -f NAME,DEVICE con show --active | head -1 | cut -d: -f1); "
            f"nmcli con mod \"$CON\" ipv4.method manual ipv4.addresses {new_ip}/24 "
            f"ipv4.gateway 192.168.1.4 ipv4.dns 8.8.8.8 && "
            f"nmcli con down \"$CON\" && nmcli con up \"$CON\" && "
            f"echo IP_SET_OK"
        )
        out = guest_exec(si, target_vm, plc_user, plc_pass, ip_cmd, timeout=30)
        if 'IP_SET_OK' in out:
            print(f"  [+] Static IP set: {new_ip}")
        else:
            print(f"  [!] IP config output: {out[:200]}")

        # ── 10. Git pull latest code ──────────────────────────────────────
        print(f"  [*] Git pull on {vm_name}")
        repo = REPO_PATH_LINUX.format(user=plc_user)
        pull_cmd = (
            f"export GIT_SSH_COMMAND='ssh -o StrictHostKeyChecking=no' && "
            f"cd {repo} && git pull && git log --oneline -1"
        )
        out = guest_exec(si, target_vm, plc_user, plc_pass, pull_cmd, timeout=60)
        print(f"  [+] {out.strip().split(chr(10))[-1]}")

        # ── 11. Run setup_vm.sh ───────────────────────────────────────────
        print(f"  [*] Running setup_vm.sh {proc}")
        setup_cmd = (
            f"cd {repo} && "
            f"echo {plc_pass} | sudo -S bash {ICS_DIR}/deploy/setup_vm.sh {proc}"
        )
        out = guest_exec(si, target_vm, plc_user, plc_pass, setup_cmd, timeout=120)
        if 'DEPLOYMENT COMPLETE' in out:
            print(f"  [+] Service deployed successfully")
            results[vm_name] = f"OK  ip={new_ip}"
        else:
            last_lines = '\n'.join(out.strip().split('\n')[-5:])
            print(f"  [!] Setup output tail:\n{last_lines}")
            results[vm_name] = f"PARTIAL (setup uncertain)"

    Disconnect(si)

    print(f"\n{'='*60}")
    print(f"  CLONE SUMMARY")
    print(f"{'='*60}")
    for name, status in sorted(results.items()):
        print(f"  {name:<35} {status}")


def cmd_provision_new_plcs():
    """Provision already-existing new PLC VMs: set IP + deploy service (no clone step)."""
    si = connect_esxi()
    vms = get_vms(si)
    plc_user, plc_pass = plc_creds()
    results = {}

    for vm_name, cfg in NEW_PLCS.items():
        proc   = cfg["process"]
        new_ip = cfg["ip"]
        vm = vms.get(vm_name)
        if not vm:
            results[vm_name] = "NOT FOUND"
            continue
        if vm.guest.toolsRunningStatus != 'guestToolsRunning':
            results[vm_name] = f"TOOLS NOT RUNNING (state={vm.runtime.powerState})"
            continue

        repo = REPO_PATH_LINUX.format(user=plc_user)
        cmd = (
            f"export GIT_SSH_COMMAND='ssh -o StrictHostKeyChecking=no' && "
            f"cd {repo} && git pull && "
            f"echo {plc_pass} | sudo -S bash {ICS_DIR}/deploy/setup_vm.sh {proc}"
        )
        out = guest_exec(si, vm, plc_user, plc_pass, cmd, timeout=120)
        results[vm_name] = "OK" if 'DEPLOYMENT COMPLETE' in out else "CHECK OUTPUT"
        print(f"  {vm_name}: {results[vm_name]}")

    Disconnect(si)


def cmd_verify_new_plcs():
    """Verify the 4 new PLCs are reachable and services running."""
    import socket as _socket
    si = connect_esxi()
    vms = get_vms(si)
    plc_user, plc_pass = plc_creds()

    # Protocol ports to check per process
    proto_ports = {
        "heating_district":   [("tcp", 502)],
        "water_utility_dnp3": [("tcp", 20000)],
        "sensor_network":     [("tcp", 5000)],
        "safety_system":      [("udp", 1502), ("tcp", 2404)],
    }

    print(f"\n{'VM':<35} {'IP':<16} {'Tools':<10} {'Ports'}")
    print("-" * 80)

    for vm_name, cfg in NEW_PLCS.items():
        proc   = cfg["process"]
        new_ip = cfg["ip"]
        vm = vms.get(vm_name)
        if not vm:
            print(f"  {vm_name:<33} NOT FOUND IN ESXI")
            continue

        tools = vm.guest.toolsRunningStatus
        guest_ip = vm.guest.ipAddress or "N/A"
        port_results = []
        for proto, port in proto_ports.get(proc, []):
            try:
                if proto == "tcp":
                    s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
                    s.settimeout(2)
                    ok = s.connect_ex((new_ip, port)) == 0
                    s.close()
                else:
                    s = _socket.socket(_socket.AF_INET, _socket.SOCK_DGRAM)
                    s.settimeout(1)
                    s.sendto(b'\x00', (new_ip, port))
                    try: s.recvfrom(64)
                    except: pass
                    ok = True
                    s.close()
                port_results.append(f"{port}={'OK' if ok else 'CLOSED'}")
            except Exception as e:
                port_results.append(f"{port}=ERR({e})")
        ports_str = " ".join(port_results) or "none checked"
        print(f"  {vm_name:<33} {guest_ip:<16} {tools:<10} {ports_str}")

    Disconnect(si)


# ---------------------------------------------------------------------------

COMMANDS = {
    'status': cmd_status,
    'verify': cmd_verify,
    'pull': cmd_pull,
    'restart-plcs': cmd_restart_plcs,
    'restart-hmi': cmd_restart_hmi,
    'deploy-plcs': cmd_deploy_plcs,
    'snapshot': cmd_snapshot,
    'clone-new-plcs': cmd_clone_new_plcs,
    'provision-new-plcs': cmd_provision_new_plcs,
    'verify-new-plcs': cmd_verify_new_plcs,
}

if __name__ == '__main__':
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Usage: {sys.argv[0]} <command>")
        print(f"Commands: {', '.join(COMMANDS.keys())}")
        sys.exit(1)

    COMMANDS[sys.argv[1]]()
