<#
This script is meant to fetch the attributes of members of multiple groups (of same domain)...
If you wish to perform these steps on a list of multiple groups (of multiple domains), check out [v1.1] of this script.
- - -

Values within angle brackets <> are to be replaced by users with actual values...
PLEASE REMOVE ANGLE BRACKETS (<>) & DO NOT REMOVE DOUBLE QUOTES ("") WHEN YOU SUPPLY ACTUAL VALUES
#>

# Please provide the names of the Active Directory groups in a file named Groups.txt & their common respective <domain> here...
$ListOfGroups = Get-Content -Path "C:\path\to\Groups.txt"
$ListOfGroups | ForEach-Object {
    $Group = Get-ADGroup $_ -Properties Members -Server <domain>
    $Domains = (Get-ADForest).Domains
    $MemberAttribs = @()

    foreach ($member in $Group.Members) {
        $UserFound = $false

        foreach ($domain in $Domains) {
            try {
                $User = Get-ADUser -Identity $member -Properties GivenName, Surname, EmailAddress, UserPrincipalName -Server $domain
                $UserFound = $true
                break
            } catch [Microsoft.ActiveDirectory.Management.ADIdentityNotFoundException] {
                continue
            }
        }

        if ($UserFound) {
            $Username, $UserDomain = $User.UserPrincipalName.Split('@')
            $UserDetail = [PSCustomObject]@{
                "First Name" = $User.GivenName
                "Last Name" = $User.Surname
                "Username" = $UserID
                "Email Address" = $User.EmailAddress
                "Domain" = $Domain
            }
            $UserDetails += $UserDetail
        }
    }

    # This will export the data in a CSV file as "First Name, Last Name, Username, Email Address, Domain"
    # If an attribute doesn't have any value for the user in Active Directory, the entry for that column will be blank...
    # Each group will have one CSV file named after itself...
    $group = $_
    $MemberAttribs | Export-Csv -Path "C:\path\to\$group.csv" -NoTypeInformation
}

# --- END OF SCRIPT ---