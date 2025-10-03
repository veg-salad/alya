<#
.SYNOPSIS
	Checks Active Directory user group memberships across multiple domains.

.DESCRIPTION
	This script verifies if specified users are members of target groups in Active Directory.
	It searches across all domains in the forest and supports two methods for specifying groups:
	1. Direct text file containing group Distinguished Names (one per line)
	2. Interactive input for individual group Distinguished Names
	All inputs are collected via interactive prompts.

.EXAMPLE
	.\Check_ADUser-Group-Memberships.ps1

.NOTES
	HOW TO RUN THIS SCRIPT:
	1. Open PowerShell (as Administrator, if needed)
	2. Navigate to the script location: cd "C:\path\to\script"
	3. Run the script: .\Check_ADUser-Group-Memberships.ps1
	4. Follow the prompts to enter:
	   - Input text file path (containing usernames)
	   - Groups file path OR individual group DNs
	   - Output CSV file path for results
	   - Output file path for users not found
	
	Author: Areen Agrawal
	Version: 2.0
	Requires: ActiveDirectory PowerShell module
#>

Write-Host "`n=== AD USER GROUP MEMBERSHIP CHECKER ===" -ForegroundColor Magenta
Write-Host "This script will check user group memberships across multiple domains and export to CSV" -ForegroundColor White
Write-Host "===========================================================`n" -ForegroundColor Magenta

# Prompt for User List File Path
do {
	$UserListPath = Read-Host "Enter the path to input text file containing usernames (e.g., 'C:\Reports\Users.txt')"
} while ([string]::IsNullOrWhiteSpace($UserListPath))

# Prompt for Groups specification method
Write-Host "`nHow would you like to specify the target groups?" -ForegroundColor Yellow
Write-Host "1. From a text file containing group Distinguished Names" -ForegroundColor White
Write-Host "2. Enter group Distinguished Names individually" -ForegroundColor White

do {
	$groupMethod = Read-Host "Choose method (1 or 2)"
} while ($groupMethod -notmatch '^[12]$')

# Handle group specification based on chosen method
$groupsArr = @()
if ($groupMethod -eq "1") {
	# Groups from file
	do {
		$GroupsFilePath = Read-Host "Enter the path to text file containing group Distinguished Names (e.g., 'C:\Reports\Groups.txt')"
	} while ([string]::IsNullOrWhiteSpace($GroupsFilePath))
	
	if (Test-Path $GroupsFilePath) {
		$groupsArr = Get-Content -Path $GroupsFilePath | Where-Object { $_.Trim() -ne "" }
	} else {
		Write-Error "Groups file not found: $GroupsFilePath"
		exit 1
	}
} else {
	# Individual group input
	Write-Host "`nEnter group Distinguished Names (one per line). Press Enter on empty line to finish:" -ForegroundColor Yellow
	Write-Host "Example: CN=Domain Admins,CN=Users,DC=contoso,DC=com" -ForegroundColor Gray
	
	do {
		$groupDN = Read-Host "Group DN"
		if (![string]::IsNullOrWhiteSpace($groupDN)) {
			$groupsArr += $groupDN.Trim()
		}
	} while (![string]::IsNullOrWhiteSpace($groupDN))
	
	if ($groupsArr.Count -eq 0) {
		Write-Error "No groups specified. Script cannot continue."
		exit 1
	}
}

# Prompt for Output CSV Path
do {
	$OutputPath = Read-Host "Enter the path for output CSV file (e.g., 'C:\Reports\GroupMemberships.csv')"
} while ([string]::IsNullOrWhiteSpace($OutputPath))

# Prompt for Not Found Users Path
do {
	$NotFoundPath = Read-Host "Enter the path for users not found file (e.g., 'C:\Reports\UsersNotFound.txt')"
} while ([string]::IsNullOrWhiteSpace($NotFoundPath))

# Display entered parameters for confirmation
Write-Host "`n=== CONFIRMATION ===" -ForegroundColor Magenta
Write-Host "User List File: $UserListPath" -ForegroundColor White
if ($GroupsFilePath) {
	Write-Host "Groups File: $GroupsFilePath" -ForegroundColor White
} else {
	Write-Host "Target Groups:" -ForegroundColor White
	foreach ($group in $groupsArr) {
		Write-Host "  - $group" -ForegroundColor Gray
	}
}
Write-Host "Target Groups Count: $($groupsArr.Count)" -ForegroundColor White
Write-Host "Output CSV Path: $OutputPath" -ForegroundColor White
Write-Host "Not Found Path: $NotFoundPath" -ForegroundColor White
Write-Host "==================`n" -ForegroundColor Magenta

