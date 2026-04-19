# AHV VLAN Test v1 (Interactive)

## What this script does

- Prompts interactively for Prism and guest credentials.
- Reads a CSV containing VLAN/subnet/test-IP rows.
- Fetches AHV subnet inventory from Prism and validates CSV rows before execution.
- Finds one pre-created test VM (same name) in each cluster.
- Rebinds test VM NIC to each target subnet, migrates across hosts, and pings gateway from guest.
- Produces CSV report with PASS/FAIL rows.

## Operator runbook

1. Confirm change window and verify test VMs are not production workloads.
2. Prepare `subnet_input.csv` with `vlan_id,subnet_extid,free_ip` (reserved IPs only).
3. Run `--preflight-only` and review planned clusters/subnets.
4. Run `--dry-run` to simulate full execution and verify targeting/report layout.
5. Run actual execution with `--confirm-vm-per-cluster` in shared/production environments.
6. Review report CSV and remediate all `FAIL` rows before rerun.

## Prerequisites

- Python 3.9+ on the execution host.
- Network connectivity from execution host to:
	- Prism Central (`https://<pc>:9440`)
	- guest test VM IPs over SSH (`tcp/22`)
- Prism Central API credentials with rights for inventory read, VM NIC update, and VM migration.
- One pre-created test VM in each cluster with the same VM name.
- Guest SSH enabled on test VMs and a guest account with privileges for:
	- `ip addr`
	- `ip route`
	- `ping`
- Reserved free IP per tested subnet/VLAN (managed in IPAM).

## Install dependencies

```bash
pip install -r requirements.txt
```

Optional (recommended) virtual environment setup:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Input CSV schema

Required columns:

- `vlan_id`
- `subnet_extid`
- `free_ip`

Optional column:

- `subnet_name`

CSV example:

```csv
vlan_id,subnet_extid,free_ip,subnet_name
100,11111111-2222-3333-4444-555555555555,192.168.100.50,APP_VLAN_100
200,aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee,192.168.200.50,DB_VLAN_200
```

Notes:

- `subnet_name` is optional and only for operator readability.
- Use IPs reserved in your IPAM process.

## Run

Dry run:

```bash
python ahv_vlan_test_v1.py --dry-run
```

Preflight only (no mutation, plan printout only):

```bash
python ahv_vlan_test_v1.py --preflight-only
```

Manual per-cluster VM confirmation gate:

```bash
python ahv_vlan_test_v1.py --confirm-vm-per-cluster
```

Flag interaction notes:

- `--preflight-only` exits after plan/validation (takes precedence over `--dry-run`).
- `--confirm-vm-per-cluster` applies to actual run and `--dry-run`, not `--preflight-only`.

Actual run:

```bash
python ahv_vlan_test_v1.py
```

The program prompts for:

- Prism Central IP/FQDN, username, password
- Test VM name
- Guest SSH username/password
- Guest interface name
- CSV path
- Report path and runtime tuning values

## Validation behavior

Before running tests, the tool validates each CSV row against Prism subnet inventory:

- `subnet_extid` must exist
- `vlan_id` must match subnet `networkId`
- subnet must include gateway + prefix info

During execution, the tool also validates cluster scope:

- subnet cluster references (`clusterReferenceList` / `clusterReference`) must include the cluster under test
- if not, that row is marked `FAIL` with stage `subnet_cluster_scope` and skipped

VM targeting safety behavior:

- exactly one VM with the provided test name must exist per cluster
- if zero or multiple matches are found, that cluster is skipped with `vm_targeting` failure record

Execution safety behavior:

- non-dry-run execution requires a global `YES` confirmation after preflight summary
- optional `--confirm-vm-per-cluster` requires `YES` per cluster and prints VM extId/NIC extId

If any row fails validation, execution stops immediately.

## Do's and Don'ts

Do:

- Run `--preflight-only` first, then `--dry-run`, then actual execution.
- Use `--confirm-vm-per-cluster` for production or shared environments.
- Reserve one known free IP per subnet/VLAN in IPAM and use only those in CSV.
- Keep one dedicated test VM per cluster with the exact same test VM name.
- Ensure test VM guest account has required privilege to run `ip addr` and `ip route` commands.
- Verify guest SSH reachability for each test IP before live execution.
- Use least-privilege Prism API credentials (inventory + NIC update + VM migrate scope only).
- Review report output after each run and investigate all `FAIL` rows before rerun.

Don't:

- Do not run against a business VM or a VM with active production workload.
- Do not reuse random/untracked free IPs; avoid IP conflict risk.
- Do not assume `--dry-run` validates real network reachability (it validates flow only).
- Do not disable the single-VM targeting rule by changing script logic casually.
- Do not store credentials in plain text files or commit them to source control.
- Do not run during maintenance/failover windows unless planned, as migration results may be noisy.

Operational cautions:

- `--preflight-only` takes precedence if combined with `--dry-run`.
- `--confirm-vm-per-cluster` applies to actual run and dry-run, not preflight-only.
- A subnet row is skipped for a cluster if subnet cluster references do not include that cluster.
- SSH host keys are auto-accepted in this version; run only in trusted network contexts.
