<#
.SYNOPSIS
    Exports members of multiple Active Directory groups (same domain) to separate CSV files.

.DESCRIPTION
    This script retrieves all members of multiple specified Active Directory groups and exports
    their details (First Name, Last Name, Username, Email Address, Domain) to separate CSV files.
    The script searches across all domains in the forest to find user details.
    Groups must be from the same domain. Group names are read from a text file.
    All inputs are collected via interactive prompts.

.EXAMPLE
    .\[v1]-Export_Members-of-Many-Groups.ps1

.NOTES
    HOW TO RUN THIS SCRIPT:
    1. Create a text file with group names (one per line)
    2. Open PowerShell (as Administrator, if needed)
    3. Navigate to the script location: cd "C:\path\to\script"
    4. Run the script: .\[v1]-Export_Members-of-Many-Groups.ps1
    5. Follow the prompts to enter:
       - Path to groups text file
       - Domain name
       - Output directory path
    
    For single group export, use "Export_Members-of-One-Group.ps1"
    For multiple groups across multiple domains, use "[v2]-Export_Members-of-Many-Groups.ps1"

    Author: Areen Agrawal
    Version: 1.0
    Requires: ActiveDirectory PowerShell module
#>

Write-Host "`n=== AD MULTIPLE GROUPS MEMBER EXPORT TOOL ===" -ForegroundColor Magenta
Write-Host "This script will export members of multiple Active Directory groups to separate CSV files" -ForegroundColor White
Write-Host "Each group will have its own CSV file named after the group" -ForegroundColor White
Write-Host "================================================================`n" -ForegroundColor Magenta

# Prompt for Groups File Path
do {
    $GroupsFilePath = Read-Host "Enter the full path to the text file containing group names (e.g., 'C:\Groups.txt')"
} while ([string]::IsNullOrWhiteSpace($GroupsFilePath))

# Verify file exists
if (-not (Test-Path $GroupsFilePath)) {
    Write-Error "Groups file not found: $GroupsFilePath"
    exit 1
}

# Prompt for Domain Controller
do {
    $DomainController = Read-Host "Enter the domain name for all groups (e.g., 'contoso.com')"
} while ([string]::IsNullOrWhiteSpace($DomainController))

# Prompt for Output Directory
do {
    $OutputDirectory = Read-Host "Enter the directory path for output CSV files (e.g., 'C:\Reports')"
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

# Read groups from file
try {
    $ListOfGroups = Get-Content -Path $GroupsFilePath -ErrorAction Stop
    if ($ListOfGroups.Count -eq 0) {
        Write-Error "Groups file is empty: $GroupsFilePath"
        exit 1
    }
} catch {
    Write-Error "Failed to read groups file: $($_.Exception.Message)"
    exit 1
}

# Display entered parameters for confirmation
Write-Host "`n=== CONFIRMATION ===" -ForegroundColor Magenta
Write-Host "Groups File: $GroupsFilePath" -ForegroundColor White
Write-Host "Number of Groups: $($ListOfGroups.Count)" -ForegroundColor White
Write-Host "Domain: $DomainController" -ForegroundColor White
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
    
    $ListOfGroups | ForEach-Object {
        $GroupName = $_.Trim()
        if ([string]::IsNullOrWhiteSpace($GroupName)) {
            return
        }
        
        Write-Host "`nProcessing group: $GroupName" -ForegroundColor Yellow
        
        try {
            # Get the Active Directory group and its members
            $Group = Get-ADGroup $GroupName -Properties Members -Server $DomainController -ErrorAction Stop
            $MemberDetails = @()

            Write-Host "Found $($Group.Members.Count) members in group: $GroupName" -ForegroundColor Cyan

            foreach ($member in $Group.Members) {
                $UserFound = $false
                $UserDetail = $null

                # Search for the user across all domains in the forest
                foreach ($domain in $Domains) {
                    try {
                        $User = Get-ADUser -Identity $member -Properties GivenName, Surname, EmailAddress, UserPrincipalName -Server $domain -ErrorAction Stop
                        $UserFound = $true
                        
                        # Extract username and domain from UPN
                        if ($User.UserPrincipalName) {
                            $Username, $UserDomain = $User.UserPrincipalName.Split('@')
                        } else {
                            $Username = $User.SamAccountName
                            $UserDomain = $domain
                        }

                        # Create user detail object
                        $UserDetail = [PSCustomObject]@{
                            "First Name"    = $User.GivenName
                            "Last Name"     = $User.Surname
                            "Username"      = $Username
                            "Email Address" = $User.EmailAddress
                            "Domain"        = $UserDomain
                        }
                        break
                    }
                    catch [Microsoft.ActiveDirectory.Management.ADIdentityNotFoundException] {
                        continue
                    }
                    catch {
                        Write-Warning "Error querying domain $domain for user $member`: $($_.Exception.Message)"
                        continue
                    }
                }

                if ($UserFound -and $UserDetail) {
                    $MemberDetails += $UserDetail
                    Write-Host "  Found user: $($UserDetail.Username)" -ForegroundColor Green
                } else {
                    Write-Warning "  User not found in any domain: $member"
                }
            }

            # Export to CSV file
            if ($MemberDetails.Count -gt 0) {
                $OutputPath = Join-Path $OutputDirectory "$GroupName.csv"
                $MemberDetails | Export-Csv -Path $OutputPath -NoTypeInformation -ErrorAction Stop
                Write-Host "Successfully exported $($MemberDetails.Count) members to: $OutputPath" -ForegroundColor Green
            } else {
                Write-Warning "No members found to export for group: $GroupName"
            }
        }
        catch {
            Write-Error "Failed to process group '$GroupName': $($_.Exception.Message)"
        }
    }
}
catch {
    Write-Error "Script execution failed: $($_.Exception.Message)"
    exit 1
}

Write-Host "`n=== EXPORT COMPLETE ===" -ForegroundColor Magenta
Write-Host "All group member exports have been completed." -ForegroundColor Green
Write-Host "Check the output directory for CSV files: $OutputDirectory" -ForegroundColor White

# --- END OF SCRIPT ---