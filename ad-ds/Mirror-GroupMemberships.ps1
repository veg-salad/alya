<#
.SYNOPSIS
    Copies Active Directory group memberships from one user to another.

.DESCRIPTION
    This script retrieves all group memberships from a source user and applies them
    to a target user in Active Directory. It includes proper error handling,
    input validation, and user confirmation before making changes.

.EXAMPLE
    .\Permissions-Mirroring.ps1

.NOTES
    HOW TO RUN THIS SCRIPT:
    1. Open PowerShell (as Administrator, if needed)
    2. Navigate to the script location: cd "C:\path\to\script"
    3. Run the script: .\Mirror-GroupMemberships.ps1
    4. Follow the prompts to enter:
       - Domain name
       - Source username (copying from)
       - Target username (pasting to)
    
    Author: Areen Agrawal
    Version: 2.0
    Requires: ActiveDirectory PowerShell module
#>

Write-Host "`n=== AD GROUP MEMBERSHIP MIRRORING TOOL ===" -ForegroundColor Magenta
Write-Host "This script will copy group memberships from one user to another" -ForegroundColor White
Write-Host "==================================================`n" -ForegroundColor Magenta

# Prompt for Domain Name
do {
    $DomainName = Read-Host "Enter the domain name (e.g., 'contoso.com')"
} while ([string]::IsNullOrWhiteSpace($DomainName))

# Prompt for Source User
do {
    $SourceUser = Read-Host "Enter the username of the existing user (copying from)"
} while ([string]::IsNullOrWhiteSpace($SourceUser))

# Prompt for Target User
do {
    $TargetUser = Read-Host "Enter the username of the new user (pasting to)"
} while ([string]::IsNullOrWhiteSpace($TargetUser))

# Display entered parameters for confirmation
Write-Host "`n=== CONFIRMATION ===" -ForegroundColor Magenta
Write-Host "Domain: $DomainName" -ForegroundColor White
Write-Host "Source User (copying from): $SourceUser" -ForegroundColor White
Write-Host "Target User (pasting to): $TargetUser" -ForegroundColor White
Write-Host "==================`n" -ForegroundColor Magenta

$confirmation = Read-Host "Proceed with copying group memberships? (Y/N)"
if ($confirmation -notmatch '^[Yy]') {
    Write-Host "Script cancelled by user." -ForegroundColor Yellow
    exit 0
}

try {
    # Verify both users exist
    Write-Host "Verifying users exist..." -ForegroundColor Yellow
    
    $SourceUserObj = Get-ADUser $SourceUser -Server $DomainName -ErrorAction Stop
    $TargetUserObj = Get-ADUser $TargetUser -Server $DomainName -ErrorAction Stop
    
    Write-Host "Source user found: $($SourceUserObj.Name)" -ForegroundColor Cyan
    Write-Host "Target user found: $($TargetUserObj.Name)" -ForegroundColor Cyan

    # Get source user's group memberships
    Write-Host "`nRetrieving group memberships from source user..." -ForegroundColor Green
    $SourceGroups = Get-ADPrincipalGroupMembership $SourceUserObj -Server $DomainName
    
    if ($SourceGroups.Count -eq 0) {
        Write-Warning "Source user has no group memberships to copy."
        exit 0
    }

    Write-Host "Found $($SourceGroups.Count) group(s) to copy" -ForegroundColor Yellow

    # Get target user's current group memberships for comparison
    $TargetGroups = Get-ADPrincipalGroupMembership $TargetUserObj -Server $DomainName
    $TargetGroupNames = $TargetGroups | ForEach-Object { $_.Name }

    $SuccessCount = 0
    $SkippedCount = 0
    $ErrorCount = 0

    Write-Host "`nCopying group memberships..." -ForegroundColor Green

    foreach ($Group in $SourceGroups) {
        try {
            if ($Group.Name -in $TargetGroupNames) {
                Write-Host "Skipped: $($Group.Name) (already a member)" -ForegroundColor DarkYellow
                $SkippedCount++
            }
            else {
                Add-ADGroupMember -Identity $Group -Members $TargetUserObj -Server $DomainName -ErrorAction Stop
                Write-Host "Added to: $($Group.Name)" -ForegroundColor Cyan
                $SuccessCount++
            }
        }
        catch {
            Write-Warning "Failed to add to group '$($Group.Name)': $($_.Exception.Message)"
            $ErrorCount++
        }
    }

    # Summary
    Write-Host "`n=== SUMMARY ===" -ForegroundColor Magenta
    Write-Host "Successfully added to $SuccessCount group(s)" -ForegroundColor Green
    Write-Host "Skipped $SkippedCount group(s) (already member)" -ForegroundColor Yellow
    Write-Host "Failed to add to $ErrorCount group(s)" -ForegroundColor Red
    Write-Host "===============`n" -ForegroundColor Magenta

    if ($ErrorCount -gt 0) {
        Write-Host "Some group additions failed. This is normal for groups where you don't have permissions." -ForegroundColor DarkMagenta
    }

    Write-Host "Group memberships successfully copied from '$SourceUser' to '$TargetUser'" -ForegroundColor Green
}
catch [Microsoft.ActiveDirectory.Management.ADIdentityNotFoundException] {
    Write-Error "One or both users not found in domain '$DomainName'. Please verify usernames and domain."
    exit 1
}
catch {
    Write-Error "Script execution failed: $($_.Exception.Message)"
    exit 1
}

# --- END OF SCRIPT ---