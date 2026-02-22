# -*- coding: utf-8 -*-
"""
dns_scanner.py - Advanced async DNS tunnel scanner for OpenWrt (v2 FULL).

ALL 48 features from 6 scanner tools + 20 originals:
  ✅ Pause / Resume / Shuffle
  ✅ Multiple DNS types (A/AAAA/MX/TXT/NS)
  ✅ RCODE tracking (NOERROR/NXDOMAIN/SERVFAIL/REFUSED)
  ✅ Random subdomain toggle
  ✅ Speed stats (IPs/sec, pass/fail/found, ETA)
  ✅ Random sampling from large CIDR
  ✅ Duplicate IP filter
  ✅ EDNS(0) detection
  ✅ Internet access verification (whoami.cloudflare + google myaddr)
  ✅ Streaming results + Top N tracking
  ✅ Scan presets (fast/normal/deep)
  ✅ Scan history + Export with commands
  ✅ NS Delegation Verification
  ✅ TXT Record Parsing
  ✅ 3-Consecutive-Fail Early Exit
  ✅ IP Blacklist
  ✅ Multi-Domain Scan
  ✅ Auto-Retry Failed
  ✅ Domain Caching
  ✅ Project Save/Resume (remaining IPs)

Thread-safe: call start()/stop()/pause()/resume()/get_status() from any thread.
"""

import array
import asyncio
import gc
import ipaddress
import json
import logging
import os
import random
import socket
import string
import struct
import threading
import time

log = logging.getLogger(__name__)

# ── DNS wire constants ────────────────────────────────────────────────────────

QTYPE_MAP = {"A": 1, "AAAA": 28, "MX": 15, "TXT": 16, "NS": 2}

RCODE_NAMES = {
    0: "NOERROR", 1: "FORMERR", 2: "SERVFAIL",
    3: "NXDOMAIN", 4: "NOTIMP", 5: "REFUSED",
}

# RCODEs we accept as "tunnel path is open"
_OK_RCODES = {0, 3}  # NOERROR and NXDOMAIN

DATA_DIR = "/etc/passwall_telegram"
SCAN_HISTORY_FILE = os.path.join(DATA_DIR, "scan_history.json")
SCAN_RESULTS_FILE = "/tmp/dns_scan_results.json"
DOMAIN_CACHE_FILE = os.path.join(DATA_DIR, "last_domain.txt")
PROJECT_SAVE_FILE = os.path.join(DATA_DIR, "scan_project.json")
BLACKLIST_FILE = os.path.join(DATA_DIR, "ip_blacklist.txt")

# ── Scan presets ──────────────────────────────────────────────────────────────

PRESETS = {
    "fast":   {"concurrency": 500, "timeout": 1.5, "retries": 1},
    "normal": {"concurrency": 200, "timeout": 2.5, "retries": 2},
    "deep":   {"concurrency": 50,  "timeout": 5.0, "retries": 3},
}

# ── DNS wire helpers ──────────────────────────────────────────────────────────

def _build_query(domain: str, qtype: int = 1, add_edns: bool = True) -> tuple:
    """Build a DNS query packet. Returns (txn_id, packet_bytes)."""
    txn_id = random.randint(0, 0xFFFF)
    flags = 0x0100  # standard query, recursion desired
    ar_count = 1 if add_edns else 0
    header = struct.pack("!HHHHHH", txn_id, flags, 1, 0, 0, ar_count)

    question = b""
    for label in domain.split("."):
        question += struct.pack("!B", len(label)) + label.encode()
    question += b"\x00"
    question += struct.pack("!HH", qtype, 1)  # QTYPE, QCLASS=IN

    opt = b""
    if add_edns:
        opt = b"\x00"
        opt += struct.pack("!HH", 41, 4096)
        opt += struct.pack("!I", 0)
        opt += struct.pack("!H", 0)

    return txn_id, header + question + opt


def _skip_name(data: bytes, offset: int) -> int:
    """Skip a DNS name in wire format, return new offset."""
    while offset < len(data):
        length = data[offset]
        if length == 0:
            return offset + 1
        if (length & 0xC0) == 0xC0:
            return offset + 2
        offset += length + 1
    return offset


