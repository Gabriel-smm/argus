"""LAN control for a Keysight/Agilent N5172B (Python sockets; no VISA).

The existing read_n5172b.py remains query-only. This module intentionally sends
configuration commands and reads/consumes SYST:ERR? after user actions; existing
errors are reported, never cleared with *CLS. Connecting only reads settings.

Reference: Keysight N5180-90057, May 2024, especially pp. 68-69, 183, 343-389:
https://www.keysight.com/pa/en/assets/9018-03690/programming-guides/9018-03690.pdf
Sample clock limits (653=75 MSa/s; 655=150 MSa/s), 60-point minimum:
https://www.keysight.com/it/en/assets/7018-03381/data-sheets/5991-0039.pdf
IQ format: signed 16-bit I,Q in big-endian order, definite-length SCPI block:
https://www.keysight.com/tm/en/assets/9018-05434/programming-guides/9018-05434.pdf

The app uses Dual ARB for every waveform, including sine-tone FM; analog FM
option UNT is not required. Uploads use volatile WFM1 RAM. Each new upload
reclaims this session's previous upload while RF and ARB are off. Only exact
file names created by this controller are deleted; existing files are preserved.
The GUI calls cleanup_waveforms before normal disconnect/exit. The lower-level
close method only closes the socket, without changing the instrument.

This is a sequential configuration/readback interface, not a calibrated RF
measurement. A network failure makes RF state unknown; use front-panel RF Off.
"""

import csv
import math
import re
import uuid

if __package__:
    from .read_n5172b import SCPIConnection
else:
    from read_n5172b import SCPIConnection


class InstrumentError(RuntimeError):
    """Instrument rejected an action, or its readback did not match."""


class SCPITransport(SCPIConnection):
    """The query-only reader plus single-command and definite-block writes."""

    def write(self, command):
        if not command.strip() or any(c in command for c in "?;\r\n"):
            raise ValueError("Expected one SCPI configuration command")
        self.sock.settimeout(self.timeout)
        self.sock.sendall((command + "\n").encode("ascii"))

    def write_binary(self, prefix, payload):
        if not re.fullmatch(r':MMEM:DATA "WFM1:PYGUI_[A-F0-9_]+",', prefix):
            raise ValueError("Binary writes require an app-owned WFM1 name")
        if not isinstance(payload, bytes) or not payload:
            raise ValueError("Expected nonempty IQ bytes")
        count = str(len(payload)).encode("ascii")
        header = b"#" + str(len(count)).encode("ascii") + count
        self.sock.settimeout(self.timeout)
        self.sock.sendall(prefix.encode("ascii") + header + payload + b"\n")


def _number(value, name, minimum, maximum):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(name + " must be a number") from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise ValueError("{} must be between {:g} and {:g}".format(name, minimum, maximum))
    return result


def _boolean(raw):
    value = raw.strip().upper()
    if value not in ("0", "1", "OFF", "ON"):
        raise InstrumentError("Invalid boolean instrument reply: " + repr(raw))
    return value in ("1", "ON")


def _power_dbm(raw, unit):
    """Convert amplitude readback using the generator's 50-ohm convention."""
    value = float(raw)
    if unit == "DBM":
        return value
    if unit == "DBUV":
        return value - 10 * math.log10(50) - 90
    if unit == "DBMV":
        return value - 10 * math.log10(50) - 30
    if unit == "W" and value > 0:
        return 10 * math.log10(value * 1000)
    if unit == "V" and value > 0:
        return 10 * math.log10(value * value / 50 * 1000)
    raise InstrumentError("Cannot display power in dBm from unit {!r}; use absolute power units".format(unit))


