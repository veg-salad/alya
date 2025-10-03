<#
.SYNOPSIS
	Checks Active Directory user group memberships across multiple domains.

.DESCRIPTION
	This script verifies if specified users are members of target groups in Active Directory.
	It searches across all domains in the forest and supports two methods for specifying groups:
	1. Direct array of group Distinguished Names
	2. Text file containing group Distinguished Names (one per line)

.PARAMETER UserListPath
	Path to text file containing usernames/SAMAccountNames (one per line)

.PARAMETER GroupsArray
	Array of group Distinguished Names to check membership against

.PARAMETER GroupsFilePath
	Path to text file containing group Distinguished Names (one per line)

.PARAMETER OutputPath
	Path for the results CSV file

.PARAMETER NotFoundPath
	Path for the file containing users not found in AD

.EXAMPLE
	.\Check_ADUser-Group-Memberships.ps1

.NOTES
	Author: Areen Agrawal
	Version: 2.0
	Requires: ActiveDirectory PowerShell module
#>

[CmdletBinding()]
param(
	[string]$UserListPath = "C:\path\to\UserList.txt",
	[string[]]$GroupsArray = @(),
	[string]$GroupsFilePath = "",
	[string]$OutputPath = "C:\path\to\results.csv",
	[string]$NotFoundPath = "C:\path\to\Users_Not-Found.txt"
)

# Validate input parameters
if (-not (Test-Path $UserListPath)) {
	Write-Error "User list file not found: $UserListPath"
	exit 1
}

# Determine group source
if ($GroupsFilePath -and (Test-Path $GroupsFilePath)) {
	$groupsArr = Get-Content -Path $GroupsFilePath | Where-Object { $_.Trim() -ne "" }
	Write-Host "Loaded $($groupsArr.Count) groups from file: $GroupsFilePath"
} elseif ($GroupsArray.Count -gt 0) {
	$groupsArr = $GroupsArray
	Write-Host "Using $($groupsArr.Count) groups from parameter array"
} else {
	Write-Warning "No groups specified. Please provide either -GroupsArray or -GroupsFilePath parameter."
	Write-Host "Example group DN: CN=Domain Admins,CN=Users,DC=contoso,DC=com"
	exit 1
}

# Initialize collections
$notFound = [System.Collections.ArrayList]::new()
$results = [System.Collections.ArrayList]::new()

# Get all domains in the forest
try {
	$domains = (Get-ADForest).Domains
	Write-Host "Searching across $($domains.Count) domains: $($domains -join ', ')"
} catch {
	Write-Error "Failed to get AD Forest information: $($_.Exception.Message)"
	exit 1
}

# Load users from file
$users = Get-Content -Path $UserListPath | Where-Object { $_.Trim() -ne "" }
Write-Host "Processing $($users.Count) users..."

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
		Write-Host "✓ Found user: $username in domain: $userDomain (Member of $($memberGroups.Count) target groups)"
	} else {
		[void]$notFound.Add($username)
		Write-Warning "✗ User not found: $username"
	}
}

# Export results
try {
	$results | Export-Csv -Path $OutputPath -NoTypeInformation -Encoding UTF8
	Write-Host "Results exported to: $OutputPath ($($results.Count) users)"
	
	if ($notFound.Count -gt 0) {
		$notFound | Out-File -FilePath $NotFoundPath -Encoding UTF8
		Write-Host "Users not found exported to: $NotFoundPath ($($notFound.Count) users)"
	}
} catch {
	Write-Error "Failed to export results: $($_.Exception.Message)"
	exit 1
}

# Summary
Write-Host "`nSummary:"
Write-Host "- Users processed: $($users.Count)"
Write-Host "- Users found: $($results.Count)"
Write-Host "- Users not found: $($notFound.Count)"
Write-Host "- Target groups: $($groupsArr.Count)"