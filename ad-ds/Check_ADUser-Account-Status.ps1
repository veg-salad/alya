# Please provide a list of usernames only in the Users.txt input file...

$UserList = Get-Content -Path C:\path\to\Users.txt | ForEach-Object {
    $user = Get-ADUser -LDAPFilter "(anr=$_)" -Properties samaccountname, enabled
    $status = If ($user.enabled -eq $true) { "Active" } else { "Not Active" }
    $user | Select-Object @{Name='SAMAccountName';Expression={$_.samaccountname}}, @{Name='Status';Expression={$status}}
}

# This will export the results in a CSV file as "SAMAccountName, Status" for each user...
$UserList | Export-Csv -Path C:\path\to\OutputFile.csv -NoTypeInformation