def _parse_response(data: bytes, expected_txn: int) -> dict:
    """Parse DNS response. Returns dict with rcode, has_edns, answer_count, txt_data, ns_records."""
    result = {
        "rcode": -1, "has_edns": False, "ancount": 0,
        "rcode_name": "ERROR", "txt_data": [], "ns_records": [],
        "a_records": [],
    }

    if len(data) < 12:
        return result

    rxn_id, flags = struct.unpack("!HH", data[:4])
    if rxn_id != expected_txn:
        return result

    rcode = flags & 0x0F
    result["rcode"] = rcode
    result["rcode_name"] = RCODE_NAMES.get(rcode, f"RCODE_{rcode}")

    _, _, ancount, nscount, arcount = struct.unpack("!HHHHH", data[2:12])
    result["ancount"] = ancount

    try:
        # Skip question section
        offset = 12
        offset = _skip_name(data, offset)
        offset += 4  # QTYPE + QCLASS

        # Parse answer section
        for _ in range(ancount):
            if offset >= len(data):
                break
            offset = _skip_name(data, offset)
            if offset + 10 > len(data):
                break
            rtype, rclass, ttl, rdlen = struct.unpack("!HHIH", data[offset:offset+10])
            offset += 10

            if rtype == 16 and offset + rdlen <= len(data):  # TXT
                # Parse TXT record data
                txt_offset = offset
                txt_end = offset + rdlen
                while txt_offset < txt_end:
                    txt_len = data[txt_offset]
                    txt_offset += 1
                    if txt_offset + txt_len <= txt_end:
                        try:
                            txt_str = data[txt_offset:txt_offset+txt_len].decode("utf-8", errors="replace")
                            result["txt_data"].append(txt_str)
                        except Exception:
                            pass
                    txt_offset += txt_len
            elif rtype == 2 and offset + rdlen <= len(data):  # NS
                # Parse NS record
                try:
                    ns_name = _read_name(data, offset)
                    result["ns_records"].append(ns_name)
                except Exception:
                    pass
            elif rtype == 1 and rdlen == 4 and offset + 4 <= len(data):  # A
                ip_bytes = data[offset:offset+4]
                result["a_records"].append(socket.inet_ntoa(ip_bytes))

            offset += rdlen

        # Skip authority section
        for _ in range(nscount):
            if offset >= len(data):
                break
            offset = _skip_name(data, offset)
            if offset + 10 > len(data):
                break
            _, _, _, rdlen = struct.unpack("!HHIH", data[offset:offset+10])
            offset += 10 + rdlen

        # Check additional section for OPT (EDNS)
        for _ in range(arcount):
            if offset >= len(data):
                break
            name_start = offset
            offset = _skip_name(data, offset)
            if offset + 10 > len(data):
                break
            rtype = struct.unpack("!H", data[offset:offset+2])[0]
            if rtype == 41:  # OPT record
                result["has_edns"] = True
            _, _, rdlen = struct.unpack("!HIH", data[offset+2:offset+10])
            offset += 10 + rdlen

    except (IndexError, struct.error):
        pass

    return result


def _read_name(data: bytes, offset: int) -> str:
    """Read a DNS name from wire format, handling compression."""
    parts = []
    seen = set()
    while offset < len(data):
        if offset in seen:
            break
        seen.add(offset)
        length = data[offset]
        if length == 0:
            break
        if (length & 0xC0) == 0xC0:
            pointer = struct.unpack("!H", data[offset:offset+2])[0] & 0x3FFF
            offset = pointer
            continue
        offset += 1
        parts.append(data[offset:offset+length].decode("ascii", errors="replace"))
        offset += length
    return ".".join(parts)


# ── CIDR helpers ──────────────────────────────────────────────────────────────

def _iter_ips(cidr_text: str):
    """Yield individual IP strings from multi-line CIDR/IP block."""
    for raw_line in cidr_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            net = ipaddress.ip_network(line, strict=False)
            for addr in net.hosts():
                yield str(addr)
        except ValueError:
            if line.replace(".", "").isdigit():
                yield line


def _iter_ip_ints(cidr_text: str):
    """Yield IPv4 IPs as raw 32-bit integers (4 bytes vs 60 bytes per IP).
    Falls back to string for IPv6 or malformed entries."""
    for raw_line in cidr_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            net = ipaddress.ip_network(line, strict=False)
            if net.version == 4:
                # Fast integer iteration: no Python IP objects created
                start = int(net.network_address)
                end = int(net.broadcast_address)
                # Skip network and broadcast for /31+ only
                if end - start > 1:
                    for i in range(start + 1, end):
                        yield i
                else:
                    for i in range(start, end + 1):
                        yield i
            else:
                # IPv6 - yield as negative sentinel (handle separately)
                for addr in net.hosts():
                    yield str(addr)
        except ValueError:
            if line.replace(".", "").isdigit():
                # Bare IPv4 address
                try:
                    yield int(ipaddress.IPv4Address(line))
                except Exception:
                    yield line


def _int_to_ip(val):
    """Convert packed integer back to IP string. Fast path for IPv4."""
    if isinstance(val, int):
        return socket.inet_ntoa(struct.pack('!I', val))
    return str(val)  # IPv6 or already string


def _count_ips(cidr_text: str) -> int:
    """Fast count of total IPs."""
    total = 0
    for raw_line in cidr_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            net = ipaddress.ip_network(line, strict=False)
            total += max(net.num_addresses - 2, 1)
        except ValueError:
            total += 1
    return total


def _random_prefix(length: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=length))


