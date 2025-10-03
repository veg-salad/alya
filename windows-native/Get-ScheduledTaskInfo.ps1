<#
.SYNOPSIS
    Retrieves detailed information about a specified Windows scheduled task.

.DESCRIPTION
    This script searches for a specified scheduled task anywhere on the system and displays
    detailed information including task name, path, state, last run time, next run time,
    and last result. The task name is collected via interactive prompt.

.EXAMPLE
    .\Get-ScheduledTaskInfo.ps1

.NOTES
    HOW TO RUN THIS SCRIPT:
    1. Open PowerShell (as Administrator recommended for full task access)
    2. Navigate to the script location: cd "C:\path\to\script"
    3. Run the script: .\Get-ScheduledTaskInfo.ps1
    4. Follow the prompt to enter the scheduled task name

    Author: Areen Agrawal
    Version: 1.0
    Requires: Windows PowerShell with ScheduledTasks module
#>

Write-Host "`n=== SCHEDULED TASK INFO TOOL ===" -ForegroundColor Magenta
Write-Host "This script will retrieve detailed information about a scheduled task" -ForegroundColor White
Write-Host "=======================================================`n" -ForegroundColor Magenta

# Prompt for Task Name
do {
    $TaskName = Read-Host "Enter the scheduled task name (e.g., 'chef-client', 'Windows Update')"
} while ([string]::IsNullOrWhiteSpace($TaskName))

# Display entered parameter for confirmation
Write-Host "`n=== CONFIRMATION ===" -ForegroundColor Magenta
Write-Host "Task Name: $TaskName" -ForegroundColor White
Write-Host "==================`n" -ForegroundColor Magenta

$confirmation = Read-Host "Proceed with searching for this task? (Y/N)"
if ($confirmation -notmatch '^[Yy]') {
    Write-Host "Script cancelled by user." -ForegroundColor Yellow
    exit 0
}

try {
    Write-Host "Searching for scheduled task: $TaskName" -ForegroundColor Green
    
    # Get all scheduled tasks and look for the one with the exact name
    $task = Get-ScheduledTask | Where-Object { $_.TaskName -eq $TaskName }

    if ($task) {
        Write-Host "Task found! Retrieving detailed information..." -ForegroundColor Yellow
        
        # Retrieve detailed task status info
        $info = Get-ScheduledTaskInfo -TaskName $task.TaskName -TaskPath $task.TaskPath

        # Output the information in a formatted list
        $TaskDetails = [PSCustomObject]@{
            TaskName    = $task.TaskName
            TaskPath    = $task.TaskPath
            State       = $info.State
            LastRunTime = $info.LastRunTime
            NextRunTime = $info.NextRunTime
            LastResult  = $info.LastTaskResult
        }
        
        Write-Host "`n=== TASK INFORMATION ===" -ForegroundColor Magenta
        $TaskDetails | Format-List
        Write-Host "=======================" -ForegroundColor Magenta
    }
    else {
        Write-Host "Scheduled task '$TaskName' not found." -ForegroundColor Yellow
        Write-Host "Please verify the task name and try again." -ForegroundColor Yellow
    }
}
catch {
    Write-Error "Script execution failed: $($_.Exception.Message)"
    exit 1
}

# --- END OF SCRIPT ---