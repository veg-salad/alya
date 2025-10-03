<#
.SYNOPSIS
    Analyzes directory statistics and exports results to CSV file.

.DESCRIPTION
    This script reads folder paths from an input file, analyzes each folder's statistics
    (file count, subfolder count, total size), and exports the results to a CSV file.
    All inputs are collected via interactive prompts.

.EXAMPLE
    .\folderStats.ps1

.NOTES
    HOW TO RUN THIS SCRIPT:
    1. Open PowerShell (as Administrator, if needed)
    2. Navigate to the script location: cd "C:\path\to\script"
    3. Run the script: .\Get-FolderStats.ps1
    4. Follow the prompts to enter:
       - Input file path (containing folder paths)
       - Output CSV file path
    
    Author: [Your Name]
    Version: 1.0
    Requires: PowerShell 5.0 or higher
#>

Write-Host "`n=== DIRECTORY STATISTICS ANALYZER ===" -ForegroundColor Magenta
Write-Host "This script will analyze folder statistics and export results to CSV" -ForegroundColor White
Write-Host "=============================================`n" -ForegroundColor Magenta

# Prompt for Input File Path
do {
    $inputFile = Read-Host "Enter the full path to input file containing folder paths (e.g., 'C:\Data\folders.txt')"
} while ([string]::IsNullOrWhiteSpace($inputFile))

# Prompt for Output Path
do {
    $outputCsv = Read-Host "Enter the full path for output CSV file (e.g., 'C:\Reports\DirectoryStats.csv')"
} while ([string]::IsNullOrWhiteSpace($outputCsv))

# Display entered parameters for confirmation
Write-Host "`n=== CONFIRMATION ===" -ForegroundColor Magenta
Write-Host "Input File: $inputFile" -ForegroundColor White
Write-Host "Output CSV: $outputCsv" -ForegroundColor White
Write-Host "==================`n" -ForegroundColor Magenta

$confirmation = Read-Host "Proceed with these parameters? (Y/N)"
if ($confirmation -notmatch '^[Yy]') {
    Write-Host "Script cancelled by user." -ForegroundColor Yellow
    exit 0
}

try {
    # Verify input file exists
    if (-not (Test-Path $inputFile)) {
        Write-Error "Input file not found: $inputFile"
        exit 1
    }

    Write-Host "Reading folder paths from: $inputFile" -ForegroundColor Green
    $folderPaths = Get-Content $inputFile -ErrorAction Stop
    $results = @()

    Write-Host "Processing $($folderPaths.Count) folder paths..." -ForegroundColor Yellow

    foreach ($folderPath in $folderPaths) {
        $folderPath = $folderPath.Trim()

        if ([string]::IsNullOrWhiteSpace($folderPath)) {
            continue
        }

        if (-not (Test-Path $folderPath)) {
            Write-Warning "Folder not found: $folderPath"
            continue
        }

        Write-Host "Analyzing: $folderPath" -ForegroundColor Cyan
        $folderName = Split-Path -Path $folderPath -Leaf

        try {
            $fileCount = (Get-ChildItem -LiteralPath $folderPath -Recurse -File -ErrorAction SilentlyContinue).Count
            $subfolderCount = (Get-ChildItem -LiteralPath $folderPath -Recurse -Directory -ErrorAction SilentlyContinue).Count

            $totalSize = (Get-ChildItem -LiteralPath $folderPath -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
            $totalSizeGB = [Math]::Round($totalSize / 1GB, 2)

            $results += [PSCustomObject]@{
                FolderName      = $folderName
                FolderPath      = $folderPath
                FileCount       = $fileCount
                SubfolderCount  = $subfolderCount
                TotalSizeGB     = $totalSizeGB
            }
        }
        catch {
            Write-Warning "Error analyzing folder $folderPath`: $($_.Exception.Message)"
            continue
        }
    }

    # Export to CSV file
    if ($results.Count -gt 0) {
        $results | Export-Csv -Path $outputCsv -NoTypeInformation -ErrorAction Stop
        Write-Host "Successfully exported statistics for $($results.Count) folders to: $outputCsv" -ForegroundColor Green
    } else {
        Write-Warning "No folder statistics to export."
    }
}
catch {
    Write-Error "Script execution failed: $($_.Exception.Message)"
    exit 1
}

# --- END OF SCRIPT ---