$confirmation = Read-Host "Proceed with these parameters? (Y/N)"
if ($confirmation -notmatch '^[Yy]') {
	Write-Host "Script cancelled by user." -ForegroundColor Yellow
	exit 0
}

try {
	# Check if user list file exists
	if (-not (Test-Path $UserListPath)) {
		Write-Error "User list file not found: $UserListPath"
		exit 1
	}

	# Initialize collections
	$notFound = [System.Collections.ArrayList]::new()
	$results = [System.Collections.ArrayList]::new()

	# Get all domains in the forest
	Write-Host "Retrieving forest domains..." -ForegroundColor Green
	$domains = (Get-ADForest).Domains
	Write-Host "Found domains: $($domains -join ', ')" -ForegroundColor Cyan

	# Load users from file
	Write-Host "Reading usernames from input file..." -ForegroundColor Green
	$users = Get-Content -Path $UserListPath | Where-Object { $_.Trim() -ne "" }
	Write-Host "Processing $($users.Count) users against $($groupsArr.Count) target groups..." -ForegroundColor Yellow

	# Process each user
	foreach ($username in $users) {
		$userFound = $false
		$userDomain = ""
		$userObject = $null

		# Search for user across all domains
		foreach ($domain in $domains) {
			try {
				$userObject = Get-ADUser $username -Properties MemberOf -Server $domain -ErrorAction Stop
				$userDomain = $domain
				$userFound = $true
				break
			} catch [Microsoft.ActiveDirectory.Management.ADIdentityNotFoundException] {
				continue
			} catch {
				Write-Warning "Error searching for user '$username' in domain '$domain': $($_.Exception.Message)"
				continue
			}
		}

		if ($userFound) {
			$memberGroups = [System.Collections.ArrayList]::new()
			
			# Check membership in each target group
			foreach ($groupDN in $groupsArr) {
				if ($userObject.MemberOf -contains $groupDN) {
					# Extract group name from DN (CN=GroupName,...)
					if ($groupDN -match '^CN=([^,]+)') {
						[void]$memberGroups.Add($matches[1])
					} else {
						[void]$memberGroups.Add($groupDN)
					}
				}
			}

			# Create result object
			$resultObj = [PSCustomObject]@{
				Domain         = $userDomain
				SAMAccountName = $username
				DisplayName    = $userObject.Name
				Enabled        = $userObject.Enabled
				Groups         = if ($memberGroups.Count -gt 0) { $memberGroups -join ', ' } else { "None" }
				GroupCount     = $memberGroups.Count
			}

			[void]$results.Add($resultObj)
			Write-Host "Found user: $username in domain: $userDomain (Member of $($memberGroups.Count) target groups)" -ForegroundColor Cyan
		} else {
			[void]$notFound.Add($username)
			Write-Warning "User not found in any domain: $username"
		}
	}

	# Export results
	if ($results.Count -gt 0) {
		$results | Export-Csv -Path $OutputPath -NoTypeInformation -Encoding UTF8 -ErrorAction Stop
		Write-Host "Successfully exported $($results.Count) user records to: $OutputPath" -ForegroundColor Green
	} else {
		Write-Warning "No user records found to export."
	}
	
	if ($notFound.Count -gt 0) {
		$notFound | Out-File -FilePath $NotFoundPath -Encoding UTF8 -ErrorAction Stop
		Write-Host "Users not found exported to: $NotFoundPath ($($notFound.Count) users)" -ForegroundColor Green
	}

	# Summary
	Write-Host "`n=== SUMMARY ===" -ForegroundColor Magenta
	Write-Host "Users processed: $($users.Count)" -ForegroundColor White
	Write-Host "Users found: $($results.Count)" -ForegroundColor White
	Write-Host "Users not found: $($notFound.Count)" -ForegroundColor White
	Write-Host "Target groups: $($groupsArr.Count)" -ForegroundColor White
	Write-Host "===============" -ForegroundColor Magenta
}
catch {
	Write-Error "Script execution failed: $($_.Exception.Message)"
	exit 1
}

# --- END OF SCRIPT ---