<#
This script checks the status of User Accounts across multiple domains and exports the results to CSV.
It searches for users in multiple AD domains and retrieves their DisplayName, EmailAddress, and account status.
- - -

Values within angle brackets <> are to be replaced by users with actual values...
PLEASE REMOVE ANGLE BRACKETS (<>) & DO NOT REMOVE DOUBLE QUOTES ("") WHEN YOU SUPPLY ACTUAL VALUES
#>

# Define the path to the input file (list of usernames) and output CSV file
$inputFilePath = <".\Users.txt">
$outputCsvPath = <".\UserAccountStatus.csv">
$Domains = (Get-ADForest).Domains

# Read the list of usernames from the input file
$usernames = Get-Content $inputFilePath

# Initialize an array to hold user objects
$userResults = @()

# Loop through each username
foreach ($username in $usernames) {
    # Skip service accounts that start with "sa_"
    if ($username -and $username.StartsWith("sa_")) { continue }
    
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
    foreach ($domain in $Domains) {
        try {
            # Query AD user with required properties from specific domain
            $user = Get-ADUser $Uname -Properties DisplayName, EmailAddress, Enabled -Server $domain
            if ($user) {
                $found = $true
                break
            }
        } catch {
            # Ignore error and try next domain
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
$userResults | Export-Csv -Path $outputCsvPath -NoTypeInformation

Write-Host "User account status information has been exported to $outputCsvPath"

# --- END OF SCRIPT ---