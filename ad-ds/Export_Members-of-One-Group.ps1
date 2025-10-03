<#
.SYNOPSIS
    Exports members of a single Active Directory group to CSV file.

.DESCRIPTION
    This script retrieves all members of a specified Active Directory group and exports
    their details (First Name, Last Name, Username, Email Address, Domain) to a CSV file.
    The script searches across all domains in the forest to find user details.
    All inputs are collected via interactive prompts.

.EXAMPLE
    .\Export_Members-of-One-Group.ps1

.NOTES
    HOW TO RUN THIS SCRIPT:
    1. Open PowerShell (as Administrator, if needed)
    2. Navigate to the script location: cd "C:\path\to\script"
    3. Run the script: .\Export_Members-of-One-Group.ps1
    4. Follow the prompts to enter:
       - Active Directory group name
       - Domain name
       - Output CSV file path
    
    For multiple groups in same domain, use "[v1]-Export_Members-of-Many-Groups.ps1"
    For multiple groups across multiple domains, use "[v2]-Export_Members-of-Many-Groups.ps1"

    Author: Areen Agrawal
    Version: 1.0
    Requires: ActiveDirectory PowerShell module
#>

Write-Host "`n=== AD GROUP MEMBER EXPORT TOOL ===" -ForegroundColor Magenta
Write-Host "This script will export members of an Active Directory group to CSV" -ForegroundColor White
Write-Host "========================================`n" -ForegroundColor Magenta

# Prompt for Group Name
do {
    $GroupName = Read-Host "Enter the Active Directory group name (e.g., 'IT-Admins')"
} while ([string]::IsNullOrWhiteSpace($GroupName))

# Prompt for Domain Controller
do {
    $DomainController = Read-Host "Enter the domain name (e.g., 'contoso.com')"
} while ([string]::IsNullOrWhiteSpace($DomainController))

# Prompt for Output Path
do {
    $OutputPath = Read-Host "Enter the full path for output CSV file (e.g., 'C:\Reports\output.csv')"
} while ([string]::IsNullOrWhiteSpace($OutputPath))

# Display entered parameters for confirmation
Write-Host "`n=== CONFIRMATION ===" -ForegroundColor Magenta
Write-Host "Group Name: $GroupName" -ForegroundColor White
Write-Host "Domain: $DomainController" -ForegroundColor White
Write-Host "Output Path: $OutputPath" -ForegroundColor White
Write-Host "==================`n" -ForegroundColor Magenta

$confirmation = Read-Host "Proceed with these parameters? (Y/N)"
if ($confirmation -notmatch '^[Yy]') {
    Write-Host "Script cancelled by user." -ForegroundColor Yellow
    exit 0
}

try {
    # Get the Active Directory group and its members
    Write-Host "Retrieving group: $GroupName from domain: $DomainController" -ForegroundColor Green
    $Group = Get-ADGroup $GroupName -Properties Members -Server $DomainController -ErrorAction Stop
    
    # Get all domains in the forest
    $Domains = (Get-ADForest).Domains
    $MemberDetails = @()

    Write-Host "Processing $($Group.Members.Count) group members..." -ForegroundColor Yellow

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
            Write-Host "Found user: $($UserDetail.Username)" -ForegroundColor Cyan
        } else {
            Write-Warning "User not found in any domain: $member"
        }
    }

    # Export to CSV file
    if ($MemberDetails.Count -gt 0) {
        $MemberDetails | Export-Csv -Path $OutputPath -NoTypeInformation -ErrorAction Stop
        Write-Host "Successfully exported $($MemberDetails.Count) members to: $OutputPath" -ForegroundColor Green
    } else {
        Write-Warning "No members found to export."
    }
}
catch {
    Write-Error "Script execution failed: $($_.Exception.Message)"
    exit 1
}

# --- END OF SCRIPT ---