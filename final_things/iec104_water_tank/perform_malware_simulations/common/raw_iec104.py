#!/usr/bin/env python3
"""
Raw IEC 60870-5-104 Protocol Implementation

This module implements raw IEC-104 ASDU frame construction and transmission.
Used to bypass c104 library limitations for malware simulations.

IEC-104 uses APCI (Application Protocol Control Information) + ASDU structure:
- APCI: 6 bytes (0x68, length, control fields)
- ASDU: Variable length (Type ID, VSQ, COT, CA, IOA, data)
"""

import socket
import struct
import time
from typing import List, Tuple
from enum import IntEnum


class TypeID(IntEnum):
    """IEC 60870-5-104 Type IDs"""
    M_SP_NA_1 = 1   # Single-point information
    M_DP_NA_1 = 3   # Double-point information
    M_ME_NB_1 = 11  # Measured value, scaled
    C_SC_NA_1 = 45  # Single command
    C_DC_NA_1 = 46  # Double command
    C_SE_NC_1 = 50  # Set point command, short floating point
    C_IC_NA_1 = 100 # Interrogation command


class COT(IntEnum):
    """Cause of Transmission"""
    ACTIVATION = 6
    ACT_CON = 7        # Activation confirmation
    DEACTIVATION = 8
    SPONTANEOUS = 3
    INTERROGATED = 5


