#!/usr/bin/env python3
"""Interactive AHV VLAN validation tool (procedural version).

Workflow:
1. Prompt for Prism Central and Windows guest credentials.
2. Validate CSV rows against Prism subnet inventory.
3. Print all discovered clusters and ask which clusters to test.
4. Find exactly one VM (by name) per selected cluster.
5. Enforce exactly one VM NIC (multi-NIC test VMs are blocked).
6. Rebind VM NIC to each target subnet, configure guest IP, migrate host-by-host.
7. Run two probes per host: guest-to-gateway and runner-to-guest.
8. Write CSV PASS/FAIL report.
"""

from __future__ import annotations

import argparse
import base64
import csv
import getpass
import json
import platform
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import paramiko
import requests

try:
    import winrm
except Exception:
    winrm = None

API_PATHS = {
    "clusters": "/api/clustermgmt/v4.0/config/clusters",
    "hosts": "/api/clustermgmt/v4.0/config/hosts",
    "subnets": "/api/networking/v4.0/config/subnets",
    "vms": "/api/vmm/v4.0/ahv/config/vms",
    "vm_get": "/api/vmm/v4.0/ahv/config/vms/{vm_extid}",
    "vm_nic_update": "/api/vmm/v4.0/ahv/config/vms/{vm_extid}/nics/{nic_extid}",
    "vm_migrate_action": "/api/vmm/v4.0/ahv/config/vms/{vm_extid}/$actions/migrate-to-host",
}

DEFAULT_SETTLE_SECONDS = 15
DEFAULT_PING_COUNT = 3
DEFAULT_API_TIMEOUT = 45
DEFAULT_SSH_TIMEOUT = 20
DEFAULT_MIGRATION_TIMEOUT = 300


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_stage(stage: str, message: str) -> None:
    print(f"[{now_utc()}] [{stage}] {message}")


def log_progress(stage: str, current: int, total: int, message: str, width: int = 24) -> None:
    if total <= 0:
        bar = "-" * width
        percent = 0
    else:
        current = max(0, min(current, total))
        filled = int(width * current / total)
        bar = "#" * filled + "-" * (width - filled)
        percent = int(100 * current / total)
    print(f"[{now_utc()}] [{stage}] [{bar}] {current}/{total} {percent:3d}% {message}")


def prompt_non_empty(text: str) -> str:
    while True:
        value = input(f"\t{text}").strip()
        if value:
            return value
        print("Value is required.")


def prompt_yes_no(text: str, default: bool) -> bool:
    default_txt = "Y/n" if default else "y/N"
    while True:
        raw = input(f"\t{text} [{default_txt}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Please answer yes or no.")


def prompt_prefix_length(text: str) -> int:
    while True:
        raw = input(f"\t{text}: ").strip()
        if not raw:
            print("Prefix length is required.")
            continue
        try:
            return parse_prefix_length(raw, 0)
        except RuntimeError:
            print("Please enter a CIDR prefix length from 1 to 32.")


def prompt_cluster_selection(clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not clusters:
        raise RuntimeError("No clusters were discovered in Prism Central")

    print("Discovered clusters:")
    for index, cluster in enumerate(clusters, start=1):
        name = cluster.get("name", "")
        extid = cluster.get("extId", "")
        print(f"  {index}. {name} ({extid})")

    while True:
        raw = input("\tSelect cluster numbers or names separated by comma, or * for all: ").strip()
        if not raw:
            print("Please select at least one cluster or use * for all.")
            continue
        if raw.lower() in {"*", "all"}:
            return clusters

        selected: List[Dict[str, Any]] = []
        seen: set[str] = set()
        errors: List[str] = []

        for token in [part.strip() for part in raw.split(",") if part.strip()]:
            cluster: Optional[Dict[str, Any]] = None
            if token.isdigit():
                index = int(token)
                if 1 <= index <= len(clusters):
                    cluster = clusters[index - 1]
                else:
                    errors.append(token)
                    continue
            else:
                matches = [c for c in clusters if c.get("name", "").lower() == token.lower()]
                if len(matches) == 1:
                    cluster = matches[0]
                elif len(matches) > 1:
                    errors.append(f"{token} (ambiguous)")
                    continue
                else:
                    errors.append(token)
                    continue

            key = cluster.get("extId") or cluster.get("name")
            if key and key not in seen:
                selected.append(cluster)
                seen.add(key)

        if not selected or errors:
            if errors:
                print("Invalid cluster selection: " + ", ".join(errors))
            else:
                print("Please select at least one cluster.")
            continue

        return selected


def init_session(pc_host: str, pc_user: str, pc_pass: str, verify_tls: bool) -> requests.Session:
    session = requests.Session()
    session.auth = (pc_user, pc_pass)
    session.verify = verify_tls
    if not verify_tls:
        requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]
    session.headers.update({"Content-Type": "application/json"})
    session.base_url = f"https://{pc_host}:9440"  # type: ignore[attr-defined]
    return session


