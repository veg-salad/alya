<#
.SYNOPSIS
    Checks the existence of users in Active Directory by Employee ID and exports results to CSV.

.DESCRIPTION
    This script reads a list of Employee IDs from a text file and searches for corresponding
    users across multiple domains in the forest. It exports user details (Employee ID, Username,
    Extension Attribute 9, Domain, Distinguished Name) to a CSV file.
    All inputs are collected via interactive prompts.

.EXAMPLE
    .\CheckUsersExistence.ps1

.NOTES
    HOW TO RUN THIS SCRIPT:
    1. Open PowerShell (as Administrator, if needed)
    2. Navigate to the script location: cd "C:\path\to\script"
    3. Run the script: .\CheckUsersExistence.ps1
    4. Follow the prompts to enter:
       - Input file path (containing Employee IDs)
       - Output CSV file path
    
    Author: Areen Agrawal
    Version: 2.0
    Requires: ActiveDirectory PowerShell module
#>

Write-Host "`n=== AD USER EXISTENCE CHECK TOOL ===" -ForegroundColor Magenta
Write-Host "This script will check user existence by Employee ID and export results to CSV" -ForegroundColor White
Write-Host "================================================================`n" -ForegroundColor Magenta

# Prompt for Input File Path
do {
    $inputFilePath = Read-Host "Enter the path to input file containing Employee IDs (e.g., 'C:\Data\UserList.txt')"
} while ([string]::IsNullOrWhiteSpace($inputFilePath) -or !(Test-Path $inputFilePath))

if (!(Test-Path $inputFilePath)) {
    Write-Error "Input file not found: $inputFilePath"
    exit 1
}

# Prompt for Output Path
do {
    $outputCsvPath = Read-Host "Enter the full path for output CSV file (e.g., 'C:\Reports\output.csv')"
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
    # Get all domains in the forest
    $Domains = (Get-ADForest).Domains
    
    # Read the list of usernames from the input file
    $usernames = Get-Content $inputFilePath -ErrorAction Stop
    Write-Host "Processing $($usernames.Count) Employee IDs..." -ForegroundColor Yellow

    # Initialize an array to hold user objects
    $userResults = @()

    # Loop through each username
    foreach ($username in $usernames) {
        $found = $false
        $user = $null

        # Search for the user across all domains in the forest
        foreach ($domain in $Domains) {
            try {
                $user = Get-ADUser -Filter {EmployeeID -eq $username} -Properties UserPrincipalName, extensionAttribute9, DistinguishedName -Server $domain -ErrorAction Stop
                if ($user) {
                    $found = $true
                    break
                }
            }
            catch [Microsoft.ActiveDirectory.Management.ADIdentityNotFoundException] {
                continue
            }
            catch {
                Write-Warning "Error querying domain $domain for Employee ID $username`: $($_.Exception.Message)"
                continue
            }
        }

        if ($found -and $user) {
            # Create a custom object with the desired properties for found users
            $DomainName = $user.UserPrincipalName.Split("@")
            $userObject = [PSCustomObject]@{
                "Employee ID"         = $username
                "Username"            = $DomainName[0]
                "Extension Attribute 9" = $user.extensionAttribute9
                "Domain"              = $DomainName[1]
                "Distinguished Name"  = $user.DistinguishedName    
            }
            Write-Host "Found user: $($userObject.Username)" -ForegroundColor Cyan
        }
        else {
            # Create a custom object with "Not Found in AD" for not found users
            $userObject = [PSCustomObject]@{
                "Employee ID"         = $username
                "Username"            = "Not Found in AD"
                "Extension Attribute 9" = ""
                "Domain"              = ""
                "Distinguished Name"  = ""
            }
            Write-Warning "User not found in any domain: $username"
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