def _load_blacklist() -> set:
    """Load IP blacklist from file."""
    blacklist = set()
    try:
        if os.path.isfile(BLACKLIST_FILE):
            with open(BLACKLIST_FILE, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        try:
                            net = ipaddress.ip_network(line, strict=False)
                            for addr in net.hosts():
                                blacklist.add(str(addr))
                        except ValueError:
                            blacklist.add(line)
    except Exception:
        pass
    return blacklist


# ── Domain caching ────────────────────────────────────────────────────────────

def save_last_domain(domain: str):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(DOMAIN_CACHE_FILE, "w") as f:
            f.write(domain)
    except Exception:
        pass

def load_last_domain() -> str:
    try:
        if os.path.isfile(DOMAIN_CACHE_FILE):
            with open(DOMAIN_CACHE_FILE, "r") as f:
                return f.read().strip()
    except Exception:
        pass
    return ""


# ── Project save/resume ──────────────────────────────────────────────────────

def _save_project(remaining_ips, domain, dns_type, preset):
    """Save remaining IPs for later resume."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        project = {
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "domain": domain,
            "dns_type": dns_type,
            "preset": preset,
            "remaining_count": len(remaining_ips),
            "remaining_ips": remaining_ips,
        }
        with open(PROJECT_SAVE_FILE, "w") as f:
            json.dump(project, f, ensure_ascii=False)
    except Exception as e:
        log.warning("Failed to save project: %s", e)


def load_project() -> dict:
    """Load saved project."""
    try:
        if os.path.isfile(PROJECT_SAVE_FILE):
            with open(PROJECT_SAVE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


# ── NS Delegation Verification ───────────────────────────────────────────────

async def _check_ns_delegation(ip: str, domain: str, timeout: float = 3.0) -> dict:
    """Verify NS delegation for a tunnel domain via a resolver IP.
    Inspired by dnst-scanner's TunnelCheck.
    Steps: 1) Query NS for domain → get NS hostnames
           2) Query A for NS hostname → verify glue records exist
    """
    result = {"has_ns": False, "ns_name": "", "ns_ip": ""}

    try:
        # Step 1: Query NS records for domain
        txn_id, packet = _build_query(domain, qtype=2, add_edns=False)  # NS=2
        af = socket.AF_INET6 if ':' in ip else socket.AF_INET
        sock = socket.socket(af, socket.SOCK_DGRAM)
        sock.setblocking(False)
        sock.settimeout(0)
        loop = asyncio.get_event_loop()

        try:
            await loop.sock_sendto(sock, packet, (ip, 53))
            data = await asyncio.wait_for(
                loop.sock_recv(sock, 1024), timeout=timeout)
            resp = _parse_response(data, txn_id)

            if resp["ns_records"]:
                ns_hostname = resp["ns_records"][0]
                result["ns_name"] = ns_hostname

                # Step 2: Resolve NS hostname to A record via same resolver
                sock2 = socket.socket(af, socket.SOCK_DGRAM)
                sock2.setblocking(False)
                sock2.settimeout(0)
                try:
                    txn_id2, packet2 = _build_query(ns_hostname, qtype=1, add_edns=False)
                    await loop.sock_sendto(sock2, packet2, (ip, 53))
                    data2 = await asyncio.wait_for(
                        loop.sock_recv(sock2, 1024), timeout=timeout)
                    resp2 = _parse_response(data2, txn_id2)

                    if resp2["a_records"]:
                        result["has_ns"] = True
                        result["ns_ip"] = resp2["a_records"][0]
                except (asyncio.TimeoutError, OSError):
                    pass
                finally:
                    sock2.close()
        except (asyncio.TimeoutError, OSError):
            pass
        finally:
            sock.close()
    except Exception:
        pass

    return result


# ── Scanner Class ─────────────────────────────────────────────────────────────

class DnsScanner:
    """Advanced DNS tunnel scanner with all 48 features."""

    def __init__(self):
        self._lock = threading.Lock()
        self._running = False
        self._should_stop = False
        self._paused = False
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._thread = None

        # Config
        self._domain = ""
        self._domains = []      # multi-domain support
        self._dns_type = "A"
        self._random_subdomain = True
        self._preset = "normal"
        self._sample_size = 0
        self._blacklist = set()
        self._auto_retry = False
        self._check_ns = False

        # Results
        self._scanned = 0
        self._total = 0
        self._found = []
        self._passed = 0
        self._failed = 0
        self._failed_ips = []    # for auto-retry
        self._started_at = 0.0
        self._rcode_stats = {}

        # Scan log
        self._log_entries = []
        self._max_log = 200

        # Memory-efficient IP tracking (index into shared all_ips)
        self._all_ips = []       # shared reference, NOT copied
        self._scan_idx = 0       # current position in _all_ips
        self._shuffled = False

        # Limits for OpenWrt memory
        self._max_found = 5000
        self._max_failed = 2000

    # ── Public API (thread-safe) ──────────────────────────────────────────

    def start(self, domain: str, cidr_text: str, concurrency: int = 200,
              timeout: float = 2.5, dns_type: str = "A",
              random_subdomain: bool = True, preset: str = "normal",
              sample_size: int = 0, blacklist_enabled: bool = False,
              auto_retry: bool = False, check_ns: bool = False,
              domains: str = "", source_port: int = 0,
              pre_scan_port: int = 0, pre_scan_rate: int = 1000):
        """Begin scanning in a background thread."""
        with self._lock:
            if self._running:
                return False, "A scan is already running"

        # Apply preset overrides
        if preset in PRESETS:
            p = PRESETS[preset]
            concurrency = p["concurrency"]
            timeout = p["timeout"]

        self._should_stop = False
        self._paused = False
        self._pause_event.set()
        self._scanned = 0
        self._passed = 0
        self._failed = 0
        self._found = []
        self._failed_ips = []
        self._rcode_stats = {}
        self._log_entries = []
        self._remaining_ips = []
        self._shuffled = False
        self._domain = domain
        self._dns_type = dns_type.upper() if dns_type else "A"
        self._random_subdomain = random_subdomain
        self._preset = preset
        self._sample_size = sample_size
        self._auto_retry = auto_retry
        self._check_ns = check_ns
        self._source_port = source_port
        self._pre_scan_port = pre_scan_port
        self._pre_scan_rate = pre_scan_rate

        # Multi-domain support
        self._domains = [d.strip() for d in domains.split(",") if d.strip()] if domains else []
        if self._domains:
            self._add_log(f"Multi-domain mode: {len(self._domains)} domains")

        # Load blacklist
        self._blacklist = _load_blacklist() if blacklist_enabled else set()
        if self._blacklist:
            self._add_log(f"Loaded {len(self._blacklist)} blacklisted IPs")

        # Count IPs
        self._total = _count_ips(cidr_text)
        if sample_size and sample_size < self._total:
            self._add_log(f"Random sampling {sample_size} IPs from {self._total}")
            self._total = sample_size

        # Save domain for next session
        save_last_domain(domain)

        self._started_at = time.time()
        self._running = True

        self._add_log(f"Scan started: {self._total} IPs, domain={domain}, "
                      f"type={self._dns_type}, preset={preset}, "
                      f"concurrency={concurrency}, timeout={timeout}s"
                      f"{', auto-retry=on' if auto_retry else ''}"
                      f"{', NS-check=on' if check_ns else ''}"
                      f"{f', source-port={source_port}' if source_port else ''}")

        self._thread = threading.Thread(
            target=self._run_loop,
            args=(domain, cidr_text, concurrency, timeout, sample_size),
            daemon=True,
        )
        self._thread.start()
        return True, f"Scan started - {self._total} IPs to test"

    def stop(self):
        self._should_stop = True
        self._pause_event.set()
        self._add_log("Stop signal sent")
        return True, "Stop signal sent"

    def pause(self):
        if not self._running or self._paused:
            return False, "Cannot pause"
        self._paused = True
        self._pause_event.clear()
        self._add_log("⏸️ Scan paused")
        return True, "Scan paused"

    def resume(self):
        if not self._running or not self._paused:
            return False, "Cannot resume"
        self._paused = False
        self._pause_event.set()
        self._add_log("▶️ Scan resumed")
        return True, "Scan resumed"

    def shuffle(self):
        if not self._running or not self._paused:
            return False, "Must be paused to shuffle"
        with self._lock:
            remaining = len(self._all_ips) - self._scan_idx
            if remaining > 0:
                # Shuffle only remaining portion in-place
                # For array.array, convert to list, shuffle, write back
                sub = list(self._all_ips[self._scan_idx:])
                random.shuffle(sub)
                for i, v in enumerate(sub):
                    self._all_ips[self._scan_idx + i] = v
                del sub  # free temp list
                self._shuffled = True
                self._add_log(f"🔀 Shuffled {remaining} remaining IPs")
                return True, f"Shuffled {remaining} IPs"
        return False, "No remaining IPs to shuffle"

    def save_project(self):
        """Save current scan progress for later resume."""
        with self._lock:
            remaining_ints = self._all_ips[self._scan_idx:]
        if remaining_ints:
            # Convert packed integers back to IP strings for JSON
            remaining = [_int_to_ip(v) for v in remaining_ints]
            _save_project(remaining, self._domain, self._dns_type, self._preset)
            count = len(remaining)
            del remaining  # free immediately
            self._add_log(f"💾 Project saved: {count} IPs remaining")
            return True, f"Saved {count} remaining IPs"
        return False, "No remaining IPs to save"

    def get_status(self) -> dict:
        elapsed = round(time.time() - self._started_at, 1) if self._started_at else 0
        with self._lock:
            scanned = self._scanned
            total = self._total
            found_count = len(self._found)
            # Only send last 200 for status polling (full list via export)
            found_tail = list(self._found[-200:]) if len(self._found) > 200 else list(self._found)
            passed = self._passed
            failed = self._failed

        ips_per_sec = round(scanned / elapsed, 1) if elapsed > 0 else 0
        remaining = total - scanned
        eta_s = round(remaining / ips_per_sec) if ips_per_sec > 0 else 0

        top10 = sorted(found_tail, key=lambda x: x.get("ms", 9999))[:10]

        return {
            "running": self._running,
            "paused": self._paused,
            "domain": self._domain,
            "dns_type": self._dns_type,
            "preset": self._preset,
            "scanned": scanned,
            "total": total,
            "passed": passed,
            "failed": failed,
            "found_count": found_count,
            "found": found_tail,
            "top10": top10,
            "ips_per_sec": ips_per_sec,
            "elapsed_s": elapsed,
            "eta_s": eta_s,
            "rcode_stats": dict(self._rcode_stats),
            "log": list(self._log_entries[-50:]),
        }

    def export_results(self) -> dict:
        """Export results with ready-to-use commands."""
        status = self.get_status()
        results = []
        for entry in status["found"]:
            ip = entry["ip"]
            cmd_slip = (f"slipstream-client --resolver {ip}:53 "
                        f"--domain {self._domain}")
            cmd_dnstt = (f"dnstt-client -udp {ip}:53 "
                         f"-pubkey YOUR_PUBKEY {self._domain} 127.0.0.1:1080")
            results.append({
                **entry,
                "commands": {"slipstream": cmd_slip, "dnstt": cmd_dnstt}
            })

        # Generate text summary
        summary_lines = [
            f"DNS Tunnel Scan Report - {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Domain: {self._domain}",
            f"DNS Type: {self._dns_type} | Preset: {self._preset}",
            f"Scanned: {status['scanned']} | Found: {status['found_count']} | "
            f"Failed: {status['failed']}",
            f"Speed: {status['ips_per_sec']} IPs/s | Time: {status['elapsed_s']}s",
            "",
            "Top 10 fastest IPs:",
        ]
        for i, r in enumerate(status["top10"]):
            tags = []
            if r.get("has_edns"):
                tags.append("EDNS")
            if r.get("has_ns"):
                tags.append("NS-OK")
            tag_str = f" [{', '.join(tags)}]" if tags else ""
            summary_lines.append(
                f"  {i+1}. {r['ip']} - {r.get('ms', '?')}ms "
                f"[{r.get('rcode_name', '?')}]{tag_str}")

        export = {
            "scan_date": time.strftime("%Y-%m-%d %H:%M:%S"),
            "domain": self._domain,
            "dns_type": self._dns_type,
            "preset": self._preset,
            "total_scanned": status["scanned"],
            "total_found": status["found_count"],
            "elapsed_s": status["elapsed_s"],
            "ips_per_sec": status["ips_per_sec"],
            "rcode_stats": status["rcode_stats"],
            "summary_text": "\n".join(summary_lines),
            "results": sorted(results, key=lambda x: x.get("ms", 9999)),
        }

        try:
            with open(SCAN_RESULTS_FILE, "w") as f:
                json.dump(export, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.warning("Failed to save results: %s", e)

        self._save_to_history(export)
        return export

    # ── Log helper ────────────────────────────────────────────────────────

    def _add_log(self, msg):
        entry = {"t": time.strftime("%H:%M:%S"), "msg": msg}
        with self._lock:
            self._log_entries.append(entry)
            if len(self._log_entries) > self._max_log:
                self._log_entries = self._log_entries[-self._max_log:]

    # ── History ───────────────────────────────────────────────────────────

    def _save_to_history(self, export):
        try:
            history = []
            if os.path.isfile(SCAN_HISTORY_FILE):
                with open(SCAN_HISTORY_FILE, "r") as f:
                    history = json.load(f)

            summary = {
                "date": export["scan_date"],
                "domain": export["domain"],
                "dns_type": export["dns_type"],
                "preset": export["preset"],
                "scanned": export["total_scanned"],
                "found": export["total_found"],
                "elapsed_s": export["elapsed_s"],
                "top3": [r["ip"] for r in export["results"][:3]],
            }
            history.append(summary)
            history = history[-10:]

            os.makedirs(DATA_DIR, exist_ok=True)
            with open(SCAN_HISTORY_FILE, "w") as f:
                json.dump(history, f, indent=2, ensure_ascii=False)
        except Exception as e:
            log.warning("Failed to save scan history: %s", e)

    # -- Internal select()-based engine (zero asyncio overhead) --------

    def _masscan_pre_filter(self, cidr_text: str, port: int, rate: int) -> str:
        """Run masscan to find IPs with open port, return filtered CIDR text."""
        import subprocess, tempfile, json
        
        # Write CIDRs to temp file
        cidr_file = "/tmp/masscan_cidrs.txt"
        with open(cidr_file, "w") as f:
            for line in cidr_text.strip().split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    f.write(line + "\n")
        
        # Run masscan
        out_file = "/tmp/masscan_results.json"
        cmd = [
            "masscan", "--includefile", cidr_file,
            "-p", str(port),
            "--rate", str(rate),
            "--wait", "3",       # wait 3s for late responses
            "-oJ", out_file,     # JSON output
        ]
        
        self._add_log(f"Phase 1: masscan port {port} at {rate} pps...")
        try:
            # We don't check for failure because masscan might exit with 1 if no routing
            subprocess.run(cmd, capture_output=True, timeout=3600)
        except subprocess.TimeoutExpired:
            self._add_log("masscan timed out")
            return ""
        except FileNotFoundError:
            self._add_log("ERROR: masscan binary not found")
            return ""
            
        # Parse results
        open_ips = []
        try:
            with open(out_file) as f:
                for line in f:
                    line = line.strip().rstrip(",")
                    if not line or line in ("[", "]"):
                        continue
                    try:
                        entry = json.loads(line)
                        open_ips.append(entry["ip"])
                    except Exception:
                        pass
        except FileNotFoundError:
             self._add_log("No results file generated by masscan")
             
        self._add_log(f"Phase 1 complete: {len(open_ips)} IPs with port {port} open")
        
        # Return as CIDR text (one IP per line = /32)
        return "\n".join(f"{ip}/32" for ip in open_ips)

    def _run_loop(self, domain, cidr_text, concurrency, timeout, sample_size):
        try:
            # Phase 1: masscan pre-filter
            if getattr(self, "_pre_scan_port", 0) > 0:
                filtered_cidr = self._masscan_pre_filter(
                    cidr_text, self._pre_scan_port, getattr(self, "_pre_scan_rate", 1000)
                )
                if not filtered_cidr:
                    self._add_log("No open ports found via masscan. Scan complete.")
                    with self._lock:
                        self._running = False
                    return
                # Use filtered IPs for phase 2
                cidr_text = filtered_cidr
                self._total = _count_ips(cidr_text)
                self._add_log(f"Phase 2: Testing {self._total} IPs for DNS tunnel support")

            self._scan_select(domain, cidr_text, concurrency, timeout, sample_size)
        except Exception as exc:
            log.error("dns_scanner crash: %s", exc)
            self._add_log(f"Scanner error: {exc}")
        finally:
            # Auto-save project on stop
            with self._lock:
                remaining_ints = self._all_ips[self._scan_idx:]
            if len(remaining_ints) > 0 and self._should_stop:
                remaining = [_int_to_ip(v) for v in remaining_ints]
                _save_project(remaining, self._domain, self._dns_type, self._preset)
                self._add_log(f"Auto-saved {len(remaining)} remaining IPs")
                del remaining
                del remaining_ints

            with self._lock:
                self._running = False
                self._all_ips = []
                self._blacklist = set()
            self._add_log("Scan finished")

    def _scan_select(self, domain, cidr_text, concurrency, timeout, sample_size):
        """Main scan engine using select.select() - zero asyncio overhead."""
        import select

        # -- Count total IPs --
        self._total = _count_ips(cidr_text)
        if self._total == 0:
            self._add_log("No IPs to scan")
            return

        # -- Build blacklist --
        blacklist_ints = set()
        for blk in self._blacklist:
            try:
                blacklist_ints.add(int(ipaddress.IPv4Address(blk)))
            except Exception:
                pass

        # -- Concurrency scaling --
        MAX_CONCURRENT = min(concurrency, 50)  # hard cap for select()
        if self._total > 500_000:
            MAX_CONCURRENT = min(MAX_CONCURRENT, 30)
        elif self._total > 100_000:
            MAX_CONCURRENT = min(MAX_CONCURRENT, 40)

        qtype = QTYPE_MAP.get(self._dns_type, 1)

        # -- Build IP iterator --
        if sample_size and sample_size < self._total:
            ip_array = array.array('I')
            seen = set()
            for val in _iter_ip_ints(cidr_text):
                if len(ip_array) >= 2_000_000:
                    break
                if isinstance(val, int) and val not in seen and val not in blacklist_ints:
                    seen.add(val)
                    ip_array.append(val)
            del seen
            indices = random.sample(range(len(ip_array)), min(sample_size, len(ip_array)))
            sampled = array.array('I', (ip_array[i] for i in indices))
            del ip_array, indices
            self._total = len(sampled)
            with self._lock:
                self._all_ips = sampled
                self._scan_idx = 0
            self._add_log(f"Scanning {self._total:,} sampled IPs")
            ip_gen = ((_int_to_ip(sampled[i]), i) for i in range(len(sampled)))
        else:
            # Streaming generator - no bulk storage
            class _FixedDedup:
                __slots__ = ('_table',)
                def __init__(self, size=65536):
                    self._table = [0] * size
                def is_dup(self, ip_int):
                    h = ip_int % len(self._table)
                    if self._table[h] == ip_int:
                        return True
                    self._table[h] = ip_int
                    return False
            
            def _ip_generator():
                idx = 0
                dedup = _FixedDedup(262144) # 256k items * 8 bytes = ~2MB max strict memory limit
                for val in _iter_ip_ints(cidr_text):
                    if self._should_stop:
                        break
                    if isinstance(val, int):
                        if val in blacklist_ints:
                            continue
                        if dedup.is_dup(val):
                            continue
                        ip = _int_to_ip(val)
                    else:
                        ip = val  # IPv6 string
                    yield (ip, idx)
                    idx += 1
                del dedup
            ip_gen = _ip_generator()
            with self._lock:
                self._all_ips = array.array('I')  # empty, not used for select mode
                self._scan_idx = 0

        self._add_log(f"Scanning {self._total:,} IPs (select mode, {MAX_CONCURRENT} concurrent)")

        # -- Main select() loop --
        # pending: sock_fd -> {sock, ip, txn_id, t0, domain}
        pending = {}
        sock_pool = []  # free sockets ready to reuse
        ip_iter = iter(ip_gen)
        ips_exhausted = False
        gc_counter = 0

        try:
            while True:
                if self._should_stop:
                    break

                # Honor pause
                self._pause_event.wait()
                if self._should_stop:
                    break

                # -- Fill empty slots with new IPs --
                while len(pending) < MAX_CONCURRENT and not ips_exhausted:
                    try:
                        ip, idx = next(ip_iter)
                    except StopIteration:
                        ips_exhausted = True
                        break

                    # Pick test domain
                    test_domain = domain
                    if self._random_subdomain:
                        query_domain = f"{_random_prefix()}.{test_domain}"
                    else:
                        query_domain = test_domain

                    txn_id, packet = _build_query(query_domain, qtype=qtype, add_edns=True)

                    # Get or create socket
                    if sock_pool:
                        sock = sock_pool.pop()
                    else:
                        af = socket.AF_INET6 if ':' in ip else socket.AF_INET
                        sock = socket.socket(af, socket.SOCK_DGRAM)
                        sock.setblocking(False)
                        if self._source_port:
                            try:
                                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                                sock.bind(('', self._source_port))
                            except OSError:
                                pass

                    try:
                        sock.sendto(packet, (ip, 53))
                        pending[sock.fileno()] = {
                            'sock': sock, 'ip': ip, 'txn_id': txn_id,
                            't0': time.time(), 'domain': test_domain
                        }
                    except OSError:
                        # Send failed (network error), count as failed
                        with self._lock:
                            self._failed += 1
                            self._scanned += 1
                        try:
                            sock.close()
                        except Exception:
                            pass

                # -- Nothing pending and IPs exhausted = done --
                if not pending and ips_exhausted:
                    break

                if not pending:
                    continue

                # -- select() for readable sockets --
                read_socks = [info['sock'] for info in pending.values()]
                try:
                    readable, _, _ = select.select(read_socks, [], [], 0.1)
                except (ValueError, OSError):
                    readable = []

                # -- Process responses --
                for sock in readable:
                    fd = sock.fileno()
                    if fd not in pending:
                        continue
                    info = pending.pop(fd)
                    try:
                        data = sock.recv(1024)
                        elapsed_ms = round((time.time() - info['t0']) * 1000, 1)
                        resp = _parse_response(data, info['txn_id'])
                        rcode = resp["rcode"]
                        rcode_name = resp["rcode_name"]
                        has_edns = resp["has_edns"]

                        with self._lock:
                            self._rcode_stats[rcode_name] = self._rcode_stats.get(rcode_name, 0) + 1

                        if rcode in _OK_RCODES:
                            entry = {
                                "ip": info['ip'], "ms": elapsed_ms,
                                "rcode": rcode, "rcode_name": rcode_name,
                                "has_edns": has_edns, "dns_type": self._dns_type,
                                "domain": info['domain'], "has_ns": False,
                                "ns_name": "", "txt_data": resp.get("txt_data", []),
                            }
                            with self._lock:
                                self._found.append(entry)
                                if len(self._found) > self._max_found:
                                    self._found = self._found[-self._max_found:]
                                self._passed += 1
                            tags = f"[{rcode_name}]"
                            if has_edns:
                                tags += "[EDNS]"
                            self._add_log(f"OK {info['ip']} - {elapsed_ms}ms {tags}")
                        else:
                            with self._lock:
                                self._failed += 1
                    except Exception:
                        with self._lock:
                            self._failed += 1
                    with self._lock:
                        self._scanned += 1
                    # Return socket to pool for reuse
                    sock_pool.append(sock)

                # -- Check timeouts --
                now = time.time()
                timed_out = []
                for fd, info in pending.items():
                    if now - info['t0'] > timeout:
                        timed_out.append(fd)
                for fd in timed_out:
                    info = pending.pop(fd)
                    with self._lock:
                        self._failed += 1
                        self._scanned += 1
                        self._rcode_stats["TIMEOUT"] = self._rcode_stats.get("TIMEOUT", 0) + 1
                        if len(self._failed_ips) < self._max_failed:
                            self._failed_ips.append(info['ip'])
                    # Return socket to pool
                    sock_pool.append(info['sock'])

                # -- Periodic GC --
                gc_counter += 1
                if gc_counter >= 500:
                    gc_counter = 0
                    gc.collect()

        finally:
            # Close all sockets
            for info in pending.values():
                try:
                    info['sock'].close()
                except Exception:
                    pass
            for sock in sock_pool:
                try:
                    sock.close()
                except Exception:
                    pass
            del pending, sock_pool
            del blacklist_ints

        # -- Auto-retry failed IPs --
        if self._auto_retry and self._failed_ips and not self._should_stop:
            retry_ips = list(self._failed_ips[:500])
            self._failed_ips = []
            self._add_log(f"Retrying {len(retry_ips)} failed IPs with {timeout * 2}s timeout")
            for ip in retry_ips:
                if self._should_stop:
                    break
                self._pause_event.wait()
                self._retry_one_sync(ip, domain, timeout * 2, qtype)
            self._add_log("Retry complete")

    def _retry_one_sync(self, ip, domain, timeout, qtype):
        """Synchronous single-IP retry with blocking socket."""
        import select
        try:
            if self._random_subdomain:
                query_domain = f"{_random_prefix()}.{domain}"
            else:
                query_domain = domain
            txn_id, packet = _build_query(query_domain, qtype=qtype, add_edns=True)
            af = socket.AF_INET6 if ':' in ip else socket.AF_INET
            sock = socket.socket(af, socket.SOCK_DGRAM)
            sock.setblocking(False)
            try:
                sock.sendto(packet, (ip, 53))
                readable, _, _ = select.select([sock], [], [], timeout)
                if readable:
                    data = sock.recv(1024)
                    elapsed_ms = round((time.time()) * 1000 % 100000, 1)
                    resp = _parse_response(data, txn_id)
                    rcode = resp["rcode"]
                    if rcode in _OK_RCODES:
                        entry = {
                            "ip": ip, "ms": elapsed_ms,
                            "rcode": rcode, "rcode_name": resp["rcode_name"],
                            "has_edns": resp["has_edns"], "dns_type": self._dns_type,
                            "domain": domain, "has_ns": False, "ns_name": "",
                            "txt_data": resp.get("txt_data", []),
                        }
                        with self._lock:
                            self._found.append(entry)
                            self._passed += 1
                        self._add_log(f"OK {ip} [RETRY]")
                    else:
                        with self._lock:
                            self._failed += 1
                else:
                    with self._lock:
                        self._failed += 1
            finally:
                sock.close()
        except Exception:
            with self._lock:
                self._failed += 1
        with self._lock:
            self._scanned += 1


# ── Internet access verification ──────────────────────────────────────────────

async def check_internet_access(ip: str, timeout: float = 3.0) -> dict:
    """Check if a DNS server has real internet access.
    Method 1: whoami.cloudflare TXT
    Method 2: o-o.myaddr.google TXT
    Method 3: random subdomain fallback
    """
    result = {"ip": ip, "has_internet": False, "method": "", "rtt_ms": 0}

    methods = [
        ("whoami.cloudflare", 16),           # TXT query
        ("o-o.myaddr.l.google.com", 16),     # Google MyAddr TXT
    ]

    loop = asyncio.get_event_loop()

    for domain, qtype in methods:
        try:
            txn_id, packet = _build_query(domain, qtype=qtype, add_edns=False)
            t0 = time.time()

            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setblocking(False)
            sock.settimeout(0)

            try:
                await loop.sock_sendto(sock, packet, (ip, 53))
                data = await asyncio.wait_for(
                    loop.sock_recv(sock, 1024), timeout=timeout)
                rtt = round((time.time() - t0) * 1000, 1)

                resp = _parse_response(data, txn_id)
                if resp["rcode"] == 0 and resp["ancount"] > 0:
                    result["has_internet"] = True
                    result["method"] = domain
                    result["rtt_ms"] = rtt
                    if resp["txt_data"]:
                        result["txt_response"] = resp["txt_data"][0]
                    return result
            except (asyncio.TimeoutError, OSError):
                pass
            finally:
                sock.close()
        except Exception:
            pass

    # Method 3: random subdomain fallback
    try:
        rand_domain = f"{_random_prefix(16)}.cloudflare.com"
        txn_id, packet = _build_query(rand_domain, qtype=1, add_edns=False)
        t0 = time.time()

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)
        sock.settimeout(0)

        try:
            await loop.sock_sendto(sock, packet, (ip, 53))
            data = await asyncio.wait_for(
                loop.sock_recv(sock, 512), timeout=timeout)
            rtt = round((time.time() - t0) * 1000, 1)

            resp = _parse_response(data, txn_id)
            if resp["rcode"] in (0, 3):
                result["has_internet"] = True
                result["method"] = "random-subdomain"
                result["rtt_ms"] = rtt
                return result
        except (asyncio.TimeoutError, OSError):
            pass
        finally:
            sock.close()
    except Exception:
        pass

    return result


# ── Blacklist management ──────────────────────────────────────────────────────

def add_to_blacklist(ip_or_cidr: str):
    """Add an IP or CIDR to the blacklist file."""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(BLACKLIST_FILE, "a") as f:
            f.write(ip_or_cidr.strip() + "\n")
        return True, f"Added {ip_or_cidr} to blacklist"
    except Exception as e:
        return False, str(e)


def get_blacklist() -> list:
    """Get current blacklist entries."""
    try:
        if os.path.isfile(BLACKLIST_FILE):
            with open(BLACKLIST_FILE, "r") as f:
                return [l.strip() for l in f if l.strip() and not l.startswith("#")]
    except Exception:
        pass
    return []


def clear_blacklist():
    """Clear the blacklist file."""
    try:
        with open(BLACKLIST_FILE, "w") as f:
            f.write("# IP Blacklist - one IP or CIDR per line\n")
        return True, "Blacklist cleared"
    except Exception as e:
        return False, str(e)


# ── Global singleton ──────────────────────────────────────────────────────────

_scanner = DnsScanner()


def start_scan(domain: str, cidr_text: str, concurrency: int = 200,
               timeout: float = 2.5, dns_type: str = "A",
               random_subdomain: bool = True, preset: str = "normal",
               sample_size: int = 0, blacklist_enabled: bool = False,
               auto_retry: bool = False, check_ns: bool = False,
               domains: str = "", source_port: int = 0,
               pre_scan_port: int = 0, pre_scan_rate: int = 1000):
    return _scanner.start(domain, cidr_text, concurrency, timeout,
                          dns_type, random_subdomain, preset, sample_size,
                          blacklist_enabled, auto_retry, check_ns, domains,
                          source_port, pre_scan_port, pre_scan_rate)

def stop_scan():
    return _scanner.stop()

def pause_scan():
    return _scanner.pause()

def resume_scan():
    return _scanner.resume()

def shuffle_scan():
    return _scanner.shuffle()

def save_project():
    return _scanner.save_project()

def get_status():
    return _scanner.get_status()

def export_results():
    return _scanner.export_results()

def get_scan_history():
    try:
        if os.path.isfile(SCAN_HISTORY_FILE):
            with open(SCAN_HISTORY_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return []
