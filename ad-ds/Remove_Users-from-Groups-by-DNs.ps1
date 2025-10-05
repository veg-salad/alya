<#
.SYNOPSIS
    Removes users from specified Active Directory groups across multiple domains using Distinguished Names.

.DESCRIPTION
    This script reads user DNs and group information from a CSV file, then removes users from the 
    specified groups. The script uses the Distinguished Name (DN) to directly identify users without 
    searching across domains. All inputs are collected via interactive prompts.

.EXAMPLE
    .\Remove_Users-from-Groups-by-DNs.ps1

.NOTES
    HOW TO RUN THIS SCRIPT:
    1. Create a CSV file with columns: UserDN,GroupName,Domain
       Example:
       UserDN,GroupName,Domain
       "CN=John Doe,OU=Users,DC=contoso,DC=com",HR-Team,contoso.com
       "CN=Jane Smith,OU=Users,DC=subsidiary,DC=contoso,DC=com",Finance-Users,subsidiary.contoso.com
    2. Open PowerShell (as Administrator, if needed)
    3. Navigate to the script location: cd "C:\path\to\script"
    4. Run the script: .\Remove_Users-from-Groups-by-DNs.ps1
    5. Follow the prompts to enter:
       - Path to CSV file
       - Output directory path for reports

    Author: Areen Agrawal
    Version: 3.0
    Requires: ActiveDirectory PowerShell module
#>

Write-Host "`n=== AD MULTIPLE GROUP MEMBER REMOVAL TOOL ===" -ForegroundColor Magenta
Write-Host "This script will remove users from Active Directory groups using Distinguished Names" -ForegroundColor White
Write-Host "Users are identified by their DN, groups can be in different domains" -ForegroundColor White
Write-Host "================================================================`n" -ForegroundColor Magenta

# Prompt for CSV File Path
do {
    $CsvFilePath = Read-Host "Enter the full path to the CSV file (e.g., 'C:\UsersGroups.csv')"
} while ([string]::IsNullOrWhiteSpace($CsvFilePath))

# Verify CSV file exists
if (-not (Test-Path $CsvFilePath)) {
    Write-Error "CSV file not found: $CsvFilePath"
    exit 1
}

# Prompt for Output Directory
do {
    $OutputDirectory = Read-Host "Enter the directory path for output reports (e.g., 'C:\Reports')"
} while ([string]::IsNullOrWhiteSpace($OutputDirectory))

# Verify/create output directory
if (-not (Test-Path $OutputDirectory)) {
    try {
        New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
        Write-Host "Created output directory: $OutputDirectory" -ForegroundColor Green
    } catch {
        Write-Error "Failed to create output directory: $OutputDirectory"
        exit 1
    }
}

# Read entries from CSV file
try {
    $Entries = Import-Csv -Path $CsvFilePath -ErrorAction Stop
    if ($Entries.Count -eq 0) {
        Write-Error "CSV file is empty: $CsvFilePath"
        exit 1
    }
    
    # Validate CSV structure
    if (-not ($Entries[0].PSObject.Properties.Name -contains "UserDN") -or 
        -not ($Entries[0].PSObject.Properties.Name -contains "GroupName") -or
        -not ($Entries[0].PSObject.Properties.Name -contains "Domain")) {
        Write-Error "CSV file must contain 'UserDN', 'GroupName', and 'Domain' columns"
        exit 1
    }
} catch {
    Write-Error "Failed to read CSV file: $($_.Exception.Message)"
    exit 1
}

# Display entered parameters for confirmation
Write-Host "`n=== CONFIRMATION ===" -ForegroundColor Magenta
Write-Host "CSV File: $CsvFilePath" -ForegroundColor White
Write-Host "Number of Entries: $($Entries.Count)" -ForegroundColor White
Write-Host "Output Directory: $OutputDirectory" -ForegroundColor White
Write-Host "`nSample Entries:" -ForegroundColor White
$Entries | Select-Object -First 5 | ForEach-Object {
    Write-Host "  - User: $($_.UserDN)" -ForegroundColor Cyan
    Write-Host "    Group: $($_.GroupName) in $($_.Domain)" -ForegroundColor Cyan
}
if ($Entries.Count -gt 5) {
    Write-Host "  ... and $($Entries.Count - 5) more entries" -ForegroundColor Cyan
}
Write-Host "==================`n" -ForegroundColor Magenta

$confirmation = Read-Host "Proceed with REMOVAL operations? (Y/N)"
if ($confirmation -notmatch '^[Yy]') {
    Write-Host "Script cancelled by user." -ForegroundColor Yellow
    exit 0
}

