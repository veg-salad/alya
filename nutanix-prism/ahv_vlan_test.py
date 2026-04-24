#!/usr/bin/env python3
"""Interactive Prism Element AHV VLAN validation tool.

Workflow:
1. Prompt for shared credentials and CSV/report settings.
2. Prompt for one Prism Element endpoint at a time.
3. Fetch local cluster, hosts, networks, and VMs from Prism Element.
4. Validate CSV rows against the local Element network inventory.
5. Find exactly one local Windows test VM and enforce exactly one NIC.
6. Rebind VM NIC to each target network, configure guest IP, migrate host-by-host.
7. Run two probes per host: guest-to-gateway and runner-to-guest.
8. Keep each Element run in memory and write one combined CSV report at the end.
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
    "cluster": "/cluster/",
    "hosts": "/hosts/",
    "networks": "/networks/",
    "vms": "/vms/",
    "vm_get": "/vms/{vm_uuid}/",
    "vm_nics": "/vms/{vm_uuid}/nics/",
    "vm_nic_update": "/vms/{vm_uuid}/nics/{nic_uuid}",
    "vm_migrate": "/vms/{vm_uuid}/migrate",
    "task_get": "/tasks/{task_uuid}",
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


def init_session(element_host: str, element_user: str, element_pass: str, verify_tls: bool) -> requests.Session:
    session = requests.Session()
    session.auth = (element_user, element_pass)
    session.verify = verify_tls
    if not verify_tls:
        requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]
    session.headers.update({"Content-Type": "application/json"})
    session.base_url = f"https://{element_host}:9440/PrismGateway/services/rest/v2.0"  # type: ignore[attr-defined]
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


def list_entities(
    session: requests.Session,
    path: str,
    timeout: int,
    limit: int = 100,
    label: Optional[str] = None,
    extra_params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    offset = 0
    while True:
        params = {"count": limit, "offset": offset}
        if extra_params:
            params.update(extra_params)
        payload = api_get(session, path, timeout, params=params)
        batch = payload.get("entities", [])
        if not isinstance(batch, list):
            break
        rows.extend(batch)
        meta = payload.get("metadata", {})
        total = int(meta.get("total_entities", meta.get("totalEntities", len(rows))))
        if label:
            log_progress("FETCH", len(rows), total, f"{label} offset={offset}")
        if len(rows) >= total or len(batch) < limit:
            break
        offset += limit
    return rows


def task_uuid(payload: Dict[str, Any]) -> str:
    return payload.get("task_uuid") or payload.get("uuid") or ""


def wait_task(session: requests.Session, task_id: str, timeout: int) -> None:
    if not task_id:
        return
    start = time.time()
    path = API_PATHS["task_get"].format(task_uuid=task_id)
    while time.time() - start < timeout:
        task = api_get(session, path, DEFAULT_API_TIMEOUT)
        status = str(task.get("progress_status") or task.get("status") or "").lower()
        if status in {"succeeded", "success", "completed"}:
            return
        if status in {"failed", "failure", "aborted"}:
            raise RuntimeError(task.get("message") or f"Task {task_id} failed with status {status}")
        time.sleep(5)
    raise RuntimeError(f"Timed out waiting for task {task_id}")


def get_vm(session: requests.Session, vm_uuid: str, timeout: int) -> Dict[str, Any]:
    path = API_PATHS["vm_get"].format(vm_uuid=vm_uuid)
    return api_get(session, path, timeout, params={"include_vm_nic_config": "true"})


def get_vm_nics(session: requests.Session, vm_uuid: str, timeout: int) -> List[Dict[str, Any]]:
    vm = get_vm(session, vm_uuid, timeout)
    nics = vm.get("vm_nics")
    if isinstance(nics, list):
        return nics
    path = API_PATHS["vm_nics"].format(vm_uuid=vm_uuid)
    payload = api_get(session, path, timeout)
    return payload.get("entities", []) if isinstance(payload.get("entities"), list) else []


def rebind_vm_nic_subnet(
    session: requests.Session,
    vm_uuid: str,
    nic_uuid: str,
    network_uuid: str,
    timeout: int,
) -> None:
    nic = next((n for n in get_vm_nics(session, vm_uuid, timeout) if n.get("nic_uuid") == nic_uuid), None)
    if not nic:
        raise RuntimeError(f"NIC {nic_uuid} not found on VM {vm_uuid}")

    payload = json.loads(json.dumps(nic))
    payload["network_uuid"] = network_uuid
    payload["is_connected"] = True

    path = API_PATHS["vm_nic_update"].format(vm_uuid=vm_uuid, nic_uuid=nic_uuid)
    wait_task(session, task_uuid(api_put(session, path, timeout, payload)), timeout)


def migrate_vm_to_host(session: requests.Session, vm_uuid: str, host_uuid: str, timeout: int) -> None:
    path = API_PATHS["vm_migrate"].format(vm_uuid=vm_uuid)
    wait_task(session, task_uuid(api_post(session, path, DEFAULT_API_TIMEOUT, {"host_uuid": host_uuid})), timeout)


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


def build_network_tests(
    csv_rows: List[Dict[str, str]],
    networks: List[Dict[str, Any]],
    default_prefix_length: int,
) -> List[Dict[str, Any]]:
    by_uuid = {n.get("uuid"): n for n in networks if n.get("uuid")}
    tests: List[Dict[str, Any]] = []
    errors: List[str] = []

    for idx, row in enumerate(csv_rows, start=1):
        network_uuid = row["subnet_extid"]
        expected_vlan = str(row["vlan_id"])
        free_ip = row["free_ip"]

        network = by_uuid.get(network_uuid)
        if not network:
            errors.append(f"Row {idx}: subnet_extid {network_uuid} not found in Prism Element network inventory")
            continue

        actual_vlan = str(network.get("vlan_id", ""))
        if expected_vlan != actual_vlan:
            errors.append(
                f"Row {idx}: subnet_extid {network_uuid} VLAN mismatch. CSV={expected_vlan}, Prism Element={actual_vlan}"
            )
            continue

        gateway = row.get("gateway", "")
        if not gateway:
            errors.append(f"Row {idx}: gateway is required")
            continue
        try:
            prefix = csv_prefix_length(row, idx, default_prefix_length)
        except RuntimeError as exc:
            errors.append(str(exc))
            continue

        tests.append(
            {
                "vlan_id": int(actual_vlan),
                "subnet_extid": network_uuid,
                "subnet_name": network.get("name", ""),
                "prefix": int(prefix),
                "gateway": gateway,
                "free_ip": free_ip,
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
    parser = argparse.ArgumentParser(description="Interactive Prism Element AHV VLAN validator")
    parser.add_argument("--dry-run", action="store_true", help="Only validate/discover, no changes")
    parser.add_argument("--preflight-only", action="store_true", help="Validate and print plan only")
    parser.add_argument(
        "--confirm-vm-per-element",
        action="store_true",
        help="Require manual YES confirmation before each Element run",
    )
    args = parser.parse_args()

    log_stage("START", "AHV VLAN Validator (Interactive)")
    element_user = prompt_non_empty("Prism Element Username: ")
    element_pass = getpass.getpass("\tPrism Element Password: ")
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

    log_stage("VALIDATION", f"Reading subnet CSV: {csv_path}")
    csv_rows = parse_subnet_csv(csv_path)
    log_stage("VALIDATION", f"Loaded {len(csv_rows)} CSV subnet rows")

    report_rows: List[Dict[str, Any]] = []

    def record(row: Dict[str, Any], element_host: str, cluster: Dict[str, Any]) -> None:
        row["timestamp_utc"] = now_utc()
        row["run_id"] = run_id
        row["element"] = element_host
        row["cluster_uuid"] = cluster.get("uuid") or cluster.get("cluster_uuid") or ""
        report_rows.append(row)

    log_stage("PLAN", f"Run ID: {run_id}")
    log_stage("PLAN", f"Default prefix length for rows without mask override: /{default_prefix_length}")
    while True:
        element_host = prompt_non_empty("Prism Element IP/FQDN: ")
        session = init_session(element_host, element_user, element_pass, verify_tls)

        log_stage("INVENTORY", f"{element_host}: fetching local cluster, hosts, networks, and VMs")
        cluster = api_get(session, API_PATHS["cluster"], api_timeout)
        cluster_name = cluster.get("name", element_host)
        hosts = list_entities(session, API_PATHS["hosts"], api_timeout, label="hosts")
        networks = list_entities(session, API_PATHS["networks"], api_timeout, label="networks")
        vms = list_entities(
            session,
            API_PATHS["vms"],
            api_timeout,
            label="vms",
            extra_params={"include_vm_nic_config": "true"},
        )
        log_stage(
            "INVENTORY",
            f"{cluster_name}: fetched hosts={len(hosts)} networks={len(networks)} vms={len(vms)}",
        )

        subnet_tests = build_network_tests(csv_rows, networks, default_prefix_length)
        log_stage("VALIDATION", f"{cluster_name}: validated {len(subnet_tests)} CSV rows against Element networks")
        for test in subnet_tests:
            log_stage(
                "PLAN",
                f"{cluster_name}: subnet={test['subnet_name']} vlan={test['vlan_id']} "
                f"uuid={test['subnet_extid']} ip={test['free_ip']} gw={test['gateway']}/{test['prefix']}",
            )

        vm_matches = [vm for vm in vms if vm.get("name") == vm_name]
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
                },
                element_host,
                cluster,
            )
            if not prompt_yes_no("Process another Prism Element", default=False):
                break
            continue

        vm_uuid = vm_matches[0].get("uuid", "")
        log_stage("VM", f"{cluster_name}: matched test VM {vm_name} ({vm_uuid})")
        vm_nics = get_vm_nics(session, vm_uuid, api_timeout)

        if len(vm_nics) != 1:
            log_stage("VM", f"Skipping {cluster_name}: VM has {len(vm_nics)} NICs; exactly one is required")
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
                },
                element_host,
                cluster,
            )
            if not prompt_yes_no("Process another Prism Element", default=False):
                break
            continue

        nic_uuid = vm_nics[0].get("nic_uuid", "")
        log_stage("VM", f"{cluster_name}: using VM NIC {nic_uuid}")

        if args.confirm_vm_per_element:
            print(
                f"[{now_utc()}] Confirm Element execution:\n"
                f"  Element: {element_host}\n"
                f"  Cluster: {cluster_name}\n"
                f"  Test VM: {vm_name}\n"
                f"  Test VM UUID: {vm_uuid}\n"
                f"  Test NIC UUID: {nic_uuid}\n"
                "  Guest OS: Windows"
            )
            if input("\tType YES to continue this Element: ").strip() != "YES":
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
                        "detail": "Element execution cancelled by user",
                    },
                    element_host,
                    cluster,
                )
                if not prompt_yes_no("Process another Prism Element", default=False):
                    break
                continue

        if not args.dry_run and not args.preflight_only:
            if input(f"\tType YES to execute this Element plan for {cluster_name}: ").strip() != "YES":
                log_stage("CANCELLED", f"{cluster_name}: execution cancelled by user")
                if not prompt_yes_no("Process another Prism Element", default=False):
                    break
                continue

        for subnet_index, test in enumerate(subnet_tests, start=1):
            log_progress(
                "SUBNETS",
                subnet_index,
                len(subnet_tests),
                f"cluster={cluster_name} vlan={test['vlan_id']} subnet={test['subnet_name']}",
            )

            if args.dry_run or args.preflight_only:
                status = "PREFLIGHT" if args.preflight_only else "DRY_RUN"
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
                        "status": status,
                        "stage": "planned",
                        "detail": "No actions executed",
                    },
                    element_host,
                    cluster,
                )
                continue

            try:
                log_stage("NIC", f"{cluster_name}: rebinding test VM NIC to network {test['subnet_extid']}")
                rebind_vm_nic_subnet(session, vm_uuid, nic_uuid, test["subnet_extid"], api_timeout)
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
                    },
                    element_host,
                    cluster,
                )
                continue

            for host_index, host in enumerate(hosts, start=1):
                host_name = host.get("name", "")
                host_uuid = host.get("uuid", "")
                log_progress("HOSTS", host_index, len(hosts), f"cluster={cluster_name} host={host_name or host_uuid}")
                try:
                    log_stage("MIGRATE", f"{cluster_name}: migrating test VM to host {host_name}")
                    migrate_vm_to_host(session, vm_uuid, host_uuid, migration_timeout)
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
                    guest_detail = (ping_res["stderr"] or ping_res["stdout"]).strip()
                    runner_detail = (runner_ping["stderr"] or runner_ping["stdout"]).strip()
                    detail = (
                        f"guest_gateway_ping={'PASS' if guest_ok else 'FAIL'}; "
                        f"runner_to_guest_ping={'PASS' if runner_ok else 'FAIL'}; "
                        f"guest_output={guest_detail}; runner_output={runner_detail}"
                    )
                    log_stage(
                        "RESULT",
                        f"{cluster_name}/{host_name}: {'PASS' if ok else 'FAIL'} "
                        f"guest_gateway={'PASS' if guest_ok else 'FAIL'} runner_to_guest={'PASS' if runner_ok else 'FAIL'}",
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
                        },
                        element_host,
                        cluster,
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
                        },
                        element_host,
                        cluster,
                    )

        if not prompt_yes_no("Process another Prism Element", default=False):
            break

    out = Path(report_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "timestamp_utc",
        "run_id",
        "element",
        "cluster_uuid",
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
