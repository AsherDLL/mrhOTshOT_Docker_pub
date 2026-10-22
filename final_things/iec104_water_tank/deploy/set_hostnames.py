#!/usr/bin/env python3
"""
Set Linux hostnames on PLC VMs via pyVmomi Guest Operations.

Usage (no env vars needed - credentials are hardcoded per user request):
    python deploy/set_hostnames.py [--dry-run]

Requires: pip install pyvmomi
"""

import ssl
import sys
import time
import urllib.request
import argparse

try:
    from pyVim.connect import SmartConnect, Disconnect
    from pyVmomi import vim
except ImportError:
    print("ERROR: pyvmomi not installed.  Run: pip install pyvmomi")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ESXI_HOST = "10.3.229.3"
ESXI_USER = "user"
ESXI_PASS = "LabPass123!"

GUEST_USER = "kalilinux"
GUEST_PASS = "labpass123"

# VM name in ESXi  →  desired hostname
HOSTNAME_MAP = {
    "PLC-1-WaterTreatment":   "plc-1-water-treatment",
    "PLC-2-PowerSubstation":  "plc-2-power-substation",
    "PLC-3-GasPipeline":      "plc-3-gas-pipeline",
    "PLC-4-Manufacturing":    "plc-4-centrifuge",
    "PLC-5-BuildingHVAC":     "plc-5-building-hvac",
    "PLC-6-BoilerHouse":      "plc-6-boiler-house",
    "PLC-7-HeatingDistrict":  "plc-7-heating-district",
    "PLC-8-WaterUtilityDNP3": "plc-8-water-utility-dnp3",
    "SIS-1-SafetySystem":     "sis-1-safety-system",
}


# ---------------------------------------------------------------------------
# pyVmomi helpers
# ---------------------------------------------------------------------------

def connect_esxi():
    ctx = ssl._create_unverified_context()
    si = SmartConnect(host=ESXI_HOST, user=ESXI_USER, pwd=ESXI_PASS, sslContext=ctx)
    return si


def get_vms(si):
    content = si.RetrieveContent()
    container = content.viewManager.CreateContainerView(
        content.rootFolder, [vim.VirtualMachine], True
    )
    vms = {vm.summary.config.name: vm for vm in container.view}
    container.Destroy()
    return vms


def guest_exec(si, vm, user, pwd, cmd, timeout=30):
    """
    Run cmd inside the VM via Guest Operations.
    Stdout+stderr are captured to /tmp/_gops_out.txt and returned as a string.

    We wrap the command in a shell script file rather than fighting with
    quote escaping inside the ProgramSpec arguments string.
    """
    content = si.RetrieveContent()
    pm   = content.guestOperationsManager.processManager
    fmgr = content.guestOperationsManager.fileManager
    creds = vim.vm.guest.NamePasswordAuthentication(username=user, password=pwd)

    out_file    = "/tmp/_gops_out.txt"
    script_file = "/tmp/_gops_run.sh"
    script_body = f"#!/bin/bash\n{cmd}\n"

    # Upload the script
    attr = vim.vm.guest.FileManager.FileAttributes()
    script_bytes = script_body.encode()
    upload_url = fmgr.InitiateFileTransferToGuest(
        vm, creds, script_file, attr, len(script_bytes), True
    )
    upload_url = upload_url.replace("*", ESXI_HOST)
    req = urllib.request.Request(upload_url, data=script_bytes, method="PUT")
    req.add_header("Content-Type", "application/octet-stream")
    ctx = ssl._create_unverified_context()
    urllib.request.urlopen(req, context=ctx)

    # Execute: bash script_file > out_file 2>&1
    prog = vim.vm.guest.ProcessManager.ProgramSpec(
        programPath="/bin/bash",
        arguments=f"{script_file} > {out_file} 2>&1",
    )
    pid = pm.StartProgramInGuest(vm, creds, prog)

    # Wait for completion
    for _ in range(timeout // 2):
        time.sleep(2)
        procs = pm.ListProcessesInGuest(vm, creds, pids=[pid])
        if procs and procs[0].endTime:
            break

    # Read output
    try:
        fi = fmgr.InitiateFileTransferFromGuest(vm, creds, out_file)
        dl_url = fi.url.replace("*", ESXI_HOST)
        resp = urllib.request.urlopen(dl_url, context=ctx)
        return resp.read().decode(errors="replace").strip()
    except Exception as exc:
        return f"ERROR reading output: {exc}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Set hostnames on PLC VMs")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be done without executing")
    args = parser.parse_args()

    print(f"Connecting to ESXi {ESXI_HOST} ...")
    si = connect_esxi()
    vms = get_vms(si)
    print(f"Found {len(vms)} VMs on host.\n")

    print(f"{'VM Name':<30} {'Target Hostname':<28} {'Result'}")
    print("-" * 90)

    for vm_name, new_hostname in HOSTNAME_MAP.items():
        vm = vms.get(vm_name)

        if vm is None:
            print(f"  {vm_name:<28} {new_hostname:<28} SKIP - VM not found")
            continue

        tools_status = vm.guest.toolsRunningStatus
        if tools_status != "guestToolsRunning":
            print(f"  {vm_name:<28} {new_hostname:<28} SKIP - Tools not running ({tools_status})")
            continue

        if args.dry_run:
            print(f"  {vm_name:<28} {new_hostname:<28} DRY-RUN (would set)")
            continue

        # Step 1 - set the hostname
        set_cmd = f"echo {GUEST_PASS} | sudo -S hostnamectl set-hostname {new_hostname}"
        print(f"  {vm_name:<28} {new_hostname:<28} setting ... ", end="", flush=True)
        set_out = guest_exec(si, vm, GUEST_USER, GUEST_PASS, set_cmd, timeout=20)

        # Step 2 - verify
        verify_cmd = "hostname"
        verify_out = guest_exec(si, vm, GUEST_USER, GUEST_PASS, verify_cmd, timeout=10)

        if verify_out == new_hostname:
            print(f"OK  (hostname={verify_out})")
        else:
            print(f"MISMATCH  (got '{verify_out}') | set_cmd output: {set_out!r}")

    Disconnect(si)
    print("\nDone.")


if __name__ == "__main__":
    main()
