# Nutanix AHV VLAN Test (Interactive)

## What this script does

- Prompts interactively for Prism Central and guest credentials.
- Prompts for test VM OS type (`Linux` or `Windows`) during runtime.
- Reads a CSV containing VLAN/subnet/test-IP rows.
- Fetches AHV subnet inventory from Prism Central and validates CSV rows before execution.
- Finds one pre-created test VM (same name) in each cluster.
- Enforces exactly one NIC on the test VM (multi-NIC test VMs are not allowed).
- Rebinds test VM NIC to each target subnet, auto-detects guest interface name using guest credentials, migrates across hosts, and pings gateway from inside guest.
- For Windows guests, command execution tries SSH first and automatically falls back to PowerShell WinRM.
- Produces CSV report with PASS/FAIL rows.

## Prerequisites

- Python 3.9+ on the execution machine.
- Network connectivity from execution machine to:
	- Prism Central (`https://<pc>:9440`)
	- Linux guest test VM IPs over SSH (`tcp/22`)
	- Windows guest test VM IPs over SSH (`tcp/22`) and/or WinRM (`tcp/5985`; `tcp/5986` if HTTPS WinRM is used)
- Prism Central API credentials with rights for inventory read, VM NIC update, and VM migration.
- One pre-created test VM in each cluster with the same VM name.
- Test VM must have exactly one NIC.
- Guest remote access requirements:
 	- Linux test VM: SSH enabled and account with `sudo` rights for `ip` and `ping`.
 	- Windows test VM: OpenSSH Server recommended; WinRM enabled as fallback; account with administrator rights for `Get-NetRoute`, `New-NetIPAddress`, and `Test-Connection`.
- Reserved free IP per tested subnet/VLAN.

## Install dependencies

```bash
pip install -r requirements.txt
```

`requirements.txt` includes `pywinrm` for Windows WinRM fallback.

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

## Run

Dry run:

```bash
python ahv_vlan_test.py --dry-run
```

Preflight only (no mutation, plan printout only):

```bash
python ahv_vlan_test.py --preflight-only
```

Manual per-cluster VM confirmation gate:

```bash
python ahv_vlan_test.py --confirm-vm-per-cluster
```

Flag interaction notes:

- `--preflight-only` exits after plan/validation (takes precedence over `--dry-run`).
- `--confirm-vm-per-cluster` applies to actual run and `--dry-run`, not `--preflight-only`.

Actual run:

```bash
python ahv_vlan_test.py
```

The program prompts for:

- Prism Central IP/FQDN, username, password
- Test VM name
- Test VM OS (`Linux` or `Windows`)
- Guest SSH username/password
- CSV path
- Report path and runtime tuning values

The program auto-detects guest interface name from the default route inside the guest.

For Windows guests, remote execution order is:

1. SSH PowerShell
2. WinRM PowerShell fallback (if SSH path fails)

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
- if the matched VM has more than one NIC, that cluster is skipped with `vm_nic_count` failure record

Execution safety behavior:

- non-dry-run execution requires a global `YES` confirmation after preflight summary
- optional `--confirm-vm-per-cluster` requires `YES` per cluster and prints VM extId/NIC extId

If any row fails validation, execution stops immediately.

## Do's and Don'ts

Operational cautions:

- `--preflight-only` takes precedence if combined with `--dry-run`.
- `--confirm-vm-per-cluster` applies to actual run and dry-run, not preflight-only.
- A subnet row is skipped for a cluster if subnet cluster references do not include that cluster.
- SSH host keys are auto-accepted in this version; run only in trusted network contexts.
