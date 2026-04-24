# SOP / KB: Manual AHV VLAN Validation via Prism Element (1-2 Hosts)

## Purpose

Use this SOP to manually validate VLAN/subnet connectivity in Nutanix AHV for a small check (for example, 1-2 hosts) and compare outcomes with the Windows-only automation script.

This follows the same logic as the script:

1. Open the target Prism Element cluster.
2. Validate VLAN-to-AHV-network mapping.
3. Attach the test VM NIC to one subnet.
4. Set the test IP inside the Windows guest.
5. Ping the default gateway from inside the guest.
6. Ping the test guest IP from the machine running the test.
7. Migrate the VM host-by-host and repeat both pings.

## Scope

- Platform: Nutanix AHV managed by Prism Element.
- Use case: Manual spot-check for one or two hosts.
- Goal: Verify per-host VLAN path health for selected subnets.

Not in scope:

- Full data center certification across all clusters/hosts.
- Deep network troubleshooting (LACP/LLDP/switch config analysis).

## Audience

- Junior to mid-level sysadmins.
- Basic familiarity with Prism Element navigation and Windows guest login.

## Prerequisites

- Access to Prism Element UI with permissions for:
  - VM view/edit
  - VM live migration
  - Network/subnet view
- Dedicated test VM (not a production VM), with:
   - SSH or WinRM access available
- Windows guest credentials with administrative privileges to change IP and route.
- Reserved free IPs for each subnet you test (from IPAM).
- A small test plan table (network name, VLAN ID, network UUID, free IP, gateway).

## Dependencies / Tools

- Web browser for Prism Element.
- SSH client (PuTTY/PowerShell/OpenSSH) or PowerShell Remoting/WinRM access.
- Notepad/Excel sheet to record results.

## Inputs You Need Before Starting

For each subnet/VLAN under test:

- Network name in Prism Element
- VLAN ID
- Network UUID
- Free test IP
- Prefix/mask
- Default gateway

For host checks:

- Cluster name or names
- 1-2 target AHV host names
- Windows Test VM name

## Safety Checks (Do This First)

1. Confirm the selected VM is a dedicated test VM.
2. Confirm you are in a maintenance-safe time window.
3. Confirm free test IPs are reserved and not in use.
4. Confirm you can log in to guest VM before making changes.

## Element Selection

Before testing, choose the exact Prism Element cluster you want to verify. For multi-cluster testing, repeat the procedure one Element at a time and combine the results.

Guidance:

- Record the Element IP/FQDN and cluster name.
- Use the same network names and UUIDs when comparing manual results to script output.

## Step-by-Step Procedure

### Step 1: Validate network and VLAN mapping in Prism Element

1. Open Prism Element.
2. Go to VM networking / networks.
3. Search for the target AHV network.
4. Confirm:
   - Network UUID
   - VLAN ID
   - Prefix/mask from the test plan
   - Default gateway from the test plan
5. Repeat for each network you will test.

Pass criteria:

- VLAN ID and network details match your test plan.

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

From PowerShell inside the Windows guest:

```powershell
Get-NetIPAddress -InterfaceAlias <INTERFACE> -AddressFamily IPv4 -ErrorAction SilentlyContinue | Remove-NetIPAddress -Confirm:$false
Get-NetRoute -InterfaceAlias <INTERFACE> -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Remove-NetRoute -Confirm:$false
New-NetIPAddress -InterfaceAlias <INTERFACE> -IPAddress <FREE_IP> -PrefixLength <PREFIX> -DefaultGateway <GATEWAY> -AddressFamily IPv4
Get-NetIPAddress -InterfaceAlias <INTERFACE> -AddressFamily IPv4
Get-NetRoute -InterfaceAlias <INTERFACE> -AddressFamily IPv4
```

Replace:

- `<FREE_IP>` with reserved test IP
- `<PREFIX>` with subnet prefix (for example `24`)
- `<GATEWAY>` with subnet default gateway

Pass criteria:

- The selected Windows interface shows correct IP/prefix.
- Default route points to expected gateway.

### Step 5: Probe gateway from guest (baseline)

Run from the Windows guest:

```powershell
Test-Connection -ComputerName <GATEWAY> -Count 3 -Quiet
```

Pass criteria:

- The command returns `True` or shows successful replies.

### Step 6: Probe test guest from execution machine (baseline)

From the machine where you are running the validation:

```powershell
Test-Connection -ComputerName <FREE_IP> -Count 3 -Quiet
```

Pass criteria:

- The command returns `True` or shows successful replies.

Record result as:

- Cluster
- Current host
- Network/VLAN
- Test IP
- Gateway
- Ping result (PASS/FAIL)

### Step 7: Migrate VM to Host 1 and retest

1. In Prism VM actions, select Live Migrate.
2. Choose Host 1.
3. Wait until VM placement shows Host 1.
4. Wait 10-20 seconds.
5. Run gateway ping again from guest.
6. Run test guest ping again from execution machine.

Pass criteria:

- Both pings are successful.

### Step 8: Migrate VM to Host 2 and retest

Repeat Step 7 for Host 2.

Pass criteria:

- Both pings successful on Host 2 as well.

### Step 9: Repeat for next network

1. Re-attach VM NIC to next AHV network.
2. Reconfigure guest IP/route for that network.
3. Repeat guest ping, execution-machine ping, and migration checks.

## Result Interpretation

### Expected good outcome

- Same network passes on all tested hosts.
- Indicates VLAN path is consistent for tested hosts.

### Common failure patterns

1. Fails on one host, passes on others:
   - Likely host/uplink VLAN path inconsistency.

2. Fails on all hosts for one network:
   - Possible wrong network mapping, gateway issue, or blocked path.

3. Guest IP config fails before ping:
   - Guest-side issue (interface, permissions, route setup).

4. Migration succeeds but ping fails afterward:
   - Possible host-specific network path issue.

5. Guest-to-gateway ping passes, but execution-machine-to-guest ping fails:
   - Likely upstream routing/firewall/security path issue between execution machine and guest network.

## Comparison with Script Results

When comparing manual vs script output, match on:

- Cluster
- Host
- Network UUID / VLAN ID
- Test IP
- Guest-to-gateway probe result
- Runner-to-guest probe result

If mismatch occurs:

1. Re-check network mapping and free IP correctness.
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

| Element | Cluster | Host | Network Name | VLAN ID | Network UUID | Test IP | Gateway | Ping Result | Notes |
|---|---|---|---|---|---|---|---|---|---|
| <element_ip> | <cluster_name> | <host_name> | <network_name> | <vlan_id> | <network_uuid> | <test_ip> | <gateway_ip> | PASS/FAIL | |

