<#
.SYNOPSIS
    Adds users from a list to a specified Active Directory group across multiple domains.

.DESCRIPTION
    This script reads usernames from a text file and adds them to a specified Active Directory group.
    The script searches across all domains in the forest to find users and handles cases where
    users are not found. All inputs are collected via interactive prompts.

.EXAMPLE
    .\Add-Users-to-Group.ps1

.NOTES
    HOW TO RUN THIS SCRIPT:
    1. Create a text file with usernames (one per line)
    2. Open PowerShell (as Administrator, if needed)
    3. Navigate to the script location: cd "C:\path\to\script"
    4. Run the script: .\Add-Users-to-Group.ps1
    5. Follow the prompts to enter:
       - Path to users text file
       - Group name
       - Domain name for the group
       - Output directory path for reports

    Author: Areen Agrawal
    Version: 1.0
    Requires: ActiveDirectory PowerShell module
#>

Write-Host "`n=== AD GROUP MEMBER ADDITION TOOL ===" -ForegroundColor Magenta
Write-Host "This script will add users from a list to a specified Active Directory group" -ForegroundColor White
Write-Host "Users will be searched across all domains in the forest" -ForegroundColor White
Write-Host "================================================================`n" -ForegroundColor Magenta

# Prompt for Users File Path
do {
    $UsersFilePath = Read-Host "Enter the full path to the text file containing usernames (e.g., 'C:\Users.txt')"
} while ([string]::IsNullOrWhiteSpace($UsersFilePath))

# Verify file exists
if (-not (Test-Path $UsersFilePath)) {
    Write-Error "Users file not found: $UsersFilePath"
    exit 1
}

# Prompt for Group Name
do {
    $GroupName = Read-Host "Enter the Active Directory group name"
} while ([string]::IsNullOrWhiteSpace($GroupName))

# Prompt for Group Domain
do {
    $GroupDomain = Read-Host "Enter the domain name where the group exists (e.g., 'contoso.com')"
} while ([string]::IsNullOrWhiteSpace($GroupDomain))

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

# Display entered parameters for confirmation
Write-Host "`n=== CONFIRMATION ===" -ForegroundColor Magenta
Write-Host "Users File: $UsersFilePath" -ForegroundColor White
Write-Host "Number of Users: $($UserNames.Count)" -ForegroundColor White
Write-Host "Target Group: $GroupName" -ForegroundColor White
Write-Host "Group Domain: $GroupDomain" -ForegroundColor White
Write-Host "Output Directory: $OutputDirectory" -ForegroundColor White
Write-Host "==================`n" -ForegroundColor Magenta

$confirmation = Read-Host "Proceed with these parameters? (Y/N)"
if ($confirmation -notmatch '^[Yy]') {
    Write-Host "Script cancelled by user." -ForegroundColor Yellow
    exit 0
}

try {
    # Get all domains in the forest
    $Domains = (Get-ADForest).Domains
    
    # Verify target group exists
    try {
        $TargetGroup = Get-ADGroup -Identity $GroupName -Server $GroupDomain -ErrorAction Stop
        Write-Host "Target group found: $($TargetGroup.Name)" -ForegroundColor Green
    } catch {
        Write-Error "Target group '$GroupName' not found in domain '$GroupDomain'"
        exit 1
    }
    
    # Initialize tracking arrays
    $AddedUsers = @()
    $NotFoundUsers = @()
    $FailedUsers = @()
    
    Write-Host "`nProcessing $($UserNames.Count) users..." -ForegroundColor Yellow
    
    foreach ($UserName in $UserNames) {
        $UserName = $UserName.Trim()
        if ([string]::IsNullOrWhiteSpace($UserName)) {
            continue
        }
        
        $UserFound = $false
        $UserAdded = $false
        
        Write-Host "Processing user: $UserName" -ForegroundColor Cyan
        
        # Search for user across all domains
        foreach ($Domain in $Domains) {
            try {
                $Users = Get-ADUser -LDAPFilter "(anr=$UserName)" -Server $Domain -ErrorAction Stop
                
                foreach ($User in $Users) {
                    try {
                        Add-ADGroupMember -Identity $TargetGroup -Members $User -Server $GroupDomain -ErrorAction Stop
                        $AddedUsers += [PSCustomObject]@{
                            Username = $User.SamAccountName
                            DisplayName = $User.Name
                            Domain = $Domain
                            Status = "Added Successfully"
                        }
                        Write-Host "  Successfully added: $($User.SamAccountName) from $Domain" -ForegroundColor Green
                        $UserFound = $true
                        $UserAdded = $true
                    } catch {
                        $FailedUsers += [PSCustomObject]@{
                            Username = $UserName
                            Domain = $Domain
                            Error = $_.Exception.Message
                        }
                        Write-Warning "  Failed to add $($User.SamAccountName): $($_.Exception.Message)"
                        $UserFound = $true
                    }
                }
                
                if ($UserAdded) {
                    break
                }
            } catch {
                continue
            }
        }
        
        if (-not $UserFound) {
            $NotFoundUsers += $UserName
            Write-Warning "  User not found in any domain: $UserName"
        }
    }
    
    # Generate reports
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    
    # Export added users
    if ($AddedUsers.Count -gt 0) {
        $AddedUsersPath = Join-Path $OutputDirectory "AddedUsers_$timestamp.csv"
        $AddedUsers | Export-Csv -Path $AddedUsersPath -NoTypeInformation
        Write-Host "`nSuccessfully added $($AddedUsers.Count) users. Report: $AddedUsersPath" -ForegroundColor Green
    }
    
    # Export not found users
    if ($NotFoundUsers.Count -gt 0) {
        $NotFoundPath = Join-Path $OutputDirectory "NotFoundUsers_$timestamp.txt"
        $NotFoundUsers | Out-File -FilePath $NotFoundPath
        Write-Host "Users not found: $($NotFoundUsers.Count). Report: $NotFoundPath" -ForegroundColor Yellow
    }
    
    # Export failed users
    if ($FailedUsers.Count -gt 0) {
        $FailedUsersPath = Join-Path $OutputDirectory "FailedUsers_$timestamp.csv"
        $FailedUsers | Export-Csv -Path $FailedUsersPath -NoTypeInformation
        Write-Host "Failed to add: $($FailedUsers.Count) users. Report: $FailedUsersPath" -ForegroundColor Red
    }
    
} catch {
    Write-Error "Script execution failed: $($_.Exception.Message)"
    exit 1
}

Write-Host "`n=== OPERATION COMPLETE ===" -ForegroundColor Magenta
Write-Host "Summary:" -ForegroundColor White
Write-Host "  Users Added: $($AddedUsers.Count)" -ForegroundColor Green
Write-Host "  Users Not Found: $($NotFoundUsers.Count)" -ForegroundColor Yellow
Write-Host "  Users Failed: $($FailedUsers.Count)" -ForegroundColor Red
Write-Host "Check the output directory for detailed reports: $OutputDirectory" -ForegroundColor White

# --- END OF SCRIPT ---