#!/usr/bin/env python3
"""
DeviceXPlorer .dxp Project File Parser for Cortex XSIAM

Parses TAKEBISHI DeviceXPlorer OPC Server project files and outputs
structured asset/tag inventory in formats consumable by XSIAM:
  - JSON (for XDR API / HTTP Collector)
  - CEF (for Syslog ingestion)
  - CSV (for lookup tables)

Usage:
    python dxp_parser.py final.dxp --format json
    python dxp_parser.py final.dxp --format cef
    python dxp_parser.py final.dxp --format csv
    python dxp_parser.py final.dxp --format xql    # XQL-ready dataset
    python dxp_parser.py final.dxp --format all     # all formats
"""

import xml.etree.ElementTree as ET
import json
import csv
import sys
import io
import argparse
from datetime import datetime, timezone
from typing import Dict, List, Any


# ---------------------------------------------------------------------------
# Protocol / Type Mappings
# ---------------------------------------------------------------------------

IEC104_DTYPE = {'1': 'BOOL', '2': 'SHORT', '6': 'FLOAT'}
IEC104_TYPE = {
    '2': 'M_SP_NA_1', '7': 'M_ME_NB_1', '11': 'M_ME_NB_1',
    '23': 'C_SC_NA_1', '28': 'C_SE_NC_1', '45': 'C_SC_NA_1', '50': 'C_SE_NC_1',
}
IEC104_TYPE_DESC = {
    'M_SP_NA_1': 'Single Point Information',
    'M_ME_NB_1': 'Measured Value, Scaled',
    'C_SC_NA_1': 'Single Command',
    'C_SE_NC_1': 'Setpoint Command, Short Float',
}

S7_AREA = {'0': 'M (Merker)', '1': 'I (Input)', '2': 'DB (Data Block)', '3': 'Q (Output)'}
S7_DTYPE = {'1': 'BOOL', '2': 'INT', '3': 'WORD', '4': 'DWORD', '5': 'DINT', '6': 'REAL/FLOAT'}

OPCUA_DTYPE = {'1': 'Boolean', '2': 'Int16', '6': 'Float', '10': 'Double'}

ACCESS_MAP = {'2': 'ReadOnly', '3': 'ReadWrite'}

