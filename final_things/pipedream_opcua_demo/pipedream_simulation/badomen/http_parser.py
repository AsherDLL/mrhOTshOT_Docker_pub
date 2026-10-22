#!/usr/bin/env python3
"""
Omron HTTP Interface Parser

Parses HTTP responses from Omron PLCs.
Part of BADOMEN attack module for PIPEDREAM.
"""

import logging
import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [HTTP-PARSE] - %(levelname)s - %(message)s'
)
logger = logging.getLogger('HTTPParser')


class OmronHTTPParser:
    """Parse Omron HTTP interface"""

    def __init__(self, target: str, port: int = 80):
        self.target = target
        self.port = port
        self.base_url = f"http://{target}:{port}"

    def parse_device_info(self) -> dict:
        """Parse device information from HTTP"""
        logger.info(f"[*] Parsing HTTP interface at {self.base_url}")

        try:
            response = requests.get(self.base_url, timeout=3.0)
            logger.info(f"[+] HTTP response received: {response.status_code}")

            return {
                'status_code': response.status_code,
                'server': response.headers.get('Server', 'Unknown'),
                'content_length': len(response.content)
            }

        except Exception as e:
            logger.error(f"HTTP parse error: {e}")
            return {}


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Omron HTTP Parser (BADOMEN)'
    )

    parser.add_argument('--target', '-t', required=True,
                        help='Target PLC IP')

    args = parser.parse_args()

    parser_obj = OmronHTTPParser(args.target)
    info = parser_obj.parse_device_info()

    print("\nHTTP Device Information:")
    for key, value in info.items():
        print(f"  {key}: {value}")

    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