class RawIEC104Client:
    """
    Raw IEC 60870-5-104 Client

    Implements low-level IEC-104 protocol for sending commands
    without library validation restrictions.
    """

    def __init__(self, target_ip: str, port: int = 2404):
        self.target_ip = target_ip
        self.port = port
        self.sock = None
        self.send_seq = 0
        self.recv_seq = 0

    def connect(self) -> bool:
        """Establish TCP connection and send STARTDT"""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((self.target_ip, self.port))

            # Send STARTDT (Start Data Transfer)
            # APCI: 0x68 0x04 0x07 0x00 0x00 0x00
            startdt = bytes([0x68, 0x04, 0x07, 0x00, 0x00, 0x00])
            self.sock.send(startdt)

            # Wait for STARTDT CON
            response = self.sock.recv(1024)
            if len(response) >= 6 and response[2] == 0x0B:  # STARTDT CON
                return True

            return False

        except Exception as e:
            print(f"Connection error: {e}")
            return False

    def disconnect(self):
        """Send STOPDT and close connection"""
        if self.sock:
            try:
                # Send STOPDT
                stopdt = bytes([0x68, 0x04, 0x13, 0x00, 0x00, 0x00])
                self.sock.send(stopdt)
                time.sleep(0.1)
            except:
                pass
            finally:
                self.sock.close()
                self.sock = None

    def send_single_command(self, common_address: int, ioa: int, state: bool) -> bool:
        """
        Send C_SC_NA_1 (Single Command)

        Args:
            common_address: Common Address (1-65535)
            ioa: Information Object Address (0-16777215)
            state: True = ON, False = OFF

        Returns:
            True if sent successfully
        """
        try:
            # Build ASDU
            asdu = self._build_single_command_asdu(common_address, ioa, state)

            # Build APCI + ASDU
            frame = self._build_i_frame(asdu)

            # Send
            self.sock.send(frame)

            # Increment send sequence
            self.send_seq = (self.send_seq + 1) % 32768

            return True

        except Exception as e:
            print(f"Send error: {e}")
            return False

    def send_double_command(self, common_address: int, ioa: int, state: int) -> bool:
        """
        Send C_DC_NA_1 (Double Command)

        Args:
            common_address: Common Address (1-65535)
            ioa: Information Object Address (0-16777215)
            state: 0=NOT_ALLOWED, 1=OFF, 2=ON, 3=INDETERMINATE

        Returns:
            True if sent successfully
        """
        try:
            # Build ASDU
            asdu = self._build_double_command_asdu(common_address, ioa, state)

            # Build APCI + ASDU
            frame = self._build_i_frame(asdu)

            # Send
            self.sock.send(frame)

            # Increment send sequence
            self.send_seq = (self.send_seq + 1) % 32768

            return True

        except Exception as e:
            print(f"Send error: {e}")
            return False

    def _build_i_frame(self, asdu: bytes) -> bytes:
        """Build I-Format APCI frame"""
        # APCI structure:
        # 0x68 (start)
        # length (1 byte) = len(ASDU) + 4
        # Send Seq (2 bytes, little endian) = (send_seq * 2) & 0xFFFF
        # Recv Seq (2 bytes, little endian) = (recv_seq * 2) & 0xFFFF

        length = len(asdu) + 4
        send_seq_encoded = (self.send_seq * 2) & 0xFFFF
        recv_seq_encoded = (self.recv_seq * 2) & 0xFFFF

        apci = struct.pack('<BBHH',
            0x68,                  # Start byte
            length,                # Length
            send_seq_encoded,      # Send sequence number
            recv_seq_encoded       # Receive sequence number
        )

        return apci + asdu

    def _build_single_command_asdu(self, ca: int, ioa: int, state: bool) -> bytes:
        """
        Build C_SC_NA_1 ASDU

        ASDU Structure:
        - Type ID: 1 byte (45 = C_SC_NA_1)
        - VSQ: 1 byte (Number of objects, SQ=0)
        - COT: 1 byte (6 = ACTIVATION)
        - ORG: 1 byte (Originator address, usually 0)
        - CA: 2 bytes (Common Address, little endian)
        - IOA: 3 bytes (Information Object Address, little endian)
        - SCO: 1 byte (Single Command, bit 0 = state, bits 2-7 = qualifier)
        """

        # SCO byte: bit 0 = state (1=ON, 0=OFF), bits 2-7 = 0 (no qualifier)
        sco = 0x01 if state else 0x00

        asdu = struct.pack('<BBBBH3sB',
            TypeID.C_SC_NA_1,      # Type ID
            0x01,                  # VSQ: 1 object, SQ=0
            COT.ACTIVATION,        # Cause of Transmission
            0x00,                  # Originator Address
            ca,                    # Common Address (2 bytes)
            ioa.to_bytes(3, 'little'),  # IOA (3 bytes)
            sco                    # Single Command
        )

        return asdu

    def _build_double_command_asdu(self, ca: int, ioa: int, state: int) -> bytes:
        """
        Build C_DC_NA_1 ASDU

        ASDU Structure:
        - Type ID: 1 byte (46 = C_DC_NA_1)
        - VSQ: 1 byte (Number of objects, SQ=0)
        - COT: 1 byte (6 = ACTIVATION)
        - ORG: 1 byte (Originator address, usually 0)
        - CA: 2 bytes (Common Address, little endian)
        - IOA: 3 bytes (Information Object Address, little endian)
        - DCO: 1 byte (Double Command, bits 0-1 = state, bits 2-7 = qualifier)
        """

        # DCO byte: bits 0-1 = state, bits 2-7 = 0 (no qualifier)
        # state: 0=NOT_ALLOWED, 1=OFF, 2=ON, 3=INDETERMINATE
        dco = state & 0x03

        asdu = struct.pack('<BBBBH3sB',
            TypeID.C_DC_NA_1,      # Type ID
            0x01,                  # VSQ: 1 object, SQ=0
            COT.ACTIVATION,        # Cause of Transmission
            0x00,                  # Originator Address
            ca,                    # Common Address (2 bytes)
            ioa.to_bytes(3, 'little'),  # IOA (3 bytes)
            dco                    # Double Command
        )

        return asdu


# Test function
if __name__ == '__main__':
    print("[*] Testing Raw IEC-104 Client")

    client = RawIEC104Client('127.0.0.1', 2404)

    if client.connect():
        print("[+] Connected to IEC-104 server")

        # Test single command
        print("[*] Sending C_SC_NA_1 to IOA 100...")
        client.send_single_command(common_address=1, ioa=100, state=True)
        time.sleep(0.5)

        # Test double command
        print("[*] Sending C_DC_NA_1 to IOA 1101...")
        client.send_double_command(common_address=1, ioa=1101, state=2)  # 2 = ON
        time.sleep(0.5)

        client.disconnect()
        print("[+] Disconnected")
    else:
        print("[-] Connection failed")