LIB_TO_PROTOCOL = {
    'Iec104Client': 'IEC 60870-5-104',
    'Iec104Ethernet': 'IEC 60870-5-104',
    'OpcUaClient': 'OPC-UA',
    'OpcUaClientPort': 'OPC-UA',
    'SimaticEthernet': 'Siemens S7 (ISO-on-TCP)',
    'Ethernet': 'Siemens S7 (ISO-on-TCP)',
}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def parse_dxp(filepath: str) -> Dict[str, Any]:
    """Parse a DeviceXPlorer .dxp XML file into structured data."""
    tree = ET.parse(filepath)
    root = tree.getroot()

    result = {
        'meta': {
            'source_file': filepath,
            'product_version': root.get('ProductVersion', 'unknown'),
            'parsed_at': datetime.now(timezone.utc).isoformat(),
            'parser': 'mrhOTshOT dxp_parser v1.0',
        },
        'ports': [],
        'devices': [],
        'tags': [],
    }

    # Parse ports (network connections)
    for port in root.findall('.//PORT'):
        name = port.get('Name')
        lib = port.get('LibType', '')
        if name == 'SYSTEM':
            continue

        info = port.find('Info').text if port.find('Info') is not None else ''
        fields = info.split(',')

        port_data = {
            'name': name,
            'lib_type': lib,
            'protocol': LIB_TO_PROTOCOL.get(lib, lib),
        }

        if lib == 'Iec104Ethernet' and len(fields) > 5:
            port_data['target_ip'] = fields[4]
            port_data['target_port'] = int(fields[5])
            port_data['local_ip'] = fields[2]
        elif lib == 'OpcUaClientPort' and len(fields) > 1:
            port_data['endpoint_url'] = fields[1]
            # Extract IP from endpoint
            try:
                from urllib.parse import urlparse
                parsed = urlparse(fields[1])
                port_data['target_ip'] = parsed.hostname
                port_data['target_port'] = parsed.port
            except Exception:
                pass
        elif lib == 'Ethernet' and len(fields) > 5:
            port_data['target_ip'] = fields[4]
            port_data['target_port'] = int(fields[5])
            port_data['local_ip'] = fields[2]

        result['ports'].append(port_data)

    # Parse devices and tags
    for device in root.findall('.//DEVICE'):
        name = device.get('Name')
        lib = device.get('LibType', '')
        parent = device.get('ParentName', '')
        if name == 'SYSTEM':
            continue

        dev_info = device.find('Info').text if device.find('Info') is not None else ''
        dev_fields = dev_info.split(',')

        # Find matching port
        port_data = next((p for p in result['ports'] if p['name'] == parent), {})

        device_data = {
            'name': name,
            'lib_type': lib,
            'protocol': LIB_TO_PROTOCOL.get(lib, lib),
            'port_name': parent,
            'target_ip': port_data.get('target_ip', ''),
            'target_port': port_data.get('target_port', ''),
            'tag_count': len(device.findall('.//TAG')),
        }

        if lib == 'Iec104Client' and len(dev_fields) > 4:
            device_data['iec104_common_address_size'] = dev_fields[1]
            device_data['iec104_cot_size'] = dev_fields[2]
            device_data['iec104_ioa_size'] = dev_fields[3]
            device_data['iec104_common_address'] = dev_fields[4]

        result['devices'].append(device_data)

        # Parse tags
        for tag in device.findall('.//TAG'):
            tag_name = tag.get('Name')
            info = tag.find('Info').text if tag.find('Info') is not None else ''
            fields = info.split(',')

            tag_data = {
                'device': name,
                'protocol': LIB_TO_PROTOCOL.get(lib, lib),
                'target_ip': port_data.get('target_ip', ''),
                'target_port': port_data.get('target_port', ''),
                'tag_name': tag_name,
            }

            if lib == 'Iec104Client' and len(fields) > 11:
                tag_data['data_type'] = IEC104_DTYPE.get(fields[3], fields[3])
                tag_data['iec104_type_id'] = IEC104_TYPE.get(fields[4], fields[4])
                tag_data['iec104_type_desc'] = IEC104_TYPE_DESC.get(
                    tag_data['iec104_type_id'], '')
                tag_data['iec104_ioa'] = int(fields[5])
                tag_data['access'] = ACCESS_MAP.get(fields[11], fields[11])
                tag_data['address'] = f"IOA:{fields[5]}"

                # Classify tag function
                ioa = int(fields[5])
                if 100 <= ioa < 200:
                    tag_data['function'] = 'measurement'
                elif 200 <= ioa < 300:
                    tag_data['function'] = 'status'
                elif 300 <= ioa < 400:
                    tag_data['function'] = 'command'
                elif 400 <= ioa < 500:
                    tag_data['function'] = 'setpoint'

            elif lib == 'OpcUaClient' and len(fields) > 11:
                tag_data['data_type'] = OPCUA_DTYPE.get(fields[2], fields[2])
                tag_data['access'] = 'ReadWrite' if fields[3] == '1' else 'ReadOnly'
                tag_data['opcua_node_index'] = fields[11]
                tag_data['address'] = f"ns=2;idx={fields[11]}"
                tag_data['function'] = 'command' if fields[3] == '1' else 'measurement'

            elif lib == 'SimaticEthernet' and len(fields) > 11:
                tag_data['data_type'] = S7_DTYPE.get(fields[3], fields[3])
                area_code = fields[4]
                tag_data['s7_area'] = S7_AREA.get(area_code, area_code)
                if area_code == '2':  # DB
                    tag_data['s7_db'] = int(fields[5])
                    tag_data['s7_byte_offset'] = int(fields[6])
                    tag_data['s7_bit_position'] = int(fields[8]) if len(fields) > 8 else 0
                    tag_data['address'] = f"DB{fields[5]}.DBX{fields[6]}.{fields[8] if len(fields) > 8 else 0}"
                else:
                    tag_data['s7_byte_offset'] = int(fields[6]) if len(fields) > 6 else 0
                    tag_data['address'] = f"M{fields[6]}.{fields[8] if len(fields) > 8 else 0}"
                tag_data['access'] = ACCESS_MAP.get(fields[11], fields[11])
                tag_data['function'] = 'command' if tag_data['access'] == 'ReadWrite' else 'measurement'

            result['tags'].append(tag_data)

    return result


