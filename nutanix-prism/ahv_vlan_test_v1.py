#!/usr/bin/env python3
"""Interactive AHV VLAN validation tool (v1).

What it does:
1. Prompts for Prism Central and guest credentials.
2. Prompts for CSV input containing VLAN/subnet mapping + free test IP per subnet.
3. Fetches AHV subnet inventory and validates every CSV row before running any test.
4. For each cluster that contains the test VM name:
   - rebinds the first vNIC to each requested subnet
   - configures guest IP/gateway via SSH
   - migrates the VM host-by-host
   - pings the default gateway from inside the guest
5. Writes a CSV report.

CSV required columns:
- vlan_id
- subnet_extid
- free_ip

Optional columns:
- subnet_name
"""

from __future__ import annotations

import argparse
import csv
import getpass
import json
import sys
import time
import uuid
from dataclasses import dataclass
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


@dataclass
class SubnetTest:
    vlan_id: int
    subnet_extid: str
    subnet_name: str
    prefix: int
    gateway: str
    free_ip: str
    cluster_extids: List[str]


class PrismClient:
    def __init__(self, host: str, username: str, password: str, verify_tls: bool, timeout: int):
        self.base_url = f"https://{host}:9440"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.verify = verify_tls
        if not verify_tls:
            requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        res = self.session.get(self._url(path), params=params, timeout=self.timeout)
        res.raise_for_status()
        return res.json()

    def put(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        res = self.session.put(self._url(path), json=payload, timeout=self.timeout)
        res.raise_for_status()
        return res.json()

    def post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        res = self.session.post(self._url(path), json=payload, timeout=self.timeout)
        res.raise_for_status()
        if res.text.strip():
            return res.json()
        return {}

    def list_all(self, path: str, limit: int = 100) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        page = 0
        while True:
            payload = self.get(path, params={"$page": page, "$limit": limit})
            data = payload.get("data", [])
            if not isinstance(data, list):
                break
            rows.extend(data)
            meta = payload.get("metadata", {})
            total = int(meta.get("totalAvailableResults", len(rows)))
            if len(rows) >= total or len(data) < limit:
                break
            page += 1
        return rows

    def get_vm(self, vm_extid: str) -> Dict[str, Any]:
        return self.get(API_PATHS["vm_get"].format(vm_extid=vm_extid)).get("data", {})

    def rebind_vm_nic_subnet(self, vm_extid: str, nic_extid: str, target_subnet_extid: str) -> None:
        vm = self.get_vm(vm_extid)
        nics = vm.get("nics", [])
        nic = next((n for n in nics if n.get("extId") == nic_extid), None)
        if not nic:
            raise RuntimeError(f"NIC {nic_extid} not found on VM {vm_extid}")

        nic_payload = json.loads(json.dumps(nic))
        for key in ["nicNetworkInfo", "networkInfo"]:
            nic_payload.setdefault(key, {})
            nic_payload[key]["nicType"] = "NORMAL_NIC"
            nic_payload[key]["vlanMode"] = "ACCESS"
            nic_payload[key]["subnet"] = {"extId": target_subnet_extid}

        path = API_PATHS["vm_nic_update"].format(vm_extid=vm_extid, nic_extid=nic_extid)
        self.put(path, nic_payload)

    def migrate_vm_to_host(self, vm_extid: str, host_extid: str) -> None:
        path = API_PATHS["vm_migrate_action"].format(vm_extid=vm_extid)
        self.post(path, {"host": {"extId": host_extid}})


class SSHRunner:
    def __init__(self, username: str, password: str, timeout: int):
        self.username = username
        self.password = password
        self.timeout = timeout

    def run(self, host: str, command: str) -> Dict[str, Any]:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=host,
            username=self.username,
            password=self.password,
            timeout=self.timeout,
            banner_timeout=self.timeout,
            auth_timeout=self.timeout,
        )
        try:
            _, stdout, stderr = client.exec_command(command, timeout=self.timeout)
            code = stdout.channel.recv_exit_status()
            return {
                "exit_code": code,
                "stdout": stdout.read().decode("utf-8", errors="replace"),
                "stderr": stderr.read().decode("utf-8", errors="replace"),
            }
        finally:
            client.close()


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


