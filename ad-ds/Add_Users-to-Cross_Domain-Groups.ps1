# filepath: Add-Members-to-Multiple-Groups.ps1
<#
.SYNOPSIS
    Adds users from a list to multiple specified Active Directory groups across multiple domains.

.DESCRIPTION
    This script reads usernames from a text file and group information from a CSV file, then adds 
    users to the specified groups. The script searches across all domains in the forest to find 
    users and handles cases where users or groups are not found. All inputs are collected via 
    interactive prompts.

.EXAMPLE
    .\Add-Members-to-Cross_Domain-Groups.ps1

.NOTES
    HOW TO RUN THIS SCRIPT:
    1. Create a text file with usernames (one per line)
    2. Create a CSV file with columns: GroupName,Domain
       Example:
       GroupName,Domain
       HR-Team,contoso.com
       Finance-Users,subsidiary.contoso.com
    3. Open PowerShell (as Administrator, if needed)
    4. Navigate to the script location: cd "C:\path\to\script"
    5. Run the script: .\Add-Members-to-Cross_Domain-Groups.ps1
    6. Follow the prompts to enter:
       - Path to users text file
       - Path to groups CSV file
       - Output directory path for reports

    Author: Areen Agrawal
    Version: 2.0
    Requires: ActiveDirectory PowerShell module
#>

Write-Host "`n=== AD MULTIPLE GROUP MEMBER ADDITION TOOL ===" -ForegroundColor Magenta
Write-Host "This script will add users from a list to multiple Active Directory groups" -ForegroundColor White
Write-Host "Users will be searched across all domains in the forest" -ForegroundColor White
Write-Host "Groups can be in different domains" -ForegroundColor White
Write-Host "================================================================`n" -ForegroundColor Magenta

# Prompt for Users File Path
do {
    $UsersFilePath = Read-Host "Enter the full path to the text file containing usernames (e.g., 'C:\Users.txt')"
} while ([string]::IsNullOrWhiteSpace($UsersFilePath))

# Verify users file exists
if (-not (Test-Path $UsersFilePath)) {
    Write-Error "Users file not found: $UsersFilePath"
    exit 1
}

# Prompt for Groups File Path
do {
    $GroupsFilePath = Read-Host "Enter the full path to the CSV file containing groups (e.g., 'C:\Groups.csv')"
} while ([string]::IsNullOrWhiteSpace($GroupsFilePath))