# ---------------------------------------------------------------------------
# Output Formatters
# ---------------------------------------------------------------------------

def to_json(data: Dict, pretty=True) -> str:
    """Output as JSON for XSIAM HTTP Collector / XDR API."""
    # Format as XSIAM-friendly events
    events = []

    # Asset events (devices)
    for dev in data['devices']:
        event = {
            '_time': data['meta']['parsed_at'],
            'event_type': 'ics_asset_discovered',
            'source': 'devicexplorer_dxp',
            'vendor': 'TAKEBISHI',
            'product': 'DeviceXPlorer OPC Server',
            'product_version': data['meta']['product_version'],
            **dev,
        }
        events.append(event)

    # Tag events
    for tag in data['tags']:
        event = {
            '_time': data['meta']['parsed_at'],
            'event_type': 'ics_tag_configured',
            'source': 'devicexplorer_dxp',
            **tag,
        }
        events.append(event)

    return json.dumps(events, indent=2 if pretty else None)


def to_cef(data: Dict) -> str:
    """Output as CEF syslog messages for XSIAM Syslog Collector."""
    lines = []
    ts = datetime.now(timezone.utc).strftime('%b %d %Y %H:%M:%S')

    # Device discovery events
    for dev in data['devices']:
        ext = (
            f"dvc={dev.get('target_ip', '')} "
            f"dpt={dev.get('target_port', '')} "
            f"cs1={dev['name']} cs1Label=DeviceName "
            f"cs2={dev['protocol']} cs2Label=Protocol "
            f"cs3={dev.get('tag_count', 0)} cs3Label=TagCount "
            f"msg=ICS PLC device discovered via OPC configuration"
        )
        line = (
            f"CEF:0|TAKEBISHI|DeviceXPlorer|6.6|ics-asset-discovered|"
            f"ICS Asset Discovered|5|{ext}"
        )
        lines.append(line)

    # Tag configuration events
    for tag in data['tags']:
        ext = (
            f"dvc={tag.get('target_ip', '')} "
            f"dpt={tag.get('target_port', '')} "
            f"cs1={tag['device']} cs1Label=DeviceName "
            f"cs2={tag['tag_name']} cs2Label=TagName "
            f"cs3={tag.get('protocol', '')} cs3Label=Protocol "
            f"cs4={tag.get('data_type', '')} cs4Label=DataType "
            f"cs5={tag.get('address', '')} cs5Label=Address "
            f"cs6={tag.get('access', '')} cs6Label=Access "
            f"cs7={tag.get('function', '')} cs7Label=Function "
            f"msg=ICS tag configured: {tag['tag_name']} on {tag['device']}"
        )
        severity = '3' if tag.get('access') == 'ReadOnly' else '6'
        line = (
            f"CEF:0|TAKEBISHI|DeviceXPlorer|6.6|ics-tag-configured|"
            f"ICS Tag Configured|{severity}|{ext}"
        )
        lines.append(line)

    return '\n'.join(lines)


def to_csv(data: Dict) -> str:
    """Output as CSV for XSIAM lookup tables."""
    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow([
        'device', 'protocol', 'target_ip', 'target_port',
        'tag_name', 'data_type', 'address', 'access', 'function',
        'iec104_ioa', 'iec104_type_id', 's7_db', 'opcua_node_index'
    ])

    for tag in data['tags']:
        writer.writerow([
            tag.get('device', ''),
            tag.get('protocol', ''),
            tag.get('target_ip', ''),
            tag.get('target_port', ''),
            tag.get('tag_name', ''),
            tag.get('data_type', ''),
            tag.get('address', ''),
            tag.get('access', ''),
            tag.get('function', ''),
            tag.get('iec104_ioa', ''),
            tag.get('iec104_type_id', ''),
            tag.get('s7_db', ''),
            tag.get('opcua_node_index', ''),
        ])

    return output.getvalue()


