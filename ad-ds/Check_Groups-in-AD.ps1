<#
.SYNOPSIS
    Checks if Active Directory groups exist across multiple domains.

.DESCRIPTION
    This script reads group names from a text file and checks their existence across
    all domains in the current AD forest. It outputs a list of existing groups with 
    their domain information. All inputs are collected via interactive prompts.

.EXAMPLE
    .\CheckGroupsinAD.ps1

.NOTES
    HOW TO RUN THIS SCRIPT:
    1. Open PowerShell (as Administrator, if needed)
    2. Navigate to the script location: cd "C:\path\to\script"
    3. Run the script: .\CheckGroupsinAD.ps1
    4. Follow the prompts to enter:
       - Path to text file containing group names
       - Output file path (optional)
    
    Text file should contain one group name per line.

    Author: Your Name
    Version: 1.0
    Requires: ActiveDirectory PowerShell module
#>

Write-Host "`n=== AD GROUP EXISTENCE CHECK TOOL ===" -ForegroundColor Magenta
Write-Host "This script will check if AD groups exist across all domains in the forest" -ForegroundColor White
Write-Host "=============================================`n" -ForegroundColor Magenta

# Prompt for text file path
do {
    $txtFilePath = Read-Host "Enter the full path to text file with group names (e.g., 'C:\Groups\ListOfGroups.txt')"
} while ([string]::IsNullOrWhiteSpace($txtFilePath))

# Validate file exists
if (-not (Test-Path $txtFilePath)) {
    Write-Error "File not found: $txtFilePath"
    exit 1
}

# Prompt for output path (optional)
$OutputPath = Read-Host "Enter output file path (optional - press Enter to display results only)"

# Display entered parameters for confirmation
Write-Host "`n=== CONFIRMATION ===" -ForegroundColor Magenta
Write-Host "Input File: $txtFilePath" -ForegroundColor White
if ($OutputPath) {
    Write-Host "Output File: $OutputPath" -ForegroundColor White
} else {
    Write-Host "Output: Display only" -ForegroundColor White
}
Write-Host "==================`n" -ForegroundColor Magenta

$confirmation = Read-Host "Proceed with these parameters? (Y/N)"
if ($confirmation -notmatch '^[Yy]') {
    Write-Host "Script cancelled by user." -ForegroundColor Yellow
    exit 0
}

try {
    # Read group names from the text file
    Write-Host "Reading group names from: $txtFilePath" -ForegroundColor Green
    $groups = Get-Content $txtFilePath -ErrorAction Stop
    
    # Get all domains in the current forest
    Write-Host "Discovering domains in the forest..." -ForegroundColor Yellow
    $domains = (Get-ADForest).Domains
    
    # Initialize arrays to store results
    $existingGroups = @()
    $groupDetails = @()
    
    Write-Host "Checking $($groups.Count) groups across $($domains.Count) domains..." -ForegroundColor Yellow

    # Loop through each group
    foreach ($group in $groups) {
        $groupFound = $false
        
        # Loop through each domain
        foreach ($domain in $domains) {
            try {
                # Check if the group exists in the current domain
                $exists = Get-ADGroup -Filter { SamAccountName -eq $group } -Server $domain -ErrorAction Stop
                
                if ($exists) {
                    $fullGroupName = "${group}@${domain}"
                    $existingGroups += $fullGroupName
                    
                    # Create detailed object for export
                    $groupDetail = [PSCustomObject]@{
                        "Group Name" = $group
                        "Domain" = $domain
                        "Full Name" = $fullGroupName
                        "Distinguished Name" = $exists.DistinguishedName
                    }
                    $groupDetails += $groupDetail
                    
                    Write-Host "Found group: $fullGroupName" -ForegroundColor Cyan
                    $groupFound = $true
                    break  # Stop checking in other domains once found
                }
            }
            catch [Microsoft.ActiveDirectory.Management.ADServerDownException] {
                Write-Warning "Domain $domain is not accessible"
                continue
            }
            catch {
                Write-Warning "Error querying domain $domain for group $group`: $($_.Exception.Message)"
                continue
            }
        }
        
        if (-not $groupFound) {
            Write-Host "Group not found in any domain: $group" -ForegroundColor Red
        }
    }

    # Display results
    Write-Host "`n=== RESULTS ===" -ForegroundColor Magenta
    Write-Host "Found $($existingGroups.Count) existing groups out of $($groups.Count) total groups" -ForegroundColor Green
    
    if ($existingGroups.Count -gt 0) {
        Write-Host "`nExisting Groups:" -ForegroundColor Yellow
        $existingGroups | ForEach-Object { Write-Host "  $_" -ForegroundColor White }
        
        # Export to file if path provided
        if ($OutputPath) {
            $groupDetails | Export-Csv -Path $OutputPath -NoTypeInformation -ErrorAction Stop
            Write-Host "`nResults exported to: $OutputPath" -ForegroundColor Green
        }
    } else {
        Write-Host "No groups found in any domain." -ForegroundColor Yellow
    }
}
catch {
    Write-Error "Script execution failed: $($_.Exception.Message)"
    exit 1
}

# --- END OF SCRIPT ---
