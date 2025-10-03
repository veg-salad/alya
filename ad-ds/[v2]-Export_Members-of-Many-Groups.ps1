<#
.SYNOPSIS
    Exports members of multiple Active Directory groups from multiple domains to separate CSV files.

.DESCRIPTION
    This script retrieves all members of multiple specified Active Directory groups and exports
    their details (First Name, Last Name, Username, Email Address, Domain) to separate CSV files.
    The script searches across all domains in the forest to find user details.
    Groups can be from different domains. Group names and their domains are read from a CSV file.
    All inputs are collected via interactive prompts.

.EXAMPLE
    .\[v2]-Export_Members-of-Many-Groups.ps1

.NOTES
    HOW TO RUN THIS SCRIPT:
    1. Create a CSV file with columns: GroupName,Domain (one group per line)
    2. Open PowerShell (as Administrator, if needed)
    3. Navigate to the script location: cd "C:\path\to\script"
    4. Run the script: .\[v2]-Export_Members-of-Many-Groups.ps1
    5. Follow the prompts to enter:
       - Path to groups CSV file
       - Output directory path
    
    CSV FILE FORMAT:
    GroupName,Domain
    HR-Team,contoso.com
    IT-Admins,subsidiary.com
    Finance-Users,contoso.com
    
    For single group export, use "Export_Members-of-One-Group.ps1"
    For multiple groups from same domain, use "[v1]-Export_Members-of-Many-Groups.ps1"

    Author: Areen Agrawal
    Version: 2.0
    Requires: ActiveDirectory PowerShell module
#>

Write-Host "`n=== AD MULTIPLE DOMAINS GROUPS MEMBER EXPORT TOOL ===" -ForegroundColor Magenta
Write-Host "This script will export members of multiple Active Directory groups from multiple domains to separate CSV files" -ForegroundColor White
Write-Host "Each group will have its own CSV file named after the group" -ForegroundColor White
Write-Host "Groups can be from different domains" -ForegroundColor White
Write-Host "================================================================`n" -ForegroundColor Magenta

# Prompt for Groups CSV File Path
do {
    $GroupsFilePath = Read-Host "Enter the full path to the CSV file containing group names and domains (e.g., 'C:\Groups.csv')"
} while ([string]::IsNullOrWhiteSpace($GroupsFilePath))

# Verify file exists
if (-not (Test-Path $GroupsFilePath)) {
    Write-Error "Groups file not found: $GroupsFilePath"
    exit 1
}

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

# Read groups from CSV file
try {
    $GroupsList = Import-Csv -Path $GroupsFilePath -ErrorAction Stop
    if ($GroupsList.Count -eq 0) {
        Write-Error "Groups CSV file is empty: $GroupsFilePath"
        exit 1
    }
    
    # Validate CSV structure
    $requiredColumns = @('GroupName', 'Domain')
    $csvHeaders = $GroupsList[0].PSObject.Properties.Name
    $missingColumns = $requiredColumns | Where-Object { $_ -notin $csvHeaders }
    
    if ($missingColumns.Count -gt 0) {
        Write-Error "CSV file is missing required columns: $($missingColumns -join ', '). Required columns: GroupName, Domain"
        exit 1
    }
} catch {
    Write-Error "Failed to read groups CSV file: $($_.Exception.Message)"
    exit 1
}

# Display entered parameters for confirmation
Write-Host "`n=== CONFIRMATION ===" -ForegroundColor Magenta
Write-Host "Groups CSV File: $GroupsFilePath" -ForegroundColor White
Write-Host "Number of Groups: $($GroupsList.Count)" -ForegroundColor White
Write-Host "Output Directory: $OutputDirectory" -ForegroundColor White
Write-Host "`nGroups to process:" -ForegroundColor White
$GroupsList | ForEach-Object { Write-Host "  - $($_.GroupName) from $($_.Domain)" -ForegroundColor Cyan }
Write-Host "==================`n" -ForegroundColor Magenta

$confirmation = Read-Host "Proceed with these parameters? (Y/N)"
if ($confirmation -notmatch '^[Yy]') {
    Write-Host "Script cancelled by user." -ForegroundColor Yellow
    exit 0
}

try {
    # Get all domains in the forest
    $Domains = (Get-ADForest).Domains
    
    $GroupsList | ForEach-Object {
        $GroupName = $_.GroupName.Trim()
        $GroupDomain = $_.Domain.Trim()
        
        if ([string]::IsNullOrWhiteSpace($GroupName) -or [string]::IsNullOrWhiteSpace($GroupDomain)) {
            Write-Warning "Skipping row with empty GroupName or Domain"
            return
        }
        
        Write-Host "`nProcessing group: $GroupName from domain: $GroupDomain" -ForegroundColor Yellow
        
        try {
            # Get the Active Directory group and its members from specified domain
            $Group = Get-ADGroup $GroupName -Properties Members -Server $GroupDomain -ErrorAction Stop
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

            # Export to CSV file with domain prefix to avoid naming conflicts
            if ($MemberDetails.Count -gt 0) {
                $SafeGroupName = $GroupName -replace '[\\/:*?"<>|]', '_'
                $SafeDomainName = $GroupDomain -replace '[\\/:*?"<>|]', '_'
                $OutputPath = Join-Path $OutputDirectory "$SafeDomainName-$SafeGroupName.csv"
                $MemberDetails | Export-Csv -Path $OutputPath -NoTypeInformation -ErrorAction Stop
                Write-Host "Successfully exported $($MemberDetails.Count) members to: $OutputPath" -ForegroundColor Green
            } else {
                Write-Warning "No members found to export for group: $GroupName"
            }
        }
        catch {
            Write-Error "Failed to process group '$GroupName' from domain '$GroupDomain': $($_.Exception.Message)"
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