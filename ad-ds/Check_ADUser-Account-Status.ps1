<#
.SYNOPSIS
    Checks Active Directory user account status across multiple domains.

.DESCRIPTION
    This script verifies the status of User Accounts across multiple domains and exports the results to CSV.
    It searches for users in multiple AD domains and retrieves their DisplayName, EmailAddress, and account status.
    The script handles service accounts by skipping those starting with "sa_" and processes admin accounts
    by extracting the base username from patterns like "admt1_username".
    All inputs are collected via interactive prompts.

.EXAMPLE
    .\Check_ADUser-Account-Status.ps1

.NOTES
    HOW TO RUN THIS SCRIPT:
    1. Open PowerShell (as Administrator, if needed)
    2. Navigate to the script location: cd "C:\path\to\script"
    3. Run the script: .\Check_ADUser-Account-Status.ps1
    4. Follow the prompts to enter:
       - Input text file path (containing usernames)
       - Output CSV file path for results
    
    Author: Areen Agrawal
    Version: 1.0
    Requires: ActiveDirectory PowerShell module
#>

Write-Host "`n=== AD USER ACCOUNT STATUS CHECKER ===" -ForegroundColor Magenta
Write-Host "This script will check user account status across multiple domains and export to CSV" -ForegroundColor White
Write-Host "===================================================`n" -ForegroundColor Magenta

# Prompt for Input File Path
do {
    $inputFilePath = Read-Host "Enter the path to input text file containing usernames (e.g., 'C:\Reports\Users.txt')"
} while ([string]::IsNullOrWhiteSpace($inputFilePath))

# Prompt for Output CSV Path
do {
    $outputCsvPath = Read-Host "Enter the path for output CSV file (e.g., 'C:\Reports\UserAccountStatus.csv')"
} while ([string]::IsNullOrWhiteSpace($outputCsvPath))

# Display entered parameters for confirmation
Write-Host "`n=== CONFIRMATION ===" -ForegroundColor Magenta
Write-Host "Input File: $inputFilePath" -ForegroundColor White
Write-Host "Output Path: $outputCsvPath" -ForegroundColor White
Write-Host "==================`n" -ForegroundColor Magenta

$confirmation = Read-Host "Proceed with these parameters? (Y/N)"
if ($confirmation -notmatch '^[Yy]') {
    Write-Host "Script cancelled by user." -ForegroundColor Yellow
    exit 0
}

try {
    # Check if input file exists
    if (-not (Test-Path $inputFilePath)) {
        Write-Error "Input file not found: $inputFilePath"
        exit 1
    }

    # Get all domains in the forest
    Write-Host "Retrieving forest domains..." -ForegroundColor Green
    $Domains = (Get-ADForest).Domains
    Write-Host "Found domains: $($Domains -join ', ')" -ForegroundColor Cyan

    # Read the list of usernames from the input file
    Write-Host "Reading usernames from input file..." -ForegroundColor Green
    $usernames = Get-Content $inputFilePath -ErrorAction Stop
    Write-Host "Processing $($usernames.Count) usernames..." -ForegroundColor Yellow

    # Initialize an array to hold user objects
    $userResults = @()

    # Loop through each username
    foreach ($username in $usernames) {
        # Skip service accounts that start with "sa_"
        if ($username -and $username.StartsWith("sa_")) { 
            Write-Host "Skipping service account: $username" -ForegroundColor DarkYellow
            continue 
        }
        
        # Extract actual username/NetworkID if it's an admin account (e.g., "admt1_username")
        if ($username) {
            $parts = $username -split "_"
            if ($parts.Count -gt 1) {
                $Uname = $parts[1]
            } else {
                $Uname = $username
            }
        }
        
        # Search for user across all domains
        $found = $false
        $user = $null
        foreach ($domain in $Domains) {
            try {
                # Query AD user with required properties from specific domain
                $user = Get-ADUser $Uname -Properties DisplayName, EmailAddress, Enabled -Server $domain -ErrorAction Stop
                if ($user) {
                    $found = $true
                    Write-Host "Found user: $Uname in domain: $domain" -ForegroundColor Cyan
                    break
                }
            } catch [Microsoft.ActiveDirectory.Management.ADIdentityNotFoundException] {
                continue
            } catch {
                Write-Warning "Error querying domain $domain for user $Uname`: $($_.Exception.Message)"
                continue
            }
        }

        # Create user object based on search results
        if ($found -and $user) {
            # Determine account status
            $status = If ($user.Enabled -eq $true) { "Active" } else { "Not Active" }
            
            $userObject = [PSCustomObject]@{
                DisplayName = $user.DisplayName
                SAMAccountName = $username
                EmailAddress = $user.EmailAddress
                Status = $status
            }
        } else {
            # Create object for users not found in any domain
            Write-Warning "User not found in any domain: $username"
            $userObject = [PSCustomObject]@{
                DisplayName = "Not Found in AD"
                SAMAccountName = $username
                EmailAddress = "Not Found in AD"
                Status = "Not Found"
            }
        }
        
        # Add the user object to the results array
        $userResults += $userObject
    }

    # Export the results to a CSV file
    if ($userResults.Count -gt 0) {
        $userResults | Export-Csv -Path $outputCsvPath -NoTypeInformation -ErrorAction Stop
        Write-Host "Successfully exported $($userResults.Count) user records to: $outputCsvPath" -ForegroundColor Green
    } else {
        Write-Warning "No user records found to export."
    }
}
catch {
    Write-Error "Script execution failed: $($_.Exception.Message)"
    exit 1
}

# --- END OF SCRIPT ---