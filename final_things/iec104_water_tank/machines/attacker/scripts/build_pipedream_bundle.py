#!/usr/bin/env python3
"""
Build PIPEDREAM bundle ZIP for delivery to HMI engineering workstation.

Assembles:
  pipedream_bundle/
    pipedream_launcher.py        -- master orchestrator (all 7 attack steps)
    AsrDrv103.sys                -- LAZYCARGO kernel driver (legitimately signed)
    pipedream_simulation/        -- all Python attack modules
      evilscholar/               -- Schneider MODICON + Modbus
      badomen/                   -- OMRON FINS
      mousehole/                 -- OPC-UA recon
      opcua_attack.py            -- base class
      attack_gas_pipeline.py     -- OT write payload
      fins_scanner.py
      modbus_scanner.py
      __init__.py

Usage:
    python3 build_pipedream_bundle.py [--output /tmp/pipedream_bundle.zip]
"""

import os
import sys
import shutil
import zipfile
import argparse
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BASE       = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..', '..', '..', 'pipedream_opcua_demo'))
LAUNCHER   = os.path.join(SCRIPT_DIR, '..', 'payloads', 'pipedream_launcher.py')
LAUNCHER   = os.path.abspath(LAUNCHER)


def build_bundle(output_zip: str = '/tmp/pipedream_bundle.zip') -> str:
    """
    Assemble pipedream_bundle.zip from existing repo files.
    Returns the path to the created ZIP.
    """
    sim_src      = os.path.join(BASE, 'pipedream_simulation')
    asrdrv_src   = os.path.join(BASE, 'artifacts', 'AsrDrv103.sys')

    if not os.path.isdir(sim_src):
        print(f"  [-] pipedream_simulation/ not found at {sim_src}")
        sys.exit(1)
    if not os.path.exists(asrdrv_src):
        print(f"  [!] AsrDrv103.sys not found at {asrdrv_src} - using stub")
        asrdrv_src = None
    if not os.path.exists(LAUNCHER):
        print(f"  [-] pipedream_launcher.py not found at {LAUNCHER}")
        sys.exit(1)

    with tempfile.TemporaryDirectory() as tmp:
        bundle_dir = os.path.join(tmp, 'pipedream_bundle')
        os.makedirs(bundle_dir)

        # Copy pipedream_simulation/ (the attack modules)
        sim_dst = os.path.join(bundle_dir, 'pipedream_simulation')
        shutil.copytree(sim_src, sim_dst,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc',
                                                       'build', 'dist', '*.spec',
                                                       'venv', '.git'))
        print(f"  [+] pipedream_simulation/ → bundle")

        # Copy AsrDrv103.sys (LAZYCARGO)
        if asrdrv_src:
            shutil.copy(asrdrv_src, os.path.join(bundle_dir, 'AsrDrv103.sys'))
            size = os.path.getsize(asrdrv_src)
            print(f"  [+] AsrDrv103.sys ({size:,} bytes) → bundle")
        else:
            # Stub PE so the file write still generates forensic artifacts
            stub = b'MZ' + b'\x90' * 62 + b'PE\x00\x00' + b'\x64\x86' + b'\x00' * 200
            with open(os.path.join(bundle_dir, 'AsrDrv103.sys'), 'wb') as f:
                f.write(stub)
            print(f"  [!] AsrDrv103.sys stub ({len(stub)} bytes) → bundle")

        # Copy launcher
        shutil.copy(LAUNCHER, os.path.join(bundle_dir, 'pipedream_launcher.py'))
        print(f"  [+] pipedream_launcher.py → bundle")

        # Create ZIP
        if output_zip.endswith('.zip'):
            output_zip = output_zip[:-4]   # make_archive adds .zip
        zip_path = shutil.make_archive(output_zip, 'zip', tmp, 'pipedream_bundle')
        size = os.path.getsize(zip_path)
        print(f"  [+] Bundle: {zip_path} ({size:,} bytes)")
        return zip_path


def main():
    parser = argparse.ArgumentParser(description='Build PIPEDREAM delivery bundle')
    parser.add_argument('--output', default='/tmp/pipedream_bundle.zip',
                        help='Output ZIP path (default: /tmp/pipedream_bundle.zip)')
    args = parser.parse_args()

    print("Building PIPEDREAM bundle...")
    path = build_bundle(args.output)
    print(f"Done: {path}")


if __name__ == '__main__':
    main()
