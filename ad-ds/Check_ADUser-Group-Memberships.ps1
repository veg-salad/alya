<#
This script is meant to check if the given list of users are members of a group(s) in Active Directory...
It supports two methods to provide groups - one through the group DNs in an array (Line 17), another through a TXT file (Line 21).

You can modify line 33 & PSCustomObject in line 51 & provide additional attributes for the users if you want them to be added to the resultant CSV file.
- - -

Values within angle brackets <> are to be replaced by users with actual values...
PLEASE REMOVE ANGLE BRACKETS (<>) & DO NOT REMOVE DOUBLE QUOTES ("") WHEN YOU SUPPLY ACTUAL VALUES
#>

# Please provide the list of Usernames/SAMAccountNames in the UserList.txt file...
$Users = Get-Content -FilePath <"C:\path\to\UserList.txt">

# Un-Comment line 17 if you want to check memberships for a small number of groups;
# Provide the Distinguished Names for groups separated by a comma replacing the placeholder <group-DN>
#$groupsArr = @("<group-DN>")

# If your number of groups are large, then put their DNs in a txt file & Un-Comment the following line...
# If you're using TXT file option then please keep the line 17 commented.
#$groupsArr = @("<group-DN>")

$notFound = @()
$results = @()

$Domains = (Get-ADForest).Domains

foreach ($node in $Users) {
	foreach ($domain in $Domains) {
        try {
	$Groups = ""
	$User = Get-ADUser $node -Properties MemberOf -Server $domain
	$D = $domain
	break
        
	} catch [Microsoft.ActiveDirectory.Management.ADIdentityNotFoundException] {
            continue
        }}

	if ($User) {
		foreach ($group in $groupsArr) {
			if ($User.MemberOf -contains $group) {
				$splits = $group -split ','
				$more_splits += $splits[0] -split "="
				if ($Groups) {$Groups += ', ' + $more_splits[1]}
				else {$Groups += $more_splits[1]}}}
	
		if (!($Groups)) {$Groups += "None"}

		$obj = [PSCustomObject]@{
			Domain = $D,
			SAMAccountName = $node,
			Groups = $Groups,
		}

	$results += $obj
	}
	else {
		# Users that are not found in Active Directory are exported in Users_Not-Found.txt...
		$notFound += $sacn}}

# Membership data for each user will be exported in the results.csv file as "Domain, SAMAccountName, Groups"...
# If you'll add more attributes in PSCustomObject, they'll be added as columns in the file.
$results | Export-CSV -Path <"C:\path\to\results.csv"> -NoTypeInformation
$notFound | Out-File -FilePath <"C:\path\to\Users_Not-Found.txt">

# --- END OF SCRIPT ---