def api_get(
    session: requests.Session, path: str, timeout: int, params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    res = session.get(f"{session.base_url}{path}", params=params, timeout=timeout)  # type: ignore[attr-defined]
    res.raise_for_status()
    return res.json()


def api_post(session: requests.Session, path: str, timeout: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    res = session.post(f"{session.base_url}{path}", json=payload, timeout=timeout)  # type: ignore[attr-defined]
    res.raise_for_status()
    return res.json() if res.text.strip() else {}


def api_put(session: requests.Session, path: str, timeout: int, payload: Dict[str, Any]) -> Dict[str, Any]:
    res = session.put(f"{session.base_url}{path}", json=payload, timeout=timeout)  # type: ignore[attr-defined]
    res.raise_for_status()
    return res.json() if res.text.strip() else {}


def list_all(
    session: requests.Session,
    path: str,
    timeout: int,
    limit: int = 100,
    label: Optional[str] = None,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    page = 0
    while True:
        payload = api_get(session, path, timeout, params={"$page": page, "$limit": limit})
        batch = payload.get("data", [])
        if not isinstance(batch, list):
            break
        rows.extend(batch)
        meta = payload.get("metadata", {})
        total = int(meta.get("totalAvailableResults", len(rows)))
        if label:
            log_progress("FETCH", len(rows), total, f"{label} page={page}")
        if len(rows) >= total or len(batch) < limit:
            break
        page += 1
    return rows


def get_vm(session: requests.Session, vm_extid: str, timeout: int) -> Dict[str, Any]:
    path = API_PATHS["vm_get"].format(vm_extid=vm_extid)
    return api_get(session, path, timeout).get("data", {})


def rebind_vm_nic_subnet(
    session: requests.Session,
    vm_extid: str,
    nic_extid: str,
    subnet_extid: str,
    timeout: int,
) -> None:
    vm = get_vm(session, vm_extid, timeout)
    nic = next((n for n in vm.get("nics", []) if n.get("extId") == nic_extid), None)
    if not nic:
        raise RuntimeError(f"NIC {nic_extid} not found on VM {vm_extid}")

    payload = json.loads(json.dumps(nic))
    for key in ["nicNetworkInfo", "networkInfo"]:
        payload.setdefault(key, {})
        payload[key]["nicType"] = "NORMAL_NIC"
        payload[key]["vlanMode"] = "ACCESS"
        payload[key]["subnet"] = {"extId": subnet_extid}

    path = API_PATHS["vm_nic_update"].format(vm_extid=vm_extid, nic_extid=nic_extid)
    api_put(session, path, timeout, payload)


def migrate_vm_to_host(session: requests.Session, vm_extid: str, host_extid: str, timeout: int) -> None:
    path = API_PATHS["vm_migrate_action"].format(vm_extid=vm_extid)
    api_post(session, path, timeout, {"host": {"extId": host_extid}})


def ssh_run(host: str, username: str, password: str, command: str, timeout: int) -> Dict[str, Any]:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        username=username,
        password=password,
        timeout=timeout,
        banner_timeout=timeout,
        auth_timeout=timeout,
    )
    try:
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        code = stdout.channel.recv_exit_status()
        return {
            "exit_code": code,
            "stdout": stdout.read().decode("utf-8", errors="replace"),
            "stderr": stderr.read().decode("utf-8", errors="replace"),
        }
    finally:
        client.close()


def ps_encoded(script: str) -> str:
    data = script.encode("utf-16le")
    return base64.b64encode(data).decode("ascii")


def run_windows_ps(host: str, username: str, password: str, script: str, timeout: int) -> Dict[str, Any]:
    errors: List[str] = []

    # Try SSH first for consistency with current behavior.
    try:
        encoded = ps_encoded(script)
        cmd = f"powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand {encoded}"
        result = ssh_run(host, username, password, cmd, timeout)
        result["transport"] = "ssh"
        return result
    except Exception as exc:
        errors.append(f"ssh: {exc}")

    # Fallback to WinRM if SSH is unavailable.
    if winrm is None:
        raise RuntimeError(
            "Windows guest command failed over SSH, and pywinrm is not installed for WinRM fallback"
        )

    try:
        endpoint = f"http://{host}:5985/wsman"
        session = winrm.Session(endpoint, auth=(username, password), transport="ntlm")
        response = session.run_ps(script)
        return {
            "exit_code": int(response.status_code),
            "stdout": response.std_out.decode("utf-8", errors="replace"),
            "stderr": response.std_err.decode("utf-8", errors="replace"),
            "transport": "winrm",
        }
    except Exception as exc:
        errors.append(f"winrm: {exc}")

    raise RuntimeError("Windows guest command failed over SSH and WinRM: " + " | ".join(errors))


def parse_subnet_csv(csv_path: str) -> List[Dict[str, str]]:
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"vlan_id", "subnet_extid", "free_ip", "gateway"}
        if not reader.fieldnames:
            raise RuntimeError("CSV has no header row")

        header = {h.strip() for h in reader.fieldnames if h}
        missing = required - header
        if missing:
            raise RuntimeError(f"CSV missing required columns: {', '.join(sorted(missing))}")

        rows: List[Dict[str, str]] = []
        for i, row in enumerate(reader, start=2):
            cleaned = {k.strip(): (v or "").strip() for k, v in row.items() if k}
            if not cleaned.get("subnet_extid"):
                raise RuntimeError(f"CSV line {i}: subnet_extid is required")
            if not cleaned.get("vlan_id"):
                raise RuntimeError(f"CSV line {i}: vlan_id is required")
            if not cleaned.get("free_ip"):
                raise RuntimeError(f"CSV line {i}: free_ip is required")
            if not cleaned.get("gateway"):
                raise RuntimeError(f"CSV line {i}: gateway is required")
            rows.append(cleaned)

        if not rows:
            raise RuntimeError("CSV has no data rows")
        return rows


def parse_prefix_length(value: str, row_num: int) -> int:
    try:
        prefix = int(value)
    except ValueError:
        raise RuntimeError(f"CSV row {row_num}: prefix_length must be an integer")
    if prefix < 1 or prefix > 32:
        raise RuntimeError(f"CSV row {row_num}: prefix_length must be between 1 and 32")
    return prefix


def subnet_mask_to_prefix_length(value: str, row_num: int) -> int:
    try:
        parts = [int(part) for part in value.split(".")]
    except ValueError:
        raise RuntimeError(f"CSV row {row_num}: subnet_mask must contain numeric octets")
    if len(parts) != 4 or any(part < 0 or part > 255 for part in parts):
        raise RuntimeError(f"CSV row {row_num}: subnet_mask must be a valid IPv4 mask")

    bits = "".join(f"{part:08b}" for part in parts)
    if "01" in bits:
        raise RuntimeError(f"CSV row {row_num}: subnet_mask must be contiguous")
    return bits.count("1")


def csv_prefix_length(row: Dict[str, str], row_num: int, default_prefix_length: int) -> int:
    prefix_length = row.get("prefix_length", "")
    if prefix_length:
        return parse_prefix_length(prefix_length, row_num)

    subnet_mask = row.get("subnet_mask", "")
    if subnet_mask:
        return subnet_mask_to_prefix_length(subnet_mask, row_num)

    return default_prefix_length


def build_subnet_tests(
    csv_rows: List[Dict[str, str]],
    subnets: List[Dict[str, Any]],
    default_prefix_length: int,
) -> List[Dict[str, Any]]:
    by_extid = {s.get("extId"): s for s in subnets if s.get("extId")}
    tests: List[Dict[str, Any]] = []
    errors: List[str] = []

    for idx, row in enumerate(csv_rows, start=1):
        subnet_extid = row["subnet_extid"]
        expected_vlan = str(row["vlan_id"])
        free_ip = row["free_ip"]

        subnet = by_extid.get(subnet_extid)
        if not subnet:
            errors.append(f"Row {idx}: subnet_extid {subnet_extid} not found in Prism inventory")
            continue

        actual_vlan = str(subnet.get("networkId", ""))
        if expected_vlan != actual_vlan:
            errors.append(
                f"Row {idx}: subnet_extid {subnet_extid} VLAN mismatch. CSV={expected_vlan}, Prism={actual_vlan}"
            )
            continue

        prefix = 0
        gateway = ""
        ip_cfg_list = subnet.get("ipConfig", [])
        if not ip_cfg_list:
            gateway = row.get("gateway", "")
            if not gateway:
                errors.append(
                    f"Row {idx}: subnet_extid {subnet_extid} has no Prism ipConfig; "
                    "CSV gateway is required"
                )
                continue
            try:
                prefix = csv_prefix_length(row, idx, default_prefix_length)
            except RuntimeError as exc:
                errors.append(str(exc))
                continue
        else:
            ipv4 = ip_cfg_list[0].get("ipv4", {})
            prefix = ipv4.get("ipSubnet", {}).get("prefixLength")
            gateway = ipv4.get("defaultGatewayIp", {}).get("value")
            if prefix is None or not gateway:
                csv_gateway = row.get("gateway", "")
                csv_prefix = row.get("prefix_length", "")
                if not csv_gateway or not csv_prefix:
                    errors.append(f"Row {idx}: subnet_extid {subnet_extid} missing prefix or default gateway")
                    continue
                gateway = csv_gateway
                try:
                    prefix = csv_prefix_length(row, idx, default_prefix_length)
                except RuntimeError as exc:
                    errors.append(str(exc))
                    continue

        cluster_extids: List[str] = []
        for extid in subnet.get("clusterReferenceList", []) or []:
            if extid and extid not in cluster_extids:
                cluster_extids.append(extid)
        single_cluster = subnet.get("clusterReference")
        if single_cluster and single_cluster not in cluster_extids:
            cluster_extids.append(single_cluster)

        tests.append(
            {
                "vlan_id": int(actual_vlan),
                "subnet_extid": subnet_extid,
                "subnet_name": subnet.get("name", ""),
                "prefix": int(prefix),
                "gateway": gateway,
                "free_ip": free_ip,
                "cluster_extids": cluster_extids,
            }
        )

    if errors:
        raise RuntimeError("Validation failed:\n- " + "\n- ".join(errors))

    return tests


def detect_guest_interface(host: str, user: str, password: str, timeout: int) -> str:
    ps_script = (
        "$r = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' "
        "| Sort-Object RouteMetric "
        "| Select-Object -First 1 -ExpandProperty InterfaceAlias; "
        "if (-not $r) { Write-Error 'Default route not found'; exit 2 }; "
        "Write-Output $r"
    )
    res = run_windows_ps(host, user, password, ps_script, timeout)
    lines = [ln.strip() for ln in res["stdout"].splitlines() if ln.strip()]
    name = lines[0] if lines else ""
    if res["exit_code"] != 0 or not name:
        raise RuntimeError(res["stderr"] or res["stdout"] or "Failed to detect Windows interface")
    return name


def configure_guest_ip(
    host: str,
    user: str,
    password: str,
    timeout: int,
    iface: str,
    ip_addr: str,
    prefix: int,
    gateway: str,
) -> Dict[str, Any]:
    safe_iface = iface.replace("'", "''")
    ps_script = (
        f"$if='{safe_iface}'; "
        f"$ip='{ip_addr}'; "
        f"$gw='{gateway}'; "
        f"$p={prefix}; "
        "Get-NetIPAddress -InterfaceAlias $if -AddressFamily IPv4 -ErrorAction SilentlyContinue "
        "| Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue; "
        "Get-NetRoute -InterfaceAlias $if -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue "
        "| Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue; "
        "New-NetIPAddress -InterfaceAlias $if -IPAddress $ip -PrefixLength $p -DefaultGateway $gw -AddressFamily IPv4 -ErrorAction Stop | Out-Null"
    )
    return run_windows_ps(host, user, password, ps_script, timeout)


def ping_gateway(
    host: str,
    user: str,
    password: str,
    timeout: int,
    gateway: str,
    ping_count: int,
) -> Dict[str, Any]:
    ps_script = (
        f"if (Test-Connection -ComputerName '{gateway}' -Count {ping_count} -Quiet) {{ "
        "Write-Output 'PASS'; exit 0 "
        "} else { Write-Output 'FAIL'; exit 1 }"
    )
    return run_windows_ps(host, user, password, ps_script, timeout)


def ping_guest_from_runner(target_ip: str, ping_count: int) -> Dict[str, Any]:
    if platform.system().lower().startswith("win"):
        cmd = ["ping", "-n", str(ping_count), "-w", "2000", target_ip]
    else:
        cmd = ["ping", "-c", str(ping_count), "-W", "2", target_ip]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(10, ping_count * 3),
            check=False,
        )
        return {
            "exit_code": int(result.returncode),
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except Exception as exc:
        return {
            "exit_code": 1,
            "stdout": "",
            "stderr": str(exc),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive AHV VLAN validator")
    parser.add_argument("--dry-run", action="store_true", help="Only validate/discover, no changes")
    parser.add_argument("--preflight-only", action="store_true", help="Validate and print plan only")
    parser.add_argument(
        "--confirm-vm-per-cluster",
        action="store_true",
        help="Require manual YES confirmation before each cluster",
    )
    args = parser.parse_args()

    log_stage("START", "AHV VLAN Validator (Interactive)")
    pc_host = prompt_non_empty("Prism Central IP/FQDN: ")
    pc_user = prompt_non_empty("Prism Username: ")
    pc_pass = getpass.getpass("\tPrism Password: ")
    vm_name = prompt_non_empty("Windows Test VM Name (same name across clusters): ")
    guest_user = prompt_non_empty("Windows Guest Username: ")
    guest_pass = getpass.getpass("\tWindows Guest Password: ")
    csv_path = prompt_non_empty("Path to subnet CSV (vlan_id,subnet_extid,free_ip,gateway): ")
    report_path = input("\tReport CSV path [vlan_test_report.csv]: ").strip() or "vlan_test_report.csv"
    default_prefix_length = prompt_prefix_length("Default CIDR prefix length")
    verify_tls = prompt_yes_no("Verify TLS certificates", default=False)

    settle_seconds = DEFAULT_SETTLE_SECONDS
    ping_count = DEFAULT_PING_COUNT
    api_timeout = DEFAULT_API_TIMEOUT
    ssh_timeout = DEFAULT_SSH_TIMEOUT
    migration_timeout = DEFAULT_MIGRATION_TIMEOUT

    run_id = str(uuid.uuid4())
    session = init_session(pc_host, pc_user, pc_pass, verify_tls)

    log_stage("INVENTORY", "Fetching clusters, hosts, subnets, and VMs from Prism Central")
    clusters = list_all(session, API_PATHS["clusters"], api_timeout, label="clusters")
    hosts = list_all(session, API_PATHS["hosts"], api_timeout, label="hosts")
    subnets = list_all(session, API_PATHS["subnets"], api_timeout, label="subnets")
    vms = list_all(session, API_PATHS["vms"], api_timeout, label="vms")
    log_stage(
        "INVENTORY",
        f"Fetched clusters={len(clusters)} hosts={len(hosts)} subnets={len(subnets)} vms={len(vms)}",
    )

    log_stage("VALIDATION", f"Reading subnet CSV: {csv_path}")
    csv_rows = parse_subnet_csv(csv_path)
    log_stage("VALIDATION", f"Loaded {len(csv_rows)} CSV subnet rows")
    subnet_tests = build_subnet_tests(csv_rows, subnets, default_prefix_length)
    log_stage("VALIDATION", f"Validated {len(subnet_tests)} subnet rows against Prism inventory")

    selected_clusters = prompt_cluster_selection(clusters)
    print("Selected clusters:")
    for cluster in selected_clusters:
        print(f"  - {cluster.get('name', '')} ({cluster.get('extId', '')})")

    hosts_by_cluster: Dict[str, List[Dict[str, Any]]] = {}
    for host in hosts:
        cluster_id = host.get("cluster", {}).get("uuid")
        if cluster_id:
            hosts_by_cluster.setdefault(cluster_id, []).append(host)

    report_rows: List[Dict[str, Any]] = []

    def record(row: Dict[str, Any]) -> None:
        row["timestamp_utc"] = now_utc()
        row["run_id"] = run_id
        report_rows.append(row)

    log_stage("PLAN", f"Run ID: {run_id}")
    log_stage("PLAN", f"Default prefix length for rows without mask override: /{default_prefix_length}")
    log_stage("PLAN", f"Planned clusters: {len(selected_clusters)} of {len(clusters)} discovered")
    log_stage("PLAN", f"Planned subnet rows: {len(subnet_tests)}")
    for test in subnet_tests:
        log_stage(
            "PLAN",
            f"subnet={test['subnet_name']} vlan={test['vlan_id']} "
            f"extId={test['subnet_extid']} ip={test['free_ip']} gw={test['gateway']}/{test['prefix']}",
        )

    if args.preflight_only:
        log_stage("PREFLIGHT", "Preflight only selected. No changes will be made.")
        out = Path(report_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "timestamp_utc",
            "run_id",
            "cluster",
            "host",
            "test_vm",
            "vlan_id",
            "subnet",
            "subnet_extid",
            "test_ip",
            "gateway",
            "status",
            "stage",
            "detail",
        ]
        with out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
        log_stage("REPORT", f"Wrote report skeleton: {out}")
        return 0

    if not args.dry_run and input("\tType YES to execute this plan: ").strip() != "YES":
        log_stage("CANCELLED", "Execution cancelled by user.")
        return 0

    for cluster_index, cluster in enumerate(selected_clusters, start=1):
        cluster_name = cluster.get("name", "")
        cluster_extid = cluster.get("extId", "")
        log_progress("CLUSTERS", cluster_index, len(selected_clusters), f"cluster={cluster_name or '<unnamed>'}")
        if not cluster_extid:
            log_stage("CLUSTER", f"Skipping cluster with missing extId: {cluster_name}")
            continue

        cluster_hosts = hosts_by_cluster.get(cluster_extid, [])
        if not cluster_hosts:
            log_stage("CLUSTER", f"Skipping {cluster_name}: no hosts discovered")
            continue

        log_stage("CLUSTER", f"Starting cluster {cluster_name} with {len(cluster_hosts)} hosts")

        vm_matches = [
            vm
            for vm in vms
            if vm.get("name") == vm_name and vm.get("cluster", {}).get("extId") == cluster_extid
        ]

        if len(vm_matches) != 1:
            log_stage("VM", f"{cluster_name}: expected one VM named {vm_name}, found {len(vm_matches)}")
            record(
                {
                    "cluster": cluster_name,
                    "host": "",
                    "test_vm": vm_name,
                    "vlan_id": "",
                    "subnet": "",
                    "subnet_extid": "",
                    "test_ip": "",
                    "gateway": "",
                    "status": "FAIL",
                    "stage": "vm_targeting",
                    "detail": f"Expected 1 VM named {vm_name}, found {len(vm_matches)}",
                }
            )
            continue

        vm_extid = vm_matches[0].get("extId", "")
        log_stage("VM", f"{cluster_name}: matched test VM {vm_name} ({vm_extid})")
        vm_full = get_vm(session, vm_extid, api_timeout)
        vm_nics = vm_full.get("nics", [])

        # Keep behavior deterministic and simple for operators.
        if len(vm_nics) != 1:
            record(
                {
                    "cluster": cluster_name,
                    "host": "",
                    "test_vm": vm_name,
                    "vlan_id": "",
                    "subnet": "",
                    "subnet_extid": "",
                    "test_ip": "",
                    "gateway": "",
                    "status": "FAIL",
                    "stage": "vm_nic_count",
                    "detail": f"Test VM must have exactly 1 NIC; found {len(vm_nics)}",
                }
            )
            log_stage("VM", f"Skipping {cluster_name}: VM has {len(vm_nics)} NICs; exactly one is required")
            continue

        nic_extid = vm_nics[0].get("extId", "")
        log_stage("VM", f"{cluster_name}: using VM NIC {nic_extid}")

        if args.confirm_vm_per_cluster:
            print(
                f"[{now_utc()}] Confirm cluster execution:\n"
                f"  Cluster: {cluster_name}\n"
                f"  Test VM: {vm_name}\n"
                f"  Test VM extId: {vm_extid}\n"
                f"  Test NIC extId: {nic_extid}\n"
                "  Guest OS: Windows"
            )
            if input("\tType YES to continue this cluster: ").strip() != "YES":
                record(
                    {
                        "cluster": cluster_name,
                        "host": "",
                        "test_vm": vm_name,
                        "vlan_id": "",
                        "subnet": "",
                        "subnet_extid": "",
                        "test_ip": "",
                        "gateway": "",
                        "status": "FAIL",
                        "stage": "operator_confirmation",
                        "detail": "Cluster execution cancelled by user",
                    }
                )
                continue

        log_stage("CLUSTER", f"{cluster_name}: processing {len(subnet_tests)} subnet rows")

        for subnet_index, test in enumerate(subnet_tests, start=1):
            log_progress(
                "SUBNETS",
                subnet_index,
                len(subnet_tests),
                f"cluster={cluster_name} vlan={test['vlan_id']} subnet={test['subnet_name']}",
            )
            log_stage(
                "SUBNET",
                f"{cluster_name}: vlan={test['vlan_id']} subnet={test['subnet_name']} extId={test['subnet_extid']}",
            )
            if test["cluster_extids"] and cluster_extid not in test["cluster_extids"]:
                log_stage("SUBNET", f"{cluster_name}: subnet is outside cluster scope; recording failure")
                record(
                    {
                        "cluster": cluster_name,
                        "host": "",
                        "test_vm": vm_name,
                        "vlan_id": test["vlan_id"],
                        "subnet": test["subnet_name"],
                        "subnet_extid": test["subnet_extid"],
                        "test_ip": test["free_ip"],
                        "gateway": test["gateway"],
                        "status": "FAIL",
                        "stage": "subnet_cluster_scope",
                        "detail": "Subnet is not associated with this cluster in Prism references",
                    }
                )
                continue

            if args.dry_run:
                log_stage("DRY_RUN", f"{cluster_name}: planned only; no VM, NIC, guest, or migration actions executed")
                record(
                    {
                        "cluster": cluster_name,
                        "host": "",
                        "test_vm": vm_name,
                        "vlan_id": test["vlan_id"],
                        "subnet": test["subnet_name"],
                        "subnet_extid": test["subnet_extid"],
                        "test_ip": test["free_ip"],
                        "gateway": test["gateway"],
                        "status": "DRY_RUN",
                        "stage": "planned",
                        "detail": "No actions executed",
                    }
                )
                continue

            try:
                log_stage("NIC", f"{cluster_name}: rebinding test VM NIC to subnet {test['subnet_extid']}")
                rebind_vm_nic_subnet(session, vm_extid, nic_extid, test["subnet_extid"], api_timeout)
                time.sleep(settle_seconds)

                log_stage("GUEST", f"{cluster_name}: detecting Windows guest interface using {test['free_ip']}")
                iface = detect_guest_interface(test["free_ip"], guest_user, guest_pass, ssh_timeout)
                log_stage("GUEST", f"{cluster_name}: configuring {iface} with {test['free_ip']}/{test['prefix']}")
                cfg_res = configure_guest_ip(
                    test["free_ip"],
                    guest_user,
                    guest_pass,
                    ssh_timeout,
                    iface,
                    test["free_ip"],
                    test["prefix"],
                    test["gateway"],
                )
                if cfg_res["exit_code"] != 0:
                    raise RuntimeError(cfg_res["stderr"] or cfg_res["stdout"] or "Guest IP config failed")
            except Exception as exc:
                log_stage("GUEST", f"{cluster_name}: guest preparation failed: {exc}")
                record(
                    {
                        "cluster": cluster_name,
                        "host": "",
                        "test_vm": vm_name,
                        "vlan_id": test["vlan_id"],
                        "subnet": test["subnet_name"],
                        "subnet_extid": test["subnet_extid"],
                        "test_ip": test["free_ip"],
                        "gateway": test["gateway"],
                        "status": "FAIL",
                        "stage": "guest_prep",
                        "detail": str(exc),
                    }
                )
                continue

            for host_index, host in enumerate(cluster_hosts, start=1):
                host_name = host.get("hostName", "")
                host_extid = host.get("extId", "")
                log_progress(
                    "HOSTS",
                    host_index,
                    len(cluster_hosts),
                    f"cluster={cluster_name} host={host_name or host_extid}",
                )
                log_stage("HOST", f"{cluster_name}: testing host {host_name} ({host_extid})")

                try:
                    log_stage("MIGRATE", f"{cluster_name}: migrating test VM to host {host_name}")
                    migrate_vm_to_host(session, vm_extid, host_extid, api_timeout)

                    start = time.time()
                    placed = False
                    while time.time() - start < migration_timeout:
                        vm_state = get_vm(session, vm_extid, api_timeout)
                        cur_host = vm_state.get("host", {}).get("extId")
                        if cur_host == host_extid:
                            placed = True
                            break
                        time.sleep(5)

                    if not placed:
                        raise RuntimeError("Timed out waiting for host placement")

                    log_stage("MIGRATE", f"{cluster_name}: VM placement confirmed on {host_name}")
                    time.sleep(settle_seconds)
                    log_stage("PROBE", f"{cluster_name}: pinging gateway {test['gateway']} from guest")
                    ping_res = ping_gateway(
                        test["free_ip"],
                        guest_user,
                        guest_pass,
                        ssh_timeout,
                        test["gateway"],
                        ping_count,
                    )

                    log_stage("PROBE", f"{cluster_name}: pinging guest test IP {test['free_ip']} from runner")
                    runner_ping = ping_guest_from_runner(test["free_ip"], ping_count)

                    guest_ok = ping_res["exit_code"] == 0
                    runner_ok = runner_ping["exit_code"] == 0
                    ok = guest_ok and runner_ok
                    log_stage(
                        "RESULT",
                        f"{cluster_name}/{host_name}: {'PASS' if ok else 'FAIL'} "
                        f"guest_gateway={'PASS' if guest_ok else 'FAIL'} runner_to_guest={'PASS' if runner_ok else 'FAIL'}",
                    )

                    guest_detail = (ping_res["stderr"] or ping_res["stdout"]).strip()
                    runner_detail = (runner_ping["stderr"] or runner_ping["stdout"]).strip()
                    detail = (
                        f"guest_gateway_ping={'PASS' if guest_ok else 'FAIL'}; "
                        f"runner_to_guest_ping={'PASS' if runner_ok else 'FAIL'}; "
                        f"guest_output={guest_detail}; runner_output={runner_detail}"
                    )
                    record(
                        {
                            "cluster": cluster_name,
                            "host": host_name,
                            "test_vm": vm_name,
                            "vlan_id": test["vlan_id"],
                            "subnet": test["subnet_name"],
                            "subnet_extid": test["subnet_extid"],
                            "test_ip": test["free_ip"],
                            "gateway": test["gateway"],
                            "status": "PASS" if ok else "FAIL",
                            "stage": "icmp_probe",
                            "detail": detail,
                        }
                    )
                except Exception as exc:
                    log_stage("ERROR", f"{cluster_name}/{host_name}: runtime failure: {exc}")
                    record(
                        {
                            "cluster": cluster_name,
                            "host": host_name,
                            "test_vm": vm_name,
                            "vlan_id": test["vlan_id"],
                            "subnet": test["subnet_name"],
                            "subnet_extid": test["subnet_extid"],
                            "test_ip": test["free_ip"],
                            "gateway": test["gateway"],
                            "status": "FAIL",
                            "stage": "runtime",
                            "detail": str(exc),
                        }
                    )

    out = Path(report_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "timestamp_utc",
        "run_id",
        "cluster",
        "host",
        "test_vm",
        "vlan_id",
        "subnet",
        "subnet_extid",
        "test_ip",
        "gateway",
        "status",
        "stage",
        "detail",
    ]
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in report_rows:
            writer.writerow(row)

    failures = sum(1 for row in report_rows if row.get("status") == "FAIL")
    log_stage("REPORT", f"Wrote report: {out}")
    log_stage("DONE", f"Completed. Rows={len(report_rows)} Failures={failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