def build_subnet_tests(csv_rows: List[Dict[str, str]], fetched_subnets: List[Dict[str, Any]]) -> List[SubnetTest]:
    by_extid: Dict[str, Dict[str, Any]] = {s.get("extId"): s for s in fetched_subnets if s.get("extId")}
    tests: List[SubnetTest] = []
    errors: List[str] = []

    for idx, row in enumerate(csv_rows, start=1):
        subnet_extid = row["subnet_extid"]
        expected_vlan = row["vlan_id"]
        free_ip = row["free_ip"]

        sub = by_extid.get(subnet_extid)
        if not sub:
            errors.append(f"Row {idx}: subnet_extid {subnet_extid} not found in Prism inventory")
            continue

        actual_vlan = str(sub.get("networkId", ""))
        if actual_vlan != str(expected_vlan):
            errors.append(
                f"Row {idx}: subnet_extid {subnet_extid} VLAN mismatch. CSV={expected_vlan}, Prism={actual_vlan}"
            )
            continue

        ip_cfg_list = sub.get("ipConfig", [])
        if not ip_cfg_list:
            errors.append(f"Row {idx}: subnet_extid {subnet_extid} has no ipConfig")
            continue

        ipv4 = ip_cfg_list[0].get("ipv4", {})
        ip_subnet = ipv4.get("ipSubnet", {})
        prefix = ip_subnet.get("prefixLength")
        gateway = ipv4.get("defaultGatewayIp", {}).get("value")
        if prefix is None or not gateway:
            errors.append(f"Row {idx}: subnet_extid {subnet_extid} missing prefix or default gateway")
            continue

        cluster_extids: List[str] = []
        for extid in sub.get("clusterReferenceList", []) or []:
            if extid and extid not in cluster_extids:
                cluster_extids.append(extid)
        single_cluster = sub.get("clusterReference")
        if single_cluster and single_cluster not in cluster_extids:
            cluster_extids.append(single_cluster)

        tests.append(
            SubnetTest(
                vlan_id=int(actual_vlan),
                subnet_extid=subnet_extid,
                subnet_name=sub.get("name", ""),
                prefix=int(prefix),
                gateway=gateway,
                free_ip=free_ip,
                cluster_extids=cluster_extids,
            )
        )

    if errors:
        raise RuntimeError("Validation failed:\n- " + "\n- ".join(errors))

    return tests


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="Interactive AHV VLAN validator")
    parser.add_argument("--dry-run", action="store_true", help="Only validate/discover, no changes")
    parser.add_argument(
        "--confirm-vm-per-cluster",
        action="store_true",
        help="Require manual YES confirmation with VM extId before each cluster test",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Print and export execution plan only; do not perform mutations",
    )
    args = parser.parse_args()

    print("AHV VLAN Validator (Interactive v1)")
    pc_host = prompt_non_empty("Prism Central IP/FQDN: ")
    pc_user = prompt_non_empty("Prism Username: ")
    pc_pass = getpass.getpass("Prism Password: ")
    vm_name = prompt_non_empty("Test VM Name (same name across clusters): ")
    guest_user = prompt_non_empty("Guest SSH Username: ")
    guest_pass = getpass.getpass("Guest SSH Password: ")
    guest_interface = prompt_non_empty("Guest Interface Name (e.g. eth0): ")
    csv_path = prompt_non_empty("Path to subnet CSV (vlan_id,subnet_extid,free_ip): ")
    report_path = input("Report CSV path [vlan_test_report_v1.csv]: ").strip() or "vlan_test_report_v1.csv"
    verify_tls = prompt_yes_no("Verify TLS certificates", default=False)

    settle_seconds = prompt_int("Settle seconds after NIC/migration [15]: ", default=15)
    ping_count = prompt_int("Ping count [3]: ", default=3)
    api_timeout = prompt_int("API timeout seconds [45]: ", default=45)
    ssh_timeout = prompt_int("SSH timeout seconds [20]: ", default=20)
    migration_timeout = prompt_int("Migration wait timeout seconds [300]: ", default=300)

    run_id = str(uuid.uuid4())

    client = PrismClient(
        host=pc_host,
        username=pc_user,
        password=pc_pass,
        verify_tls=verify_tls,
        timeout=api_timeout,
    )
    ssh = SSHRunner(username=guest_user, password=guest_pass, timeout=ssh_timeout)

    print(f"[{now_utc()}] Fetching inventory from Prism Central")
    clusters = client.list_all(API_PATHS["clusters"])
    hosts = client.list_all(API_PATHS["hosts"])
    subnets = client.list_all(API_PATHS["subnets"])
    vms = client.list_all(API_PATHS["vms"])

    csv_rows = parse_subnet_csv(csv_path)
    subnet_tests = build_subnet_tests(csv_rows, subnets)
    print(f"[{now_utc()}] Validated {len(subnet_tests)} CSV rows against Prism subnet inventory")

    hosts_by_cluster: Dict[str, List[Dict[str, Any]]] = {}
    for host in hosts:
        cid = host.get("cluster", {}).get("uuid")
        if cid:
            hosts_by_cluster.setdefault(cid, []).append(host)

    report_rows: List[Dict[str, Any]] = []

    def record(row: Dict[str, Any]) -> None:
        row["timestamp_utc"] = now_utc()
        row["run_id"] = run_id
        report_rows.append(row)

    # Preflight summary before execution.
    print(f"[{now_utc()}] Run ID: {run_id}")
    print(f"[{now_utc()}] Planned clusters discovered: {len(clusters)}")
    print(f"[{now_utc()}] Planned subnet rows: {len(subnet_tests)}")
    for st in subnet_tests:
        print(
            f"  - Subnet={st.subnet_name} VLAN={st.vlan_id} extId={st.subnet_extid} "
            f"IP={st.free_ip} GW={st.gateway} clusters={len(st.cluster_extids)}"
        )

    if args.preflight_only:
        print(f"[{now_utc()}] Preflight-only mode requested. No mutation actions will run.")
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
        print(f"[{now_utc()}] Preflight complete. Report skeleton: {out}")
        return 0

    if not args.dry_run:
        proceed = input("Type YES to execute this plan: ").strip()
        if proceed != "YES":
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
            print(
                f"[{now_utc()}] Skip {cluster_name}: expected exactly one test VM named "
                f"'{vm_name}', found {len(vm_matches)}"
            )
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

        vm_summary = vm_matches[0]
        vm_extid = vm_summary.get("extId")
        vm_full = client.get_vm(vm_extid)
        vm_nics = vm_full.get("nics", [])
        if not vm_nics:
            print(f"[{now_utc()}] Skip {cluster_name}: VM has no NIC")
            continue
        nic_extid = vm_nics[0].get("extId")

        if args.confirm_vm_per_cluster:
            print(
                f"[{now_utc()}] Confirm cluster execution:\n"
                f"  Cluster: {cluster_name} ({cluster_extid})\n"
                f"  Test VM: {vm_name}\n"
                f"  Test VM extId: {vm_extid}\n"
                f"  Test NIC extId: {nic_extid}"
            )
            if input("Type YES to continue this cluster: ").strip() != "YES":
                print(f"[{now_utc()}] Cluster {cluster_name} skipped by operator confirmation gate")
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

        print(f"[{now_utc()}] Cluster {cluster_name}: testing {len(subnet_tests)} subnets across {len(cluster_hosts)} hosts")

        for subnet_test in subnet_tests:
            if subnet_test.cluster_extids and cluster_extid not in subnet_test.cluster_extids:
                record(
                    {
                        "cluster": cluster_name,
                        "host": "",
                        "test_vm": vm_name,
                        "vlan_id": subnet_test.vlan_id,
                        "subnet": subnet_test.subnet_name,
                        "subnet_extid": subnet_test.subnet_extid,
                        "test_ip": subnet_test.free_ip,
                        "gateway": subnet_test.gateway,
                        "status": "FAIL",
                        "stage": "subnet_cluster_scope",
                        "detail": "Subnet is not associated with this cluster in Prism references",
                    }
                )
                continue

            if args.dry_run:
                print(
                    f"[{now_utc()}] DRY-RUN rebind NIC {nic_extid} -> {subnet_test.subnet_name} "
                    f"({subnet_test.subnet_extid})"
                )
            else:
                try:
                    client.rebind_vm_nic_subnet(vm_extid, nic_extid, subnet_test.subnet_extid)
                    time.sleep(settle_seconds)
                except Exception as exc:
                    record(
                        {
                            "cluster": cluster_name,
                            "host": "",
                            "test_vm": vm_name,
                            "vlan_id": subnet_test.vlan_id,
                            "subnet": subnet_test.subnet_name,
                            "subnet_extid": subnet_test.subnet_extid,
                            "test_ip": subnet_test.free_ip,
                            "gateway": subnet_test.gateway,
                            "status": "FAIL",
                            "stage": "nic_rebind",
                            "detail": str(exc),
                        }
                    )
                    continue

            if args.dry_run:
                print(
                    f"[{now_utc()}] DRY-RUN guest cfg {subnet_test.free_ip}/{subnet_test.prefix} gw {subnet_test.gateway}"
                )
            else:
                try:
                    cfg_cmd = (
                        f"sudo ip addr flush dev {guest_interface} && "
                        f"sudo ip addr add {subnet_test.free_ip}/{subnet_test.prefix} dev {guest_interface} && "
                        f"sudo ip link set {guest_interface} up && "
                        f"sudo ip route replace default via {subnet_test.gateway} dev {guest_interface}"
                    )
                    cfg_res = ssh.run(subnet_test.free_ip, cfg_cmd)
                    if cfg_res["exit_code"] != 0:
                        record(
                            {
                                "cluster": cluster_name,
                                "host": "",
                                "test_vm": vm_name,
                                "vlan_id": subnet_test.vlan_id,
                                "subnet": subnet_test.subnet_name,
                                "subnet_extid": subnet_test.subnet_extid,
                                "test_ip": subnet_test.free_ip,
                                "gateway": subnet_test.gateway,
                                "status": "FAIL",
                                "stage": "guest_ip_config",
                                "detail": cfg_res["stderr"] or cfg_res["stdout"],
                            }
                        )
                        continue
                except Exception as exc:
                    record(
                        {
                            "cluster": cluster_name,
                            "host": "",
                            "test_vm": vm_name,
                            "vlan_id": subnet_test.vlan_id,
                            "subnet": subnet_test.subnet_name,
                            "subnet_extid": subnet_test.subnet_extid,
                            "test_ip": subnet_test.free_ip,
                            "gateway": subnet_test.gateway,
                            "status": "FAIL",
                            "stage": "guest_ip_config",
                            "detail": str(exc),
                        }
                    )
                    continue

            for host in cluster_hosts:
                host_name = host.get("hostName", "")
                host_extid = host.get("extId", "")

                if args.dry_run:
                    record(
                        {
                            "cluster": cluster_name,
                            "host": host_name,
                            "test_vm": vm_name,
                            "vlan_id": subnet_test.vlan_id,
                            "subnet": subnet_test.subnet_name,
                            "subnet_extid": subnet_test.subnet_extid,
                            "test_ip": subnet_test.free_ip,
                            "gateway": subnet_test.gateway,
                            "status": "DRY_RUN",
                            "stage": "complete",
                            "detail": "No actions executed",
                        }
                    )
                    continue

                try:
                    client.migrate_vm_to_host(vm_extid, host_extid)

                    # Wait until placement reflects target host.
                    start = time.time()
                    placed = False
                    while time.time() - start < migration_timeout:
                        vm_state = client.get_vm(vm_extid)
                        cur_host = vm_state.get("host", {}).get("extId")
                        if cur_host == host_extid:
                            placed = True
                            break
                        time.sleep(5)

                    if not placed:
                        record(
                            {
                                "cluster": cluster_name,
                                "host": host_name,
                                "test_vm": vm_name,
                                "vlan_id": subnet_test.vlan_id,
                                "subnet": subnet_test.subnet_name,
                                "subnet_extid": subnet_test.subnet_extid,
                                "test_ip": subnet_test.free_ip,
                                "gateway": subnet_test.gateway,
                                "status": "FAIL",
                                "stage": "vm_migration",
                                "detail": "Timed out waiting for host placement",
                            }
                        )
                        continue

                    time.sleep(settle_seconds)

                    ping_cmd = f"ping -c {ping_count} -W 2 {subnet_test.gateway}"
                    ping_res = ssh.run(subnet_test.free_ip, ping_cmd)
                    ok = ping_res["exit_code"] == 0

                    record(
                        {
                            "cluster": cluster_name,
                            "host": host_name,
                            "test_vm": vm_name,
                            "vlan_id": subnet_test.vlan_id,
                            "subnet": subnet_test.subnet_name,
                            "subnet_extid": subnet_test.subnet_extid,
                            "test_ip": subnet_test.free_ip,
                            "gateway": subnet_test.gateway,
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
                            "vlan_id": subnet_test.vlan_id,
                            "subnet": subnet_test.subnet_name,
                            "subnet_extid": subnet_test.subnet_extid,
                            "test_ip": subnet_test.free_ip,
                            "gateway": subnet_test.gateway,
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

    failures = sum(1 for r in report_rows if r.get("status") == "FAIL")
    print(f"[{now_utc()}] Completed. Rows={len(report_rows)} Failures={failures} Report={out}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