try {
    # Initialize tracking arrays
    $RemovedUsers = @()
    $NotFoundUsers = @()
    $NotFoundGroups = @()
    $FailedOperations = @()
    
    Write-Host "`nProcessing $($Entries.Count) removal operations..." -ForegroundColor Yellow
    
    $entryCounter = 0
    foreach ($Entry in $Entries) {
        $entryCounter++
        $UserDN = $Entry.UserDN.Trim()
        $GroupName = $Entry.GroupName.Trim()
        $Domain = $Entry.Domain.Trim()
        
        if ([string]::IsNullOrWhiteSpace($UserDN) -or 
            [string]::IsNullOrWhiteSpace($GroupName) -or 
            [string]::IsNullOrWhiteSpace($Domain)) {
            Write-Warning "[$entryCounter/$($Entries.Count)] Skipping entry with empty values"
            continue
        }
        
        Write-Host "`n[$entryCounter/$($Entries.Count)] Processing:" -ForegroundColor Cyan
        Write-Host "  User DN: $UserDN" -ForegroundColor White
        Write-Host "  Group: $GroupName in $Domain" -ForegroundColor White
        
        # Verify user exists
        try {
            # Extract domain from DN
            $UserDomainDN = ($UserDN -split ',DC=')[1..999] -join '.'
            $User = Get-ADUser -Identity $UserDN -Server $UserDomainDN -ErrorAction Stop
        } catch {
            $NotFoundUsers += [PSCustomObject]@{
                UserDN = $UserDN
                GroupName = $GroupName
                Domain = $Domain
                Error = $_.Exception.Message
                Timestamp = Get-Date
            }
            Write-Warning "  ✗ User not found: $UserDN"
            continue
        }
        
        # Verify group exists
        try {
            $Group = Get-ADGroup -Identity $GroupName -Server $Domain -ErrorAction Stop
        } catch {
            $NotFoundGroups += [PSCustomObject]@{
                UserDN = $UserDN
                GroupName = $GroupName
                Domain = $Domain
                Error = $_.Exception.Message
                Timestamp = Get-Date
            }
            Write-Warning "  ✗ Group not found: $GroupName in $Domain"
            continue
        }
        
        # Remove user from group
        try {
            Remove-ADGroupMember -Identity $Group -Members $User -Server $Domain -Confirm:$false -ErrorAction Stop
            $RemovedUsers += [PSCustomObject]@{
                Username = $User.SamAccountName
                DisplayName = $User.Name
                UserDN = $UserDN
                GroupName = $GroupName
                GroupDomain = $Domain
                GroupDN = $Group.DistinguishedName
                Status = "Removed Successfully"
                Timestamp = Get-Date
            }
            Write-Host "  ✓ Successfully removed from $GroupName" -ForegroundColor Green
        } catch {
            $FailedOperations += [PSCustomObject]@{
                Username = $User.SamAccountName
                UserDN = $UserDN
                GroupName = $GroupName
                GroupDomain = $Domain
                Error = $_.Exception.Message
                Timestamp = Get-Date
            }
            Write-Warning "  ✗ Failed to remove: $($_.Exception.Message)"
        }
    }
    
    # Generate reports
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    
    # Export removed users
    if ($RemovedUsers.Count -gt 0) {
        $RemovedUsersPath = Join-Path $OutputDirectory "RemovedUsers_$timestamp.csv"
        $RemovedUsers | Export-Csv -Path $RemovedUsersPath -NoTypeInformation
        Write-Host "`nSuccessfully completed $($RemovedUsers.Count) user-group removals. Report: $RemovedUsersPath" -ForegroundColor Green
    }
    
    # Export not found users
    if ($NotFoundUsers.Count -gt 0) {
        $NotFoundUsersPath = Join-Path $OutputDirectory "NotFoundUsers_$timestamp.csv"
        $NotFoundUsers | Export-Csv -Path $NotFoundUsersPath -NoTypeInformation
        Write-Host "Users not found: $($NotFoundUsers.Count). Report: $NotFoundUsersPath" -ForegroundColor Yellow
    }
    
    # Export not found groups
    if ($NotFoundGroups.Count -gt 0) {
        $NotFoundGroupsPath = Join-Path $OutputDirectory "NotFoundGroups_$timestamp.csv"
        $NotFoundGroups | Export-Csv -Path $NotFoundGroupsPath -NoTypeInformation
        Write-Host "Groups not found: $($NotFoundGroups.Count). Report: $NotFoundGroupsPath" -ForegroundColor Yellow
    }
    
    # Export failed operations
    if ($FailedOperations.Count -gt 0) {
        $FailedOperationsPath = Join-Path $OutputDirectory "FailedOperations_$timestamp.csv"
        $FailedOperations | Export-Csv -Path $FailedOperationsPath -NoTypeInformation
        Write-Host "Failed operations: $($FailedOperations.Count). Report: $FailedOperationsPath" -ForegroundColor Red
    }
    
} catch {
    Write-Error "Script execution failed: $($_.Exception.Message)"
    exit 1
}

Write-Host "`n=== OPERATION COMPLETE ===" -ForegroundColor Magenta
Write-Host "Summary:" -ForegroundColor White
Write-Host "  Total User-Group Removals: $($RemovedUsers.Count)" -ForegroundColor Green
Write-Host "  Users Not Found: $($NotFoundUsers.Count)" -ForegroundColor Yellow
Write-Host "  Groups Not Found: $($NotFoundGroups.Count)" -ForegroundColor Yellow
Write-Host "  Failed Operations: $($FailedOperations.Count)" -ForegroundColor Red
Write-Host "Check the output directory for detailed reports: $OutputDirectory" -ForegroundColor White

# --- END OF SCRIPT ---