def to_xql(data: Dict) -> str:
    """Output XQL dataset creation query for XSIAM."""
    lines = []
    lines.append("// XQL: ICS Asset & Tag Inventory from DeviceXPlorer DXP")
    lines.append("// Paste into XSIAM XQL query or use as dataset\n")

    lines.append("dataset = ics_plc_inventory")
    lines.append("| fields device, protocol, target_ip, target_port, tag_name, data_type, address, access, function\n")

    lines.append("// --- Static Dataset (paste into Custom Table / Lookup) ---")
    lines.append("// device | protocol | target_ip | target_port | tag_name | data_type | address | access | function")

    for tag in data['tags']:
        lines.append(
            f"// {tag.get('device','')} | {tag.get('protocol','')} | "
            f"{tag.get('target_ip','')} | {tag.get('target_port','')} | "
            f"{tag.get('tag_name','')} | {tag.get('data_type','')} | "
            f"{tag.get('address','')} | {tag.get('access','')} | "
            f"{tag.get('function','')}"
        )

    lines.append("")
    lines.append("// --- Detection Rules ---")
    lines.append("")
    lines.append("// Detect writes to ReadOnly tags (potential attack)")
    lines.append("dataset = xdr_data")
    lines.append("| filter event_type = 'ics_tag_write'")
    lines.append("| join type=inner (")
    lines.append("    dataset = ics_plc_inventory | filter access = 'ReadOnly'")
    lines.append(") as inv on tag_name = inv.tag_name and target_ip = inv.target_ip")
    lines.append("| fields _time, target_ip, tag_name, inv.protocol, inv.address")
    lines.append("")
    lines.append("// Detect command injection (writes to command/setpoint tags)")
    lines.append("dataset = xdr_data")
    lines.append("| filter event_type = 'ics_tag_write'")
    lines.append("| join type=inner (")
    lines.append("    dataset = ics_plc_inventory | filter function in ('command', 'setpoint')")
    lines.append(") as inv on tag_name = inv.tag_name")
    lines.append("| fields _time, source_ip, target_ip, tag_name, inv.protocol, inv.function, new_value")

    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='Parse DeviceXPlorer .dxp files for Cortex XSIAM ingestion',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python dxp_parser.py final.dxp --format json > tags.json
  python dxp_parser.py final.dxp --format cef | logger -p local0.info
  python dxp_parser.py final.dxp --format csv > lookup_table.csv
  python dxp_parser.py final.dxp --format xql > detection_rules.xql
  python dxp_parser.py final.dxp --format all
        """
    )
    parser.add_argument('dxp_file', help='Path to .dxp project file')
    parser.add_argument('--format', '-f', choices=['json', 'cef', 'csv', 'xql', 'all'],
                        default='json', help='Output format (default: json)')
    parser.add_argument('--output', '-o', help='Output file (default: stdout)')
    parser.add_argument('--summary', '-s', action='store_true', help='Print summary to stderr')

    args = parser.parse_args()

    data = parse_dxp(args.dxp_file)

    if args.summary:
        print(f"\nParsed: {args.dxp_file}", file=sys.stderr)
        print(f"  Ports: {len(data['ports'])}", file=sys.stderr)
        print(f"  Devices: {len(data['devices'])}", file=sys.stderr)
        print(f"  Tags: {len(data['tags'])}", file=sys.stderr)
        for dev in data['devices']:
            print(f"    {dev['name']}: {dev['protocol']} → {dev.get('target_ip','')}:{dev.get('target_port','')}", file=sys.stderr)

    if args.format == 'all':
        for fmt in ['json', 'cef', 'csv', 'xql']:
            formatter = {'json': to_json, 'cef': to_cef, 'csv': to_csv, 'xql': to_xql}[fmt]
            ext = fmt
            outfile = f"{args.dxp_file.rsplit('.', 1)[0]}_{fmt}.{ext}"
            with open(outfile, 'w') as f:
                f.write(formatter(data))
            print(f"  Written: {outfile}", file=sys.stderr)
    else:
        formatter = {'json': to_json, 'cef': to_cef, 'csv': to_csv, 'xql': to_xql}[args.format]
        output = formatter(data)

        if args.output:
            with open(args.output, 'w') as f:
                f.write(output)
        else:
            print(output)


if __name__ == '__main__':
    main()
