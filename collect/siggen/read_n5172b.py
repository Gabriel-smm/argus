#!/usr/bin/env python3
"""Read the current configuration of a Keysight N5172B EXG over Ethernet.

Python 3.8+; no third-party packages or VISA installation required.
Run on a computer that can reach the instrument's LAN address:

    python read_n5172b.py
    python read_n5172b.py --ip 10.173.170.235 --json n5172b_status.json
    python read_n5172b.py --basic

Only documented configuration/status/catalog queries are sent. No reset,
preset, configuration change, trigger, error-queue read, or clear-on-read
event query is issued. The snapshot is sequential, not atomic. It reports
settings and status, not measured RF power or verified waveform content.

Reference: Keysight N5180-90057, May 2024, N5172B SCPI Command Reference:
https://www.keysight.com/pa/en/assets/9018-03690/programming-guides/9018-03690.pdf
"""

import argparse
import csv
import json
import math
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


# (Label, query, display format). Raw replies are also retained in JSON.
CORE = [
    ("Instrument identity", "*IDN?", "text"),
    ("Installed options", "*OPT?", "text"),
    ("RF output enabled", ":OUTP:STAT?", "bool"),
    ("Global modulation enabled", ":OUTP:MOD:STAT?", "bool"),
    ("CW frequency setting", ":SOUR:FREQ:CW?", "hz"),
    ("Frequency mode", ":SOUR:FREQ:MODE?", "text"),
    ("Frequency display multiplier", ":SOUR:FREQ:MULT?", "number"),
    ("Frequency display offset", ":SOUR:FREQ:OFFS?", "hz"),
    ("Power units", ":UNIT:POW?", "text"),
    ("Power setting (in units above)", ":SOUR:POW:LEV:IMM:AMPL?", "number"),
    ("Power display offset (dB)", ":SOUR:POW:LEV:IMM:OFFS?", "number"),
    ("Power mode", ":SOUR:POW:MODE?", "text"),
    ("Automatic leveling control", ":SOUR:POW:ALC:STAT?", "bool"),
    ("Reference oscillator source", ":SOUR:ROSC:SOUR?", "text"),
    ("Automatic reference selection", ":SOUR:ROSC:SOUR:AUTO?", "bool"),
    ("External reference frequency setting", ":SOUR:ROSC:FREQ:EXT?", "hz"),
]

VECTOR = [
    ("I/Q modulation enabled", ":SOUR:DM:STAT?", "bool"),
    ("I/Q source", ":SOUR:DM:SOUR?", "text"),
    ("Dual ARB enabled", ":SOUR:RAD:ARB:STAT?", "bool"),
    ("Selected ARB waveform/sequence", ":SOUR:RAD:ARB:WAV?", "text"),
    ("ARB clock rate setting", ":SOUR:RAD:ARB:SCL:RATE?", "hz"),
    ("ARB trigger type", ":SOUR:RAD:ARB:TRIG:TYPE?", "text"),
    ("ARB trigger source", ":SOUR:RAD:ARB:TRIG:SOUR?", "text"),
    ("ARB continuous-mode behavior", ":SOUR:RAD:ARB:TRIG:TYPE:CONT:TYPE?", "text"),
    ("ARB status register", ":SOUR:RAD:ARB:REG:STAT?", "arb_status"),
]

CATALOGS = [
    ("Waveforms loaded in RAM", ':MMEM:CAT? "WFM1:"', "catalog"),
    ("Waveforms saved in nonvolatile memory", ':MMEM:CAT? "NVWFM:"', "catalog"),
    ("Saved waveform sequences", ':MMEM:CAT? "SEQ:"', "catalog"),
]


class SCPIConnection:
    """One query and complete newline-terminated response at a time."""

    def __init__(self, host, port=5025, timeout=5.0):
        self.timeout = timeout
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.buffer = bytearray()

    def close(self):
        self.sock.close()

    def query(self, command):
        header = command.split()[0] if command.strip() else ""
        if (not header.endswith("?") or command.count("?") != 1
                or any(c in command for c in ";\r\n")):
            raise ValueError("Only a single SCPI query is allowed")
        deadline = time.monotonic() + self.timeout
        self.sock.settimeout(self.timeout)
        self.sock.sendall((command + "\n").encode("ascii"))
        while b"\n" not in self.buffer:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("No complete response to " + command)
            self.sock.settimeout(remaining)
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("Instrument closed the connection during " + command)
            self.buffer.extend(chunk)
            if len(self.buffer) > 8 * 1024 * 1024:
                raise ValueError("Instrument response exceeded 8 MiB")
        line, _, rest = self.buffer.partition(b"\n")
        self.buffer = bytearray(rest)
        return line.rstrip(b"\r").decode("ascii", errors="replace").strip()