class N5172BController:
    """Single-worker controller. Call all methods from one serialized worker.

    Snapshots contain identity(str), options(list[str]), rf_on, modulation_on,
    frequency_hz, power_dbm, arb_on, iq_on, waveform(str), sample_rate_hz, baseband_offset_hz,
    arb_filter_on, iq_source, frequency_mode, power_mode, power_unit, and
    session_waveform(bool). Readback is settings, not measured RF output.
    """

    def __init__(self, host="10.173.170.235", port=5025, timeout=5.0, demo=False):
        if not isinstance(host, str) or not host.strip():
            raise ValueError("Instrument address is required")
        if isinstance(port, bool) or int(port) != port or not 1 <= port <= 65535:
            raise ValueError("SCPI port must be an integer from 1 to 65535")
        self.host = host.strip()
        self.port = int(port)
        self.timeout = _number(timeout, "Timeout (seconds)", .1, 120)
        self.demo = bool(demo)
        self._transport = None
        self._demo_connected = False
        self._demo_state = None
        self.identity = ""
        self.options = []
        self._session_prefix = "PYGUI_" + uuid.uuid4().hex[:12].upper()
        self._waveform_number = 0
        self._active_waveform = None
        self._active_bandwidth_hz = None
        self._owned_waveforms = set()

    @property
    def connected(self):
        return self._demo_connected if self.demo else self._transport is not None

    def _installed(self, code):
        return code in self.options or "N5180" + code + "B" in self.options

    def connect(self):
        if self.connected:
            return self.read_status()
        if self.demo:
            self.identity = "DEMO, N5172B, SIMULATED, 1.0"
            self.options = ["021", "099", "1EA", "403", "431", "506", "653", "UNV"]
            if self._demo_state is None:
                self._demo_state = dict(
                    identity=self.identity, options=self.options[:], rf_on=False,
                    modulation_on=False, frequency_hz=2.925e9, power_dbm=-55.0,
                    arb_on=False, iq_on=False, waveform="", sample_rate_hz=75e6,
                    arb_filter_on=False, iq_source="INT", frequency_mode="CW",
                    power_mode="FIX", power_unit="DBM", session_waveform=False, baseband_offset_hz=0.0,
                )
            self._demo_connected = True
            return self.read_status()
        try:
            self._transport = SCPITransport(self.host, self.port, self.timeout)
            self.identity = self._transport.query("*IDN?")
            fields = [item.strip().upper() for item in self.identity.split(",")]
            if len(fields) < 2 or fields[1] != "N5172B":
                raise InstrumentError("Expected model N5172B; received " + repr(self.identity))
            self.options = sorted({item.strip().strip('"').upper()
                                   for item in self._transport.query("*OPT?").split(",") if item.strip()})
            return self.read_status()
        except Exception:
            self.close()
            raise

    def close(self):
        """Disconnect only; RF is left in its current state."""
        transport, self._transport = self._transport, None
        self._demo_connected = False
        if transport is not None:
            transport.close()

    def _require_connection(self):
        if not self.connected:
            raise ConnectionError("Connect to the N5172B first")

    def read_status(self):
        self._require_connection()
        if self.demo:
            return dict(self._demo_state, options=self.options[:])
        q = self._transport.query
        try:
            unit = q(":UNIT:POW?").strip().upper()
            waveform = q(":SOUR:RAD:ARB:WAV?").strip().strip('"')
            result = dict(
                identity=self.identity, options=self.options[:],
                rf_on=_boolean(q(":OUTP:STAT?")),
                modulation_on=_boolean(q(":OUTP:MOD:STAT?")),
                frequency_hz=float(q(":SOUR:FREQ:CW?")),
                power_dbm=_power_dbm(q(":SOUR:POW:LEV:IMM:AMPL?"), unit),
                arb_on=_boolean(q(":SOUR:RAD:ARB:STAT?")),
                iq_on=_boolean(q(":SOUR:DM:STAT?")), waveform=waveform,
                sample_rate_hz=float(q(":SOUR:RAD:ARB:SCL:RATE?")),
                baseband_offset_hz=float(q(":SOUR:RAD:ARB:BAS:FREQ:OFFS?")),
                arb_filter_on=_boolean(q(":SOUR:RAD:ARB:FILT:STAT?")),
                iq_source=q(":SOUR:DM:SOUR?").strip().upper(),
                frequency_mode=q(":SOUR:FREQ:MODE?").strip().upper(),
                power_mode=q(":SOUR:POW:MODE?").strip().upper(),
                power_unit=unit,
                session_waveform=waveform == self._active_waveform,
            )
            for key in ("frequency_hz", "power_dbm", "sample_rate_hz", "baseband_offset_hz"):
                if not math.isfinite(result[key]):
                    raise InstrumentError("Nonfinite readback for " + key)
            return result
        except (OSError, ValueError, InstrumentError):
            self.close()
            raise

    def _check_errors(self, stage):
        errors = []
        for _ in range(32):
            reply = self._transport.query(":SYST:ERR?")
            try:
                code = int(reply.split(",", 1)[0])
            except ValueError as exc:
                raise InstrumentError("Invalid error queue reply: " + repr(reply)) from exc
            if code == 0:
                if errors:
                    raise InstrumentError(stage + ": " + " | ".join(errors))
                return
            errors.append(reply)
        raise InstrumentError(stage + ": " + " | ".join(errors) + " (queue still nonempty)")

    def _write_checked(self, command):
        """Attribute device errors to this command and stop before the next one.

        The error queue is checked before a control action starts, so errors
        read here belong to this write rather than an earlier operation.
        """
        self._transport.write(command)
        self._check_errors("SCPI command {!r}".format(command))

    def _force_rf_off(self):
        """Best effort after a rejected command; never claim success blindly."""
        if self._transport is None:
            return False
        try:
            self._transport.write(":OUTP:STAT OFF")
            return not _boolean(self._transport.query(":OUTP:STAT?"))
        except Exception:
            return False

    def _ram_waveform_names(self):
        """Read the RAM catalog, without enumerating or modifying saved files."""
        raw = self._transport.query(':MMEM:CAT? "WFM1:"')
        try:
            fields = next(csv.reader([raw], strict=True))
            if len(fields) < 2 or any(int(value) < 0 for value in fields[:2]):
                raise ValueError("missing memory totals")
            names = set()
            for entry in fields[2:]:
                if not entry.strip():
                    continue
                record = next(csv.reader([entry], strict=True))
                if len(record) != 3 or record[1].upper() != "WFM1" or int(record[2]) < 0:
                    raise ValueError("unrecognized waveform entry")
                name = record[0]
                names.add(name if name.upper().startswith("WFM1:") else "WFM1:" + name)
            return names
        except (ValueError, csv.Error, StopIteration) as exc:
            raise InstrumentError("Cannot parse waveform RAM catalog; cleanup stopped") from exc

    def _remove_owned_waveforms(self):
        """Free only tracked files from this controller's unique session.

        Call with RF off and playback of these files stopped. Verify absence
        after deletion; a failed cleanup must prevent another upload.
        """
        if not self._owned_waveforms:
            return
        pattern = r"WFM1:" + re.escape(self._session_prefix) + r"_[A-F0-9]+"
        if any(not re.fullmatch(pattern, name) for name in self._owned_waveforms):
            raise InstrumentError("Refusing deletion outside this session's temporary waveform names")
        names = set(self._owned_waveforms)
        if self.demo:
            self._owned_waveforms.clear()
            if self._demo_state["waveform"] in names:
                self._demo_state.update(waveform="", session_waveform=False)
            self._active_waveform = None
            self._active_bandwidth_hz = None
            return
        existing = self._ram_waveform_names()
        for name in sorted(names & existing):
            self._write_checked(':MMEM:DEL:NAME "{}"'.format(name))
        if self._transport.query("*OPC?").strip() != "1":
            raise InstrumentError("Temporary waveform deletion did not complete")
        remaining = names & self._ram_waveform_names()
        if remaining:
            raise InstrumentError("Temporary waveform deletion was not confirmed: " + ", ".join(sorted(remaining)))
        self._owned_waveforms.difference_update(names)
        if self._active_waveform in names:
            self._active_waveform = None
            self._active_bandwidth_hz = None

    def _require_arb_off(self):
        if not self.demo and _boolean(self._transport.query(":SOUR:RAD:ARB:STAT?")):
            raise InstrumentError("ARB did not stop; temporary waveform deletion refused")

    def cleanup_waveforms(self):
        """RF OFF, then remove this session's temporary RAM uploads.

        The GUI uses this on normal disconnect/exit. A broken connection or
        abrupt process termination may leave RAM files until restart. Files
        created by other sessions and saved NVWFM files are never deleted.
        """
        self._require_connection()
        if not self._owned_waveforms:
            return self.read_status()
        if self.demo:
            self._demo_state["rf_on"] = False
            if self._demo_state["waveform"] in self._owned_waveforms:
                self._demo_state.update(modulation_on=False, arb_on=False, iq_on=False, baseband_offset_hz=0.0)
            self._remove_owned_waveforms()
            return self.read_status()

        def commands():
            selected = self._transport.query(":SOUR:RAD:ARB:WAV?").strip().strip('"')
            selected_ram = selected if selected.startswith("WFM1:") else "WFM1:" + selected
            if selected_ram in self._owned_waveforms:
                self._write_checked(":OUTP:MOD:STAT OFF")
                self._write_checked(":SOUR:RAD:ARB:STAT OFF")
                self._write_checked(":SOUR:DM:STAT OFF")
                self._write_checked(":SOUR:RAD:ARB:BAS:FREQ:OFFS 0")
                self._write_checked(":SOUR:RAD:ARB:BAS:FREQ:OFFS:PHAS:RES")
                self._require_arb_off()
            self._remove_owned_waveforms()

        return self._run("temporary waveform cleanup", commands, {"rf_on": False}, gate_rf=True)

    def _run(self, label, commands, expected=None, gate_rf=False, rf_off_action=False):
        self._require_connection()
        try:
            # RF OFF must work even when the instrument has old queued errors.
            if rf_off_action:
                self._transport.write(":OUTP:STAT OFF")
            self._check_errors("Instrument errors before " + label)
            if gate_rf:
                self._write_checked(":OUTP:STAT OFF")
                if _boolean(self._transport.query(":OUTP:STAT?")):
                    raise InstrumentError("RF output did not switch OFF; configuration stopped")
            commands()
            if self._transport.query("*OPC?").strip() != "1":
                raise InstrumentError("Instrument did not confirm operation complete")
            self._check_errors("Instrument errors during " + label)
            status = self.read_status()
            for key, wanted in (expected or {}).items():
                actual = status[key]
                equal = math.isclose(actual, wanted, rel_tol=1e-8, abs_tol=1e-5) if isinstance(wanted, float) else actual == wanted
                if not equal:
                    raise InstrumentError("{} readback mismatch: wanted {!r}, got {!r}".format(key, wanted, actual))
            # Queries may expose an unsupported operation on an older firmware.
            self._check_errors("Instrument errors reading back " + label)
            return status
        except Exception as exc:
            if isinstance(exc, OSError):
                # A timed-out response or incomplete binary transfer cannot be
                # safely resynchronized by issuing additional SCPI commands.
                self.close()
                raise ConnectionError("{} failed: {}. RF state is unknown; use front-panel RF Off.".format(label, exc)) from exc
            confirmed = self._force_rf_off()
            message = "RF OFF confirmed." if confirmed else "RF state is unknown; use front-panel RF Off."
            raise InstrumentError("{} failed: {}. {}".format(label, exc, message)) from exc

    def _validate_rf_band(self, carrier_hz, offset_hz, bandwidth_hz):
        if not all(math.isfinite(value) for value in (carrier_hz, offset_hz, bandwidth_hz)):
            raise ValueError("Carrier, offset and bandwidth must be finite")
        minimum, maximum = 9e3, 6e9 if self._installed("506") else 3e9
        center = carrier_hz + offset_hz
        if center - bandwidth_hz / 2 < minimum or center + bandwidth_hz / 2 > maximum:
            raise ValueError("Shifted nominal signal band must remain within the generator RF range ({:g}..{:g} MHz)".format(minimum / 1e6, maximum / 1e6))

    def _validate_active_rf_band(self, carrier_hz=None):
        if self._active_bandwidth_hz is None:
            return
        state = self.read_status()
        if state["waveform"] == self._active_waveform:
            self._validate_rf_band(state["frequency_hz"] if carrier_hz is None else carrier_hz,
                                   state["baseband_offset_hz"], self._active_bandwidth_hz)

    def set_rf(self, enabled):
        self._require_connection()
        enabled = bool(enabled)
        if enabled:
            self._validate_active_rf_band()
        if self.demo:
            self._demo_state["rf_on"] = enabled
            return self.read_status()
        return self._run("RF " + ("ON" if enabled else "OFF"),
                         lambda: self._write_checked(":OUTP:STAT " + ("ON" if enabled else "OFF")),
                         {"rf_on": enabled}, rf_off_action=not enabled)

    def set_modulation(self, enabled):
        self._require_connection()
        enabled = bool(enabled)
        if enabled:
            self._validate_active_rf_band()
        # This is explicitly the global modulation switch, like the front panel.
        # Enabling it does not synthesize or select a new waveform.
        if self.demo:
            self._demo_state["modulation_on"] = enabled
            return self.read_status()
        return self._run("modulation " + ("ON" if enabled else "OFF"),
                         lambda: self._write_checked(":OUTP:MOD:STAT " + ("ON" if enabled else "OFF")),
                         {"modulation_on": enabled})

    def set_carrier(self, frequency_hz, power_dbm):
        self._require_connection()
        frequency = _number(frequency_hz, "Carrier frequency (Hz)", 9e3,
                            6e9 if self._installed("506") else 3e9)
        power = _number(power_dbm, "Power (dBm)", -144, 30)
        self._validate_active_rf_band(frequency)
        if self.demo:
            self._demo_state.update(rf_on=False, frequency_hz=frequency, power_dbm=power,
                                    frequency_mode="CW", power_mode="FIX", power_unit="DBM")
            return self.read_status()

        def commands():
            for command in (":SOUR:FREQ:MODE CW", ":SOUR:POW:MODE FIX", ":UNIT:POW DBM",
                            ":SOUR:FREQ:CW {:.12g} HZ".format(frequency),
                            ":SOUR:POW:LEV:IMM:AMPL {:.12g} DBM".format(power)):
                self._write_checked(command)

        return self._run("carrier settings", commands,
                         {"rf_on": False, "frequency_hz": frequency, "power_dbm": power,
                          "frequency_mode": "CW", "power_mode": "FIX"}, gate_rf=True)

    def _disable_engines(self):
        # LARB is only usable in LIST mode. Both configuration paths select
        # fixed CW mode explicitly, so no mode-dependent LARB command is needed.
        commands = [":OUTP:MOD:STAT OFF", ":SOUR:RAD:ARB:STAT OFF"]
        if self._installed("431"):
            commands += [":SOUR:RAD:DMOD:ARB:STAT OFF", ":SOUR:RAD:CUST:STAT OFF"]
        if self._installed("430"):
            commands += [":SOUR:RAD:MTON:ARB:STAT OFF", ":SOUR:RAD:TTON:ARB:STAT OFF"]
        if self._installed("403"):
            commands += [":SOUR:RAD:AWGN:RT:STAT OFF", ":SOUR:RAD:ARB:NOIS:STAT OFF"]
        if self._installed("UNT"):
            commands += [":SOUR:{}{}:STAT OFF".format(family, channel)
                         for family in ("AM", "FM", "PM") for channel in (1, 2)]
        if self._installed("UNW"):
            commands += [":SOUR:PULM:STAT OFF"]
        for command in commands:
            self._write_checked(command)

    def set_cw(self):
        self._require_connection()
        if self.demo:
            self._demo_state.update(rf_on=False, modulation_on=False, arb_on=False, iq_on=False,
                                    frequency_mode="CW", power_mode="FIX", baseband_offset_hz=0.0)
            self._remove_owned_waveforms()
            return self.read_status()

        def commands():
            self._disable_engines()
            self._write_checked(":SOUR:DM:STAT OFF")
            self._write_checked(":SOUR:RAD:ARB:BAS:FREQ:OFFS 0")
            self._write_checked(":SOUR:RAD:ARB:BAS:FREQ:OFFS:PHAS:RES")
            self._write_checked(":SOUR:FREQ:MODE CW")
            self._write_checked(":SOUR:POW:MODE FIX")
            self._require_arb_off()
            self._remove_owned_waveforms()

        return self._run("CW mode", commands,
                         {"rf_on": False, "modulation_on": False, "arb_on": False,
                          "iq_on": False, "frequency_mode": "CW", "power_mode": "FIX"}, gate_rf=True)

    def apply_waveform(self, waveform):
        self._require_connection()
        if not (self._installed("653") or self._installed("655")):
            raise InstrumentError("An internal ARB baseband generator (option 653) is required")
        if __package__:
            from .n5172b_waveforms import MAX_BASEBAND_EDGE_HZ, to_scpi_iq_bytes
        else:
            from n5172b_waveforms import MAX_BASEBAND_EDGE_HZ, to_scpi_iq_bytes
        maximum = 150e6 if self._installed("655") else 75e6
        rate = _number(waveform.sample_rate_hz, "ARB sample rate (Sa/s)", 100, maximum)
        offset = _number(waveform.metadata.get("frequency_offset_hz", 0.0), "Frequency offset (Hz)", -50e6, 50e6)
        bandwidth = _number(waveform.metadata.get("bandwidth_hz", 0.0), "Waveform bandwidth (Hz)", 0, 2 * MAX_BASEBAND_EDGE_HZ)
        if abs(offset) + bandwidth / 2 > MAX_BASEBAND_EDGE_HZ:
            raise ValueError("Shifted nominal waveform band exceeds the +/-30 MHz application limit")
        # Validate/serialize fully before any command changes instrument state.
        payload = to_scpi_iq_bytes(waveform.iq)
        if not 60 <= len(payload) // 4 <= 1_000_000 or len(payload) % 16:
            raise ValueError("Waveform requires 60..1000000 IQ samples, in multiples of four")
        carrier = self._demo_state["frequency_hz"] if self.demo else float(self._transport.query(":SOUR:FREQ:CW?"))
        self._validate_rf_band(carrier, offset, bandwidth)
        self._waveform_number += 1
        name = "WFM1:{}_{:X}".format(self._session_prefix, self._waveform_number)
        if self.demo:
            self._demo_state.update(rf_on=False, arb_on=False, iq_on=False)
            self._remove_owned_waveforms()
            self._owned_waveforms.add(name)
            self._active_waveform = name
            self._demo_state.update(rf_on=False, modulation_on=True, arb_on=True, iq_on=True,
                                    waveform=name, sample_rate_hz=rate, arb_filter_on=False,
                                    iq_source="INT", frequency_mode="CW", power_mode="FIX",
                                    session_waveform=True, baseband_offset_hz=offset)
            self._active_bandwidth_hz = bandwidth
            return self.read_status()

        def commands():
            self._disable_engines()
            self._write_checked(":SOUR:DM:STAT OFF")
            self._require_arb_off()
            self._remove_owned_waveforms()
            # Register before transfer: a failed/partial transfer may still
            # allocate a file, which must be reclaimed before retrying.
            self._owned_waveforms.add(name)
            self._transport.write_binary(':MMEM:DATA "{}",'.format(name), payload)
            if self._transport.query("*OPC?").strip() != "1":
                raise InstrumentError("Waveform transfer did not complete")
            self._check_errors('SCPI waveform upload :MMEM:DATA "{}"'.format(name))
            for command in (
                ':SOUR:RAD:ARB:WAV "{}"'.format(name),
                ":SOUR:FREQ:MODE CW", ":SOUR:POW:MODE FIX",
                ":SOUR:RAD:ARB:FILT:STAT OFF",
                ":SOUR:RAD:ARB:SCL:RATE {:.12g}".format(rate),
                ":SOUR:RAD:ARB:BAS:FREQ:OFFS {:.12g}".format(offset),
                ":SOUR:RAD:ARB:BAS:FREQ:OFFS:PHAS:RES",
                ":SOUR:RAD:ARB:RSC 100",
                ":SOUR:RAD:ARB:TRIG:TYPE CONT",
                ":SOUR:RAD:ARB:TRIG:TYPE:CONT:TYPE FREE",
                # MDEStination has exactly two spellings: MDES or
                # MDESTINATION. The partial form MDEST raises error -113.
                ":SOUR:RAD:ARB:MDES:PULS NONE", ":SOUR:RAD:ARB:MDES:ALCH NONE",
                ":SOUR:RAD:ARB:MDES:AAMP NONE",
                ":SOUR:DM:SOUR INT", ":SOUR:DM:POL NORM",
                ":SOUR:DM:IQAD:STAT OFF", ":SOUR:DM:INT:EQU:FILT:STAT OFF",
                ":SOUR:RAD:ARB:IQ:MOD:ATT:AUTO ON",
                ":SOUR:RAD:ARB:STAT ON", ":SOUR:DM:STAT ON", ":OUTP:MOD:STAT ON",
            ):
                self._write_checked(command)

        transport = self._transport
        original_timeout = transport.timeout
        transport.timeout = max(self.timeout, 30.0)
        try:
            status = self._run("waveform configuration", commands,
                               {"rf_on": False, "modulation_on": True, "arb_on": True,
                                "iq_on": True, "waveform": name, "sample_rate_hz": rate,
                                "arb_filter_on": False, "iq_source": "INT",
                                "baseband_offset_hz": offset,
                                "frequency_mode": "CW", "power_mode": "FIX"}, gate_rf=True)
            self._active_waveform = name
            self._active_bandwidth_hz = bandwidth
            status["session_waveform"] = True
            return status
        finally:
            transport.timeout = original_timeout
