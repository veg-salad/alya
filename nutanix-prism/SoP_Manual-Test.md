# SOP / KB: Manual AHV VLAN Validation via Prism Central (1-2 Hosts)

## Purpose

Use this SOP to manually validate VLAN/subnet connectivity in Nutanix AHV for a small check (for example, 1-2 hosts) and compare outcomes with the automation script.

This follows the same logic as the script:

1. Validate VLAN-to-subnet mapping.
2. Attach test VM NIC to one subnet.
3. Set test IP inside guest.
4. Ping default gateway from inside guest.
5. Migrate VM host-by-host and repeat ping.

## Scope

- Platform: Nutanix AHV managed by Prism Central.
- Use case: Manual spot-check for one or two hosts.
- Goal: Verify per-host VLAN path health for selected subnets.

Not in scope:

- Full data center certification across all clusters/hosts.
- Deep network troubleshooting (LACP/LLDP/switch config analysis).

## Audience

- Junior to mid-level sysadmins.
- Basic familiarity with Prism Central navigation and Linux guest login.

## Prerequisites

- Access to Prism Central UI with permissions for:
  - VM view/edit
  - VM live migration
  - Network/subnet view
- Dedicated test VM (not a production VM), with:
  - Nutanix Guest Tools installed (recommended)
  - SSH or console login available
- Guest credentials with privilege to change IP and route.
- Reserved free IPs for each subnet you test (from IPAM).
- A small test plan table (subnet name, VLAN ID, subnet extId, free IP, gateway).

## Dependencies / Tools

- Web browser for Prism Central.
- SSH client (PuTTY/PowerShell/OpenSSH) or Prism VM Console.
- Notepad/Excel sheet to record results.

## Inputs You Need Before Starting

For each subnet/VLAN under test:

- Subnet name in Prism Central
- VLAN ID (networkId)
- Subnet extId
- Free test IP
- Prefix/mask
- Default gateway

For host checks:

- Cluster name
- 1-2 target AHV host names
- Test VM name

## Safety Checks (Do This First)

1. Confirm the selected VM is a dedicated test VM.
2. Confirm you are in a maintenance-safe time window.
3. Confirm free test IPs are reserved and not in use.
4. Confirm you can log in to guest VM before making changes.

## Step-by-Step Procedure

### Step 1: Validate subnet and VLAN mapping in Prism

1. Open Prism Central.
2. Go to Networks/Subnets.
3. Search for the target subnet.
4. Confirm:
   - Subnet extId
   - VLAN ID (networkId)
   - Prefix/mask
   - Default gateway
5. Repeat for each subnet you will test.

Pass criteria:

- VLAN ID and subnet details match your test plan.

### Step 2: Confirm test VM and host targets

1. Go to VMs.
2. Open test VM details.
3. Confirm VM name and current host.
4. Identify the target hosts in the same cluster.

Pass criteria:

- Test VM found and powered on.
- Target hosts are healthy and available.

### Step 3: Attach test VM NIC to first subnet

1. In VM settings, open NIC configuration.
2. Select the NIC used for testing.
3. Change NIC network/subnet to target AHV subnet.
4. Save/apply changes.
5. Wait 10-20 seconds for stabilization.

Pass criteria:

- NIC shows expected subnet in VM settings.

### Step 4: Configure guest IP for that subnet

From SSH/console inside VM (Linux example):

```bash
sudo ip addr flush dev eth0
sudo ip addr add <FREE_IP>/<PREFIX> dev eth0
sudo ip link set eth0 up
sudo ip route replace default via <GATEWAY> dev eth0
ip addr show dev eth0
ip route
```

Replace:

- `<FREE_IP>` with reserved test IP
- `<PREFIX>` with subnet prefix (for example `24`)
- `<GATEWAY>` with subnet default gateway

Pass criteria:

- `eth0` shows correct IP/prefix.
- Default route points to expected gateway.

### Step 5: Probe gateway from guest (baseline)

Run:

```bash
ping -c 3 <GATEWAY>
```

Pass criteria:

- 3/3 or stable successful replies.

Record result as:

- Cluster
- Current host
- Subnet/VLAN
- Test IP
- Gateway
- Ping result (PASS/FAIL)

### Step 6: Migrate VM to Host 1 and retest

1. In Prism VM actions, select Live Migrate.
2. Choose Host 1.
3. Wait until VM placement shows Host 1.
4. Wait 10-20 seconds.
5. Run gateway ping again from guest.

Pass criteria:

- Gateway ping still successful.

### Step 7: Migrate VM to Host 2 and retest

Repeat Step 6 for Host 2.

Pass criteria:

- Gateway ping successful on Host 2 as well.

### Step 8: Repeat for next subnet

1. Re-attach VM NIC to next subnet.
2. Reconfigure guest IP/route for that subnet.
3. Repeat ping + migration checks.

## Result Interpretation

### Expected good outcome

- Same subnet passes on all tested hosts.
- Indicates VLAN path is consistent for tested hosts.

### Common failure patterns

1. Fails on one host, passes on others:
   - Likely host/uplink VLAN path inconsistency.

2. Fails on all hosts for one subnet:
   - Possible wrong subnet mapping, gateway issue, or blocked path.

3. Guest IP config fails before ping:
   - Guest-side issue (interface, permissions, route setup).

4. Migration succeeds but ping fails afterward:
   - Possible host-specific network path issue.

## Comparison with Script Results

When comparing manual vs script output, match on:

- Cluster
- Host
- Subnet extId / VLAN ID
- Test IP
- Gateway probe result

If mismatch occurs:

1. Re-check subnet mapping and free IP correctness.
2. Re-run one host manually.
3. If still mismatched, treat as investigation case.

## Do and Don't

Do:

- Use dedicated test VM only.
- Use reserved free IPs only.
- Record each host/subnet result clearly.

Don't:

- Do not test on production business VM.
- Do not reuse unknown IPs.
- Do not skip gateway verification after migration.

## Quick Result Template

Use this table format:

| Cluster | Host | Subnet Name | VLAN ID | Subnet extId | Test IP | Gateway | Ping Result | Notes |
|---|---|---|---|---|---|---|---|---|
| <cluster_name> | <host_name> | <subnet_name> | <vlan_id> | <subnet_extid> | <test_ip> | <gateway_ip> | PASS/FAIL | |

