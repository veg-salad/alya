@echo off
setlocal enabledelayedexpansion

:: ============================================================================
:: Script Name: findFQDNs.bat
:: Description: Resolves IP addresses to FQDNs using nslookup and outputs 
::              results to a CSV file
:: Author: Areen Agrawal
:: Version: 2.0
:: 
:: Requirements:
::   - Input file containing IP addresses (one per line)
::   - Network connectivity for DNS resolution
::   - nslookup command available
::
:: Output: CSV file with columns: IP,FQDN
:: ============================================================================

:: Display script information
echo ============================================================================
echo FQDN Resolver Script
echo ============================================================================
echo This script resolves IP addresses to Fully Qualified Domain Names (FQDNs)
echo and saves the results to a CSV file.
echo.

:: Get input file path from user
:get_input
set /p "input_file=Enter the path to the input file containing IP addresses: "
if "%input_file%"=="" (
    echo Error: Input file path cannot be empty.
    goto get_input
)

:: Check if input file exists
if not exist "%input_file%" (
    echo Error: Input file "%input_file%" not found.
    echo Please check the file path and try again.
    pause
    exit /b 1
)

:: Get output file path from user
:get_output
set /p "output_file=Enter the path for the output CSV file: "
if "%output_file%"=="" (
    echo Error: Output file path cannot be empty.
    goto get_output
)

:: Ensure output file has .csv extension
if /i not "%output_file:~-4%"==".csv" (
    set "output_file=%output_file%.csv"
)

:: Confirm parameters with user
echo.
echo ============================================================================
echo Configuration Summary:
echo Input file:  %input_file%
echo Output file: %output_file%
echo ============================================================================
echo.
set /p "confirm=Proceed with these parameters? (Y/N): "
if /i not "%confirm%"=="Y" (
    echo Operation cancelled by user.
    pause
    exit /b 0
)

echo.
echo Starting IP to FQDN resolution...
echo.

:: Write CSV header
echo IP,FQDN > "%output_file%"

:: Initialize counters for statistics
set "total_count=0"
set "resolved_count=0"
set "failed_count=0"

:: Process each IP address in the input file
for /f "usebackq delims=" %%i in ("%input_file%") do (
    set "ip=%%i"
    set "fqdn="
    set /a "total_count+=1"

    :: Display progress
    echo Processing: !ip!

    :: Run nslookup and extract the name
    for /f "tokens=2 delims=:" %%a in ('nslookup !ip! 2^>nul ^| findstr /C:"Name:"') do (
        set "fqdn=%%a"
        set "fqdn=!fqdn:~1!"  :: Trim leading space
    )

    :: Output to CSV (fallback to N/A if no FQDN found)
    if defined fqdn (
        echo !ip!,!fqdn! >> "%output_file%"
        set /a "resolved_count+=1"
        echo   ^> Resolved to: !fqdn!
    ) else (
        echo !ip!,N/A >> "%output_file%"
        set /a "failed_count+=1"
        echo   ^> No FQDN found
    )
)

:: Display completion summary
echo.
echo ============================================================================
echo Resolution Complete!
echo ============================================================================
echo Total IPs processed: %total_count%
echo Successfully resolved: %resolved_count%
echo Failed to resolve: %failed_count%
echo Results saved to: %output_file%
echo ============================================================================

endlocal
pause