# Verify groups file exists
if (-not (Test-Path $GroupsFilePath)) {
    Write-Error "Groups file not found: $GroupsFilePath"
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

# Read users from file
try {
    $UserNames = Get-Content -Path $UsersFilePath -ErrorAction Stop
    if ($UserNames.Count -eq 0) {
        Write-Error "Users file is empty: $UsersFilePath"
        exit 1
    }
} catch {
    Write-Error "Failed to read users file: $($_.Exception.Message)"
    exit 1
}

# Read groups from CSV file
try {
    $Groups = Import-Csv -Path $GroupsFilePath -ErrorAction Stop
    if ($Groups.Count -eq 0) {
        Write-Error "Groups file is empty: $GroupsFilePath"
        exit 1
    }
    
    # Validate CSV structure
    if (-not ($Groups[0].PSObject.Properties.Name -contains "GroupName") -or 
        -not ($Groups[0].PSObject.Properties.Name -contains "Domain")) {
        Write-Error "Groups CSV file must contain 'GroupName' and 'Domain' columns"
        exit 1
    }
} catch {
    Write-Error "Failed to read groups file: $($_.Exception.Message)"
    exit 1
}

# Display entered parameters for confirmation
Write-Host "`n=== CONFIRMATION ===" -ForegroundColor Magenta
Write-Host "Users File: $UsersFilePath" -ForegroundColor White
Write-Host "Number of Users: $($UserNames.Count)" -ForegroundColor White
Write-Host "Groups File: $GroupsFilePath" -ForegroundColor White
Write-Host "Number of Groups: $($Groups.Count)" -ForegroundColor White
Write-Host "Output Directory: $OutputDirectory" -ForegroundColor White
Write-Host "`nTarget Groups:" -ForegroundColor White
foreach ($Group in $Groups) {
    Write-Host "  - $($Group.GroupName) in $($Group.Domain)" -ForegroundColor Cyan
}
Write-Host "==================`n" -ForegroundColor Magenta

$confirmation = Read-Host "Proceed with these parameters? (Y/N)"
if ($confirmation -notmatch '^[Yy]') {
    Write-Host "Script cancelled by user." -ForegroundColor Yellow
    exit 0
}

try {
    # Get all domains in the forest
    $Domains = (Get-ADForest).Domains
    
    # Verify all target groups exist
    $VerifiedGroups = @()
    $InvalidGroups = @()
    
    Write-Host "Verifying target groups..." -ForegroundColor Yellow
    foreach ($Group in $Groups) {
        try {
            $TargetGroup = Get-ADGroup -Identity $Group.GroupName -Server $Group.Domain -ErrorAction Stop
            $VerifiedGroups += [PSCustomObject]@{
                GroupName = $Group.GroupName
                Domain = $Group.Domain
                DistinguishedName = $TargetGroup.DistinguishedName
                GroupObject = $TargetGroup
            }
            Write-Host "  ✓ Group found: $($Group.GroupName) in $($Group.Domain)" -ForegroundColor Green
        } catch {
            $InvalidGroups += [PSCustomObject]@{
                GroupName = $Group.GroupName
                Domain = $Group.Domain
                Error = $_.Exception.Message
            }
            Write-Warning "  ✗ Group not found: $($Group.GroupName) in $($Group.Domain)"
        }
    }
    
    if ($InvalidGroups.Count -gt 0) {
        Write-Host "`nFound $($InvalidGroups.Count) invalid groups. Continue with valid groups only? (Y/N)" -ForegroundColor Yellow
        $continueConfirmation = Read-Host
        if ($continueConfirmation -notmatch '^[Yy]') {
            Write-Host "Script cancelled by user." -ForegroundColor Yellow
            exit 0
        }
    }
    
    if ($VerifiedGroups.Count -eq 0) {
        Write-Error "No valid groups found. Exiting."
        exit 1
    }
    
    # Initialize tracking arrays
    $AddedUsers = @()
    $NotFoundUsers = @()
    $FailedOperations = @()
    
    Write-Host "`nProcessing $($UserNames.Count) users across $($VerifiedGroups.Count) groups..." -ForegroundColor Yellow
    
    foreach ($UserName in $UserNames) {
        $UserName = $UserName.Trim()
        if ([string]::IsNullOrWhiteSpace($UserName)) {
            continue
        }
        
        $UserFound = $false
        $FoundUserObjects = @()
        
        Write-Host "`nProcessing user: $UserName" -ForegroundColor Cyan
        
        # Search for user across all domains
        foreach ($Domain in $Domains) {
            try {
                $Users = Get-ADUser -LDAPFilter "(anr=$UserName)" -Server $Domain -ErrorAction Stop
                
                foreach ($User in $Users) {
                    $FoundUserObjects += [PSCustomObject]@{
                        UserObject = $User
                        Domain = $Domain
                    }
                    $UserFound = $true
                    Write-Host "  Found user: $($User.SamAccountName) in $Domain" -ForegroundColor Green
                }
            } catch {
                continue
            }
        }
        
        if (-not $UserFound) {
            $NotFoundUsers += $UserName
            Write-Warning "  User not found in any domain: $UserName"
            continue
        }
        
        # Add each found user to each verified group
        foreach ($FoundUser in $FoundUserObjects) {
            foreach ($TargetGroup in $VerifiedGroups) {
                try {
                    Add-ADGroupMember -Identity $TargetGroup.GroupObject -Members $FoundUser.UserObject -Server $TargetGroup.Domain -ErrorAction Stop
                    $AddedUsers += [PSCustomObject]@{
                        Username = $FoundUser.UserObject.SamAccountName
                        DisplayName = $FoundUser.UserObject.Name
                        UserDomain = $FoundUser.Domain
                        GroupName = $TargetGroup.GroupName
                        GroupDomain = $TargetGroup.Domain
                        Status = "Added Successfully"
                        Timestamp = Get-Date
                    }
                    Write-Host "    ✓ Added to $($TargetGroup.GroupName) in $($TargetGroup.Domain)" -ForegroundColor Green
                } catch {
                    $FailedOperations += [PSCustomObject]@{
                        Username = $FoundUser.UserObject.SamAccountName
                        UserDomain = $FoundUser.Domain
                        GroupName = $TargetGroup.GroupName
                        GroupDomain = $TargetGroup.Domain
                        Error = $_.Exception.Message
                        Timestamp = Get-Date
                    }
                    Write-Warning "    ✗ Failed to add to $($TargetGroup.GroupName): $($_.Exception.Message)"
                }
            }
        }
    }
    
    # Generate reports
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    
    # Export added users
    if ($AddedUsers.Count -gt 0) {
        $AddedUsersPath = Join-Path $OutputDirectory "AddedUsers_$timestamp.csv"
        $AddedUsers | Export-Csv -Path $AddedUsersPath -NoTypeInformation
        Write-Host "`nSuccessfully completed $($AddedUsers.Count) user-group additions. Report: $AddedUsersPath" -ForegroundColor Green
    }
    
    # Export not found users
    if ($NotFoundUsers.Count -gt 0) {
        $NotFoundPath = Join-Path $OutputDirectory "NotFoundUsers_$timestamp.txt"
        $NotFoundUsers | Out-File -FilePath $NotFoundPath
        Write-Host "Users not found: $($NotFoundUsers.Count). Report: $NotFoundPath" -ForegroundColor Yellow
    }
    
    # Export failed operations
    if ($FailedOperations.Count -gt 0) {
        $FailedOperationsPath = Join-Path $OutputDirectory "FailedOperations_$timestamp.csv"
        $FailedOperations | Export-Csv -Path $FailedOperationsPath -NoTypeInformation
        Write-Host "Failed operations: $($FailedOperations.Count). Report: $FailedOperationsPath" -ForegroundColor Red
    }
    
    # Export invalid groups if any
    if ($InvalidGroups.Count -gt 0) {
        $InvalidGroupsPath = Join-Path $OutputDirectory "InvalidGroups_$timestamp.csv"
        $InvalidGroups | Export-Csv -Path $InvalidGroupsPath -NoTypeInformation
        Write-Host "Invalid groups: $($InvalidGroups.Count). Report: $InvalidGroupsPath" -ForegroundColor Red
    }
    
} catch {
    Write-Error "Script execution failed: $($_.Exception.Message)"
    exit 1
}

Write-Host "`n=== OPERATION COMPLETE ===" -ForegroundColor Magenta
Write-Host "Summary:" -ForegroundColor White
Write-Host "  Total User-Group Additions: $($AddedUsers.Count)" -ForegroundColor Green
Write-Host "  Users Not Found: $($NotFoundUsers.Count)" -ForegroundColor Yellow
Write-Host "  Failed Operations: $($FailedOperations.Count)" -ForegroundColor Red
Write-Host "  Invalid Groups: $($InvalidGroups.Count)" -ForegroundColor Red
Write-Host "  Valid Groups Processed: $($VerifiedGroups.Count)" -ForegroundColor Cyan
Write-Host "Check the output directory for detailed reports: $OutputDirectory" -ForegroundColor White

# --- END OF SCRIPT ---