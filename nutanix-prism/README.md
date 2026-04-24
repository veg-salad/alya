# Nutanix AHV VLAN Test (Interactive)

## Overview

- Prompts interactively for Prism Element, guest, CSV, and report settings.
- Reads a CSV containing VLAN/network/test-IP rows and L3 details when Prism does not provide IPAM data.
- Fetches AHV network inventory from each Prism Element and validates CSV rows before execution.
- Processes one Prism Element cluster at a time, then asks whether to process another Element.
- Finds one pre-created Windows test VM in each Element cluster.
- Enforces exactly one NIC on the test VM (multi-NIC test VMs are not allowed).
- Rebinds test VM NIC to each target AHV network, auto-detects guest interface name using guest credentials, migrates across hosts, pings gateway from inside guest, and pings the test guest IP from the machine running the script.
- For Windows guests, command execution tries SSH first and automatically falls back to PowerShell WinRM.
- Keeps each Element run in memory and produces one combined CSV report with PASS/FAIL rows.

## Prerequisites

- Python 3.9+ on the execution machine.
- Network connectivity from execution machine to:
	- Prism Element (`https://<element>:9440`)
	- Windows guest test VM IPs over SSH (`tcp/22`) and/or WinRM (`tcp/5985`; `tcp/5986` if HTTPS WinRM is used)
	- ICMP reachability from execution machine to test guest IPs
- Prism Element API credentials with rights for inventory read, VM NIC update, and VM migration.
- One pre-created Windows test VM in each Element cluster you process.
- Test VM must have exactly one NIC.
- Guest remote access requirements:
 	- Windows test VM: OpenSSH Server recommended; WinRM enabled as fallback; account with administrator rights for `Get-NetRoute`, `New-NetIPAddress`, and `Test-Connection`.
- Reserved free IP per tested network/VLAN.

## Installation

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

## CSV Input Schema

Required columns:

- `vlan_id`
- `subnet_extid`
- `free_ip`
- `gateway`

Optional column:

- `subnet_name`
- `prefix_length`
- `subnet_mask`

CSV example:

```csv
vlan_id,subnet_extid,free_ip,gateway,subnet_name
100,11111111-2222-3333-4444-555555555555,192.168.100.50,192.168.100.1,APP_VLAN_100
200,aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee,192.168.200.50,192.168.200.1,DB_VLAN_200
```

Notes:

- `subnet_name` is optional and only for operator readability.
- `gateway` is the default gateway that the Windows guest pings after its NIC is moved to the target network.
- The tool prompts once for a required default CIDR prefix length and uses it for every CSV row without a mask override.
- To override the default mask per row, provide either `prefix_length` such as `24`, or `subnet_mask` such as `255.255.255.0`.
- In non-IPAM environments, Prism may return only Layer 2 network information. In that case, `gateway` must be supplied in the CSV, and the prompted default prefix is used unless overridden.
- `free_ip` must be an unused address in the target network. The tool does not reserve or allocate IPs.
- Rows with any required field missing (`vlan_id`, `subnet_extid`, `free_ip`, `gateway`) are **skipped** rather than aborting execution. Skipped rows appear in the report with `status=SKIPPED` and a description of the missing field(s) in the `detail` column.

## Prism Inventory vs CSV Input

The tool fetches these details from each Prism Element:

- local cluster and hosts
- VM inventory and test VM NIC details
- AHV network UUID, VLAN ID, network name, bridge, and virtual switch references
- Prism IP configuration when available

The CSV must provide these operator-owned values:

- `free_ip`
- `gateway`
- optional per-row mask override with `prefix_length` or `subnet_mask`

For environments where Prism does not manage IPAM for AHV VLANs, the CSV values plus the prompted default prefix are the source of truth for guest IP configuration and gateway probe behavior.

## Execution

Dry run:

```bash
python ahv_vlan_test.py --dry-run
```

Preflight only (no mutation, plan printout only):

```bash
python ahv_vlan_test.py --preflight-only
```

Manual per-Element VM confirmation gate:

```bash
python ahv_vlan_test.py --confirm-vm-per-element
```

Execution mode behavior:

- `--preflight-only` exits after plan/validation (takes precedence over `--dry-run`).
- `--confirm-vm-per-element` applies to actual run and `--dry-run`, not `--preflight-only`.

Actual run:

```bash
python ahv_vlan_test.py
```

Interactive prompts:

- Prism Element username/password
- Windows Test VM name
- Windows guest username/password
- CSV path
- Report path
- Default CIDR prefix length for CSV rows without a mask override
- One Prism Element IP/FQDN at a time
- Whether to process another Prism Element after each cluster completes

Runtime timings and probe settings use built-in defaults in this version:

- settle seconds: `15`
- ping count: `3`
- API timeout: `45` seconds
- guest connectivity timeout: `20` seconds
- migration timeout: `300` seconds

The script auto-detects guest interface name from the default route inside the guest.

After each Element inventory discovery, the script prints the local cluster plan, executes or records that cluster, then asks whether to process another Prism Element. All results are written to one combined report.

For Windows guests, remote execution order is:

1. SSH PowerShell
2. WinRM PowerShell fallback (if SSH path fails)

## Validation and Safety Controls

Before running tests, the tool validates each CSV row against the current Prism Element network inventory:

- `subnet_extid` must exist as an Element network UUID
- `vlan_id` must match the Element network `vlan_id`
- each CSV row must have `free_ip` and `gateway` populated
- mask information comes from Prism when available, otherwise from CSV `prefix_length` / `subnet_mask`, otherwise the prompted default prefix

Rows that fail any of these checks are **skipped individually** — they do not halt the run. Skipped rows appear in the report with:

- `status`: `SKIPPED`
- `stage`: `csv_validation`
- `detail`: reason (e.g. `missing required field(s): free_ip, gateway` or `VLAN mismatch`)

Only rows that pass validation are tested. If all rows for a cluster are invalid, no tests run for that cluster but other clusters are still processed.

VM targeting controls:

- exactly one VM with the provided test name must exist per cluster
- if zero or multiple matches are found, that cluster is skipped with `vm_targeting` failure record
- if the matched VM has more than one NIC, that cluster is skipped with `vm_nic_count` failure record

Execution confirmation controls:

- non-dry-run execution requires a `YES` confirmation for each Element plan
- optional `--confirm-vm-per-element` requires `YES` per Element and prints VM UUID/NIC UUID

Probe behavior per migrated host:

- Probe 1: gateway ping from inside the Windows guest.
- Probe 2: test guest IP ping from the execution machine.
- Result status is `PASS` only if both probes pass.

## Operational Notes and Limitations

- `--preflight-only` takes precedence if combined with `--dry-run`.
- `--confirm-vm-per-element` applies to actual run and dry-run, not preflight-only.
- SSH host keys are auto-accepted in this version; run only in trusted network contexts.
- Windows WinRM fallback currently uses default HTTP WinRM (`tcp/5985`) unless code is extended for custom HTTPS endpoint handling.
