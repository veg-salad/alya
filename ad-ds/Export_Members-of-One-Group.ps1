<#
This script is meant to fetch the attributes of members of a single group only...
If you wish to perform these steps on a list of multiple groups (in same domain), check out "[v1.0]-Export_Members-of-Many-Groups.ps1"...
And, if you wish to perform these steps on a list of multiple groups (of multiple domains), check out "[v1.1]-Export_Members-of-Many-Groups.ps1"
- - -

Values within angle brackets <> are to be replaced by users with actual values...
PLEASE REMOVE ANGLE BRACKETS (<>) & DO NOT REMOVE DOUBLE QUOTES ("") WHEN YOU SUPPLY ACTUAL VALUES
#>

# Please provide name of the Active Directory <group> & its respective <domain>...
$Group = Get-ADGroup "<group>" -Properties Members -Server <domain>
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
$MemberAttribs | Export-Csv -Path "C:\path\to\OutputFile.csv" -NoTypeInformation

# --- END OF SCRIPT ---