def format_reply(raw, kind):
    if kind == "bool":
        return {"0": "OFF", "1": "ON", "OFF": "OFF", "ON": "ON"}.get(raw.upper(), raw)
    if kind == "catalog":
        fields = next(csv.reader([raw]))
        if len(fields) < 2:
            return raw
        lines = ["used={} bytes; free={} bytes".format(*fields[:2])]
        lines.extend("  " + item for item in fields[2:] if item)
        if not any(fields[2:]):
            lines.append("  (empty)")
        return "\n".join(lines)
    try:
        value = float(raw)
        if kind == "hz":
            return "{:,.15g} Hz ({:.12g} MHz)".format(value, value / 1e6)
        if kind == "number":
            return "{:.12g}".format(value)
        if kind == "arb_status":
            bits = int(value)
            return "{} [enabled={}, armed={}, RUN={}]".format(
                bits, bool(bits & 1), bool(bits & 2), bool(bits & 4))
    except (ValueError, OverflowError):
        pass
    return raw or "(empty reply)"


def option_queries(options_reply):
    """Avoid probing feature commands when their option is not reported."""
    options = {s.strip().strip('"').upper() for s in options_reply.split(",")}

    def installed(code):
        return code in options or "N5180" + code + "B" in options

    queries = []
    if installed("UNT"):
        for family in ("AM", "FM", "PM"):
            for channel in (1, 2):
                name = "{}{}".format(family, channel)
                queries.append((name + " enabled", ":SOUR:" + name + ":STAT?", "bool"))
    if installed("UNW"):
        queries.append(("Pulse modulation enabled", ":SOUR:PULM:STAT?", "bool"))
    if installed("431"):
        queries.append(("Custom digital modulation enabled", ":SOUR:RAD:DMOD:ARB:STAT?", "bool"))
    if installed("430"):
        queries.append(("Multitone modulation enabled", ":SOUR:RAD:MTON:ARB:STAT?", "bool"))
    if installed("403"):
        queries.append(("Dual ARB added noise enabled", ":SOUR:RAD:ARB:NOIS:STAT?", "bool"))
    return queries


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ip", default="10.173.170.235", help="Instrument address (default: address in your photo)")
    parser.add_argument("--port", type=int, default=5025, help="SCPI socket port (default: 5025)")
    parser.add_argument("--timeout", type=float, default=5.0, help="Seconds per query (default: 5)")
    parser.add_argument("--json", type=Path, metavar="FILE", help="Also save raw replies and completion status to JSON")
    parser.add_argument("--basic", action="store_true", help="Read only basic RF/power/reference settings")
    parser.add_argument("--no-catalogs", action="store_true", help="Skip the waveform/sequence file listings")
    args = parser.parse_args()
    if not (math.isfinite(args.timeout) and args.timeout > 0 and 1 <= args.port <= 65535):
        parser.error("timeout must be finite and positive, and port must be 1..65535")

    snapshot = {"address": args.ip, "port": args.port,
                "started_utc": datetime.now(timezone.utc).isoformat(),
                "scope": "basic" if args.basic else "standard",
                "complete": False, "readings": [], "error": None}
    client = None
    current_command = None
    raw_by_command = {}
    exit_code = 0

    def read_group(title, queries):
        nonlocal current_command
        print("\n" + title, flush=True)
        for label, command, kind in queries:
            current_command = command
            raw = client.query(command)
            raw_by_command[command] = raw
            snapshot["readings"].append({"label": label, "query": command, "raw": raw})
            print("  {:<41} {}".format(label + ":", format_reply(raw, kind)), flush=True)
            if command == "*IDN?":
                fields = [x.strip().upper() for x in raw.split(",")]
                if len(fields) < 2 or fields[1] != "N5172B":
                    raise ValueError("Expected model N5172B; stopping after identity query")

    try:
        print("Connecting to {}:{} ...".format(args.ip, args.port), flush=True)
        client = SCPIConnection(args.ip, args.port, args.timeout)
        read_group("Instrument / RF / reference settings", CORE)
        if not args.basic:
            read_group("I/Q and Dual ARB settings", VECTOR)
            read_group("Installed modulation features", option_queries(raw_by_command["*OPT?"]))
            print("  Feature queries are limited to options reported by *OPT?.")
            if not args.no_catalogs:
                read_group("Waveform inventory (files listed here need not be playing)", CATALOGS)
        snapshot["complete"] = True
        print("\nFinished. No configuration commands were sent.")
        if not args.basic:
            print("ARB RUN is a status bit; in GATE mode it stays high even when gated off.")
            print("ARB clock rate is a symbol rate when the real-time modulation filter is active.")
    except (OSError, ValueError, csv.Error) as exc:
        exit_code = 1
        snapshot["error"] = {"query": current_command, "message": str(exc)}
        print("\nStopped: {}".format(exc), file=sys.stderr)
        if current_command:
            print("Query: " + current_command, file=sys.stderr)
        print("Earlier replies remain valid. No later queries were sent after the failure.", file=sys.stderr)
        print("Check LAN access and SCPI port 5025. Try --basic or --timeout 15.", file=sys.stderr)
    finally:
        if client is not None:
            client.close()
        snapshot["finished_utc"] = datetime.now(timezone.utc).isoformat()
        if args.json:
            try:
                args.json.write_text(json.dumps(snapshot, indent=2) + "\n", encoding="utf-8")
                print("\nSaved report: " + str(args.json))
            except OSError as exc:
                print("Could not save report: " + str(exc), file=sys.stderr)
                exit_code = 1
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
