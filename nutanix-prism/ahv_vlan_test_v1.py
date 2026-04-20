#!/usr/bin/env python3
"""Interactive AHV VLAN validation tool (procedural version).

Workflow:
1. Prompt for Prism Central, guest credentials, and runtime options.
2. Validate CSV rows against Prism subnet inventory.
3. Find exactly one VM (by name) per cluster.
4. Enforce exactly one VM NIC (multi-NIC test VMs are blocked).
5. Rebind VM NIC to each target subnet, configure guest IP, migrate host-by-host.
6. Ping gateway from inside guest and write CSV PASS/FAIL report.
"""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import re
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import paramiko
import requests

API_PATHS = {
    "clusters": "/api/clustermgmt/v4.0/config/clusters",
    "hosts": "/api/clustermgmt/v4.0/config/hosts",
    "subnets": "/api/networking/v4.0/config/subnets",
    "vms": "/api/vmm/v4.0/ahv/config/vms",
    "vm_get": "/api/vmm/v4.0/ahv/config/vms/{vm_extid}",
    "vm_nic_update": "/api/vmm/v4.0/ahv/config/vms/{vm_extid}/nics/{nic_extid}",
    "vm_migrate_action": "/api/vmm/v4.0/ahv/config/vms/{vm_extid}/$actions/migrate",
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def prompt_non_empty(text: str) -> str:
    while True:
        value = input(text).strip()
        if value:
            return value
        print("Value is required.")


def prompt_int(text: str, default: Optional[int] = None) -> int:
    while True:
        raw = input(text).strip()
        if not raw and default is not None:
            return default
        try:
            return int(raw)
        except ValueError:
            print("Please enter a valid integer.")


def prompt_yes_no(text: str, default: bool) -> bool:
    default_txt = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{text} [{default_txt}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Please answer yes or no.")


def prompt_guest_os() -> str:
    while True:
        raw = input("Test VM OS [Linux/Windows]: ").strip().lower()
        if raw in {"linux", "l"}:
            return "linux"
        if raw in {"windows", "w"}:
            return "windows"
        print("Please enter Linux or Windows.")


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


def list_all(session: requests.Session, path: str, timeout: int, limit: int = 100) -> List[Dict[str, Any]]:
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


def parse_subnet_csv(csv_path: str) -> List[Dict[str, str]]:
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"vlan_id", "subnet_extid", "free_ip"}
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
            rows.append(cleaned)

        if not rows:
            raise RuntimeError("CSV has no data rows")
        return rows


def build_subnet_tests(csv_rows: List[Dict[str, str]], subnets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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

        ip_cfg_list = subnet.get("ipConfig", [])
        if not ip_cfg_list:
            errors.append(f"Row {idx}: subnet_extid {subnet_extid} has no ipConfig")
            continue

        ipv4 = ip_cfg_list[0].get("ipv4", {})
        prefix = ipv4.get("ipSubnet", {}).get("prefixLength")
        gateway = ipv4.get("defaultGatewayIp", {}).get("value")
        if prefix is None or not gateway:
            errors.append(f"Row {idx}: subnet_extid {subnet_extid} missing prefix or default gateway")
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


def detect_guest_interface(host: str, user: str, password: str, timeout: int, guest_os: str) -> str:
    if guest_os == "linux":
        cmd = "ip -o -4 route show default"
        res = ssh_run(host, user, password, cmd, timeout)
        if res["exit_code"] != 0:
            raise RuntimeError(res["stderr"] or res["stdout"] or "Failed to detect default route")
        match = re.search(r"\bdev\s+(\S+)", res["stdout"])
        if not match:
            raise RuntimeError(f"Could not parse interface from route output: {res['stdout'].strip()}")
        return match.group(1)

    ps_cmd = (
        "powershell -NoProfile -Command \""
        "$r = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' "
        "| Sort-Object RouteMetric "
        "| Select-Object -First 1 -ExpandProperty InterfaceAlias; "
        "if (-not $r) { exit 2 }; "
        "Write-Output $r"
        "\""
    )
    res = ssh_run(host, user, password, ps_cmd, timeout)
    name = res["stdout"].strip()
    if res["exit_code"] != 0 or not name:
        raise RuntimeError(res["stderr"] or res["stdout"] or "Failed to detect Windows interface")
    return name


def configure_guest_ip(
    host: str,
    user: str,
    password: str,
    timeout: int,
    guest_os: str,
    iface: str,
    ip_addr: str,
    prefix: int,
    gateway: str,
) -> Dict[str, Any]:
    if guest_os == "linux":
        cmd = (
            f"sudo ip addr flush dev {iface} && "
            f"sudo ip addr add {ip_addr}/{prefix} dev {iface} && "
            f"sudo ip link set {iface} up && "
            f"sudo ip route replace default via {gateway} dev {iface}"
        )
        return ssh_run(host, user, password, cmd, timeout)

    safe_iface = iface.replace("'", "''")
    ps = (
        "powershell -NoProfile -Command \""
        f"$if='{safe_iface}'; "
        f"$ip='{ip_addr}'; "
        f"$gw='{gateway}'; "
        f"$p={prefix}; "
        "Get-NetIPAddress -InterfaceAlias $if -AddressFamily IPv4 -ErrorAction SilentlyContinue "
        "| Remove-NetIPAddress -Confirm:$false -ErrorAction SilentlyContinue; "
        "Get-NetRoute -InterfaceAlias $if -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue "
        "| Remove-NetRoute -Confirm:$false -ErrorAction SilentlyContinue; "
        "New-NetIPAddress -InterfaceAlias $if -IPAddress $ip -PrefixLength $p -DefaultGateway $gw -AddressFamily IPv4 -ErrorAction Stop | Out-Null"
        "\""
    )
    return ssh_run(host, user, password, ps, timeout)


def ping_gateway(
    host: str,
    user: str,
    password: str,
    timeout: int,
    guest_os: str,
    gateway: str,
    ping_count: int,
) -> Dict[str, Any]:
    if guest_os == "linux":
        return ssh_run(host, user, password, f"ping -c {ping_count} -W 2 {gateway}", timeout)

    ps = (
        "powershell -NoProfile -Command \""
        f"if (Test-Connection -ComputerName '{gateway}' -Count {ping_count} -Quiet) {{ "
        "Write-Output 'PASS'; exit 0 "
        "} else { Write-Output 'FAIL'; exit 1 }"
        "\""
    )
    return ssh_run(host, user, password, ps, timeout)


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

    print("AHV VLAN Validator (Interactive)")
    pc_host = prompt_non_empty("Prism Central IP/FQDN: ")
    pc_user = prompt_non_empty("Prism Username: ")
    pc_pass = getpass.getpass("Prism Password: ")
    vm_name = prompt_non_empty("Test VM Name (same name across clusters): ")
    guest_os = prompt_guest_os()
    guest_user = prompt_non_empty("Guest Username: ")
    guest_pass = getpass.getpass("Guest Password: ")
    csv_path = prompt_non_empty("Path to subnet CSV (vlan_id,subnet_extid,free_ip): ")
    report_path = input("Report CSV path [vlan_test_report_v1.csv]: ").strip() or "vlan_test_report_v1.csv"
    verify_tls = prompt_yes_no("Verify TLS certificates", default=False)

    settle_seconds = prompt_int("Settle seconds after NIC/migration [15]: ", default=15)
    ping_count = prompt_int("Ping count [3]: ", default=3)
    api_timeout = prompt_int("API timeout seconds [45]: ", default=45)
    ssh_timeout = prompt_int("Guest SSH timeout seconds [20]: ", default=20)
    migration_timeout = prompt_int("Migration wait timeout seconds [300]: ", default=300)

    run_id = str(uuid.uuid4())
    session = init_session(pc_host, pc_user, pc_pass, verify_tls)

    print(f"[{now_utc()}] Fetching Prism inventory")
    clusters = list_all(session, API_PATHS["clusters"], api_timeout)
    hosts = list_all(session, API_PATHS["hosts"], api_timeout)
    subnets = list_all(session, API_PATHS["subnets"], api_timeout)
    vms = list_all(session, API_PATHS["vms"], api_timeout)

    csv_rows = parse_subnet_csv(csv_path)
    subnet_tests = build_subnet_tests(csv_rows, subnets)

    hosts_by_cluster: Dict[str, List[Dict[str, Any]]] = {}
    for host in hosts:
        cluster_id = host.get("cluster", {}).get("uuid")
        if cluster_id:
            hosts_by_cluster.setdefault(cluster_id, []).append(host)

    report_rows: List[Dict[str, Any]] = []

    def record(row: Dict[str, Any]) -> None:
        row["timestamp_utc"] = now_utc()
        row["run_id"] = run_id
        row["guest_os"] = guest_os
        report_rows.append(row)

    print(f"[{now_utc()}] Run ID: {run_id}")
    print(f"[{now_utc()}] Planned clusters: {len(clusters)}")
    print(f"[{now_utc()}] Planned subnet rows: {len(subnet_tests)}")
    for test in subnet_tests:
        print(
            f"  - subnet={test['subnet_name']} vlan={test['vlan_id']} "
            f"extId={test['subnet_extid']} ip={test['free_ip']} gw={test['gateway']}"
        )

    if args.preflight_only:
        print(f"[{now_utc()}] Preflight only selected. No changes will be made.")
        out = Path(report_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        fields = [
            "timestamp_utc",
            "run_id",
            "guest_os",
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
        print(f"[{now_utc()}] Wrote report skeleton: {out}")
        return 0

    if not args.dry_run and input("Type YES to execute this plan: ").strip() != "YES":
        print("Execution cancelled by user.")
        return 0

    for cluster in clusters:
        cluster_name = cluster.get("name", "")
        cluster_extid = cluster.get("extId", "")
        if not cluster_extid:
            continue

        cluster_hosts = hosts_by_cluster.get(cluster_extid, [])
        if not cluster_hosts:
            print(f"[{now_utc()}] Skip {cluster_name}: no hosts")
            continue

        vm_matches = [
            vm
            for vm in vms
            if vm.get("name") == vm_name and vm.get("cluster", {}).get("extId") == cluster_extid
        ]

        if len(vm_matches) != 1:
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
            print(f"[{now_utc()}] Skip {cluster_name}: VM has {len(vm_nics)} NICs (only 1 allowed)")
            continue

        nic_extid = vm_nics[0].get("extId", "")

        if args.confirm_vm_per_cluster:
            print(
                f"[{now_utc()}] Confirm cluster execution:\n"
                f"  Cluster: {cluster_name}\n"
                f"  Test VM: {vm_name}\n"
                f"  Test VM extId: {vm_extid}\n"
                f"  Test NIC extId: {nic_extid}\n"
                f"  Guest OS: {guest_os}"
            )
            if input("Type YES to continue this cluster: ").strip() != "YES":
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

        print(f"[{now_utc()}] Cluster {cluster_name}: {len(subnet_tests)} subnet rows, {len(cluster_hosts)} hosts")

        for test in subnet_tests:
            if test["cluster_extids"] and cluster_extid not in test["cluster_extids"]:
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
                rebind_vm_nic_subnet(session, vm_extid, nic_extid, test["subnet_extid"], api_timeout)
                time.sleep(settle_seconds)

                iface = detect_guest_interface(test["free_ip"], guest_user, guest_pass, ssh_timeout, guest_os)
                cfg_res = configure_guest_ip(
                    test["free_ip"],
                    guest_user,
                    guest_pass,
                    ssh_timeout,
                    guest_os,
                    iface,
                    test["free_ip"],
                    test["prefix"],
                    test["gateway"],
                )
                if cfg_res["exit_code"] != 0:
                    raise RuntimeError(cfg_res["stderr"] or cfg_res["stdout"] or "Guest IP config failed")
            except Exception as exc:
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

            for host in cluster_hosts:
                host_name = host.get("hostName", "")
                host_extid = host.get("extId", "")

                try:
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

                    time.sleep(settle_seconds)
                    ping_res = ping_gateway(
                        test["free_ip"],
                        guest_user,
                        guest_pass,
                        ssh_timeout,
                        guest_os,
                        test["gateway"],
                        ping_count,
                    )

                    ok = ping_res["exit_code"] == 0
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
                            "detail": (ping_res["stdout"] if ok else (ping_res["stderr"] or ping_res["stdout"])).strip(),
                        }
                    )
                except Exception as exc:
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
        "guest_os",
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
    print(f"[{now_utc()}] Completed. Rows={len(report_rows)} Failures={failures} Report={out}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
