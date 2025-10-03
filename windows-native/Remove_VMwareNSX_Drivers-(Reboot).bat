REM ==============================================================================
REM Script Name: Remove_VMwareNSX_Drivers-(Reboot).bat
REM Description: Removes VMware NSX network security drivers and services from
REM              Windows system with automatic system reboot. Handles driver file
REM              deletion, service removal, and provides comprehensive logging.
REM
REM Purpose: Clean removal of VMware NSX components including:
REM          - vsepflt.sys/vsepflt service (VMware NSX Endpoint Protection Filter)
REM          - vnetflt.sys/vnetflt service (VMware NSX Network Filter)
REM          - vnetwfp.sys/vnetwfp service (VMware NSX Network WFP Filter)
REM
REM Requirements:
REM   - Administrative privileges required
REM   - Windows environment with sc.exe, takeown.exe, icacls.exe utilities
REM   - Write access to C:\Windows\Logs directory
REM
REM Input Parameters:
REM   %1 - Optional: Reboot delay in seconds (default: 60)
REM   %2 - Optional: Custom log file path (default: C:\Windows\Logs\Remove_VMwareNSX_Drivers.log)
REM
REM Usage Examples:
REM   Remove_VMwareNSX_Drivers-(Reboot).bat
REM   Remove_VMwareNSX_Drivers-(Reboot).bat 120
REM   Remove_VMwareNSX_Drivers-(Reboot).bat 90 "C:\Temp\cleanup.log"
REM
REM Output:
REM   - Log file: Configurable (default: C:\Windows\Logs\Remove_VMwareNSX_Drivers.log)
REM   - Console output: Silent execution (all output redirected to log)
REM   - System reboot: Automatic if drivers found and processed
REM
REM Process Flow:
REM   1. Parses input parameters for custom reboot delay and log path
REM   2. Creates log directory and initializes logging
REM   3. Iterates through predefined driver-service pairs
REM   4. For each found driver:
REM      - Stops associated Windows service
REM      - Deletes the service registration
REM      - Takes ownership of driver file
REM      - Grants full permissions to administrators
REM      - Deletes the driver file
REM      - Verifies successful removal
REM   5. If drivers were processed, initiates system reboot with specified delay
REM   6. Provides summary of operations performed
REM
REM Exit Codes: Uses standard Windows batch errorlevel conventions
REM
REM Notes:
REM   - Uses delayed expansion for dynamic variable handling
REM   - All operations logged with timestamps
REM   - Includes verification steps for service and file removal
REM   - Non-destructive if target drivers not present
REM   - Automatic reboot only occurs if drivers were actually processed
REM
REM Author: Areen Agrawal
REM Version: 1.1
REM ==============================================================================
@echo off
setlocal enabledelayedexpansion

:: Parse input parameters
set "rebootDelay=60"
set "logPath=C:\Windows\Logs"
set "logFile=%logPath%\Remove_VMwareNSX_Drivers.log"

:: Process parameter 1 - Reboot delay (optional)
if not "%~1"=="" (
    set "rebootDelay=%~1"
    echo Custom reboot delay specified: !rebootDelay! seconds
)

:: Process parameter 2 - Custom log file path (optional)
if not "%~2"=="" (
    set "logFile=%~2"
    for %%F in ("!logFile!") do set "logPath=%%~dpF"
    echo Custom log file specified: !logFile!
)

:: Create log directory if missing
if not exist "!logPath!" (
    mkdir "!logPath!"
)

:: Start log with parameter information
echo Removing VMware NSX drivers with reboot >> "!logFile!"
echo Started at %date% %time% >> "!logFile!"
echo Reboot delay: !rebootDelay! seconds >> "!logFile!"
echo Log file: !logFile! >> "!logFile!"
echo. >> "!logFile!"

:: Define driver-service pairs
set "drivers[0]=vsepflt.sys"
set "services[0]=vsepflt"

set "drivers[1]=vnetflt.sys"
set "services[1]=vnetflt"

set "drivers[2]=vnetwfp.sys"
set "services[2]=vnetwfp"

set "found=0"

:: Loop through drivers
for /L %%i in (0,1,2) do (
    call set "driver=%%drivers[%%i]%%"
    call set "service=%%services[%%i]%%"
    set "driverPath=C:\Windows\System32\drivers\!driver!"

    if exist "!driverPath!" (
        echo === Found !driver! === >> "!logFile!"

        :: Stop service
        echo Stopping service: !service! >> "!logFile!"
        sc stop !service! >> "!logFile!" 2>&1

        :: Delete service
        echo Deleting service: !service! >> "!logFile!"
        sc delete !service! >> "!logFile!" 2>&1

        :: Take ownership and grant permissions
        echo Taking ownership and granting rights for !driver! >> "!logFile!"
        takeown /f "!driverPath!" >> "!logFile!" 2>&1
        icacls "!driverPath!" /grant administrators:F >> "!logFile!" 2>&1

        :: Delete driver file
        echo Deleting driver file: !driver! >> "!logFile!"
        del /f /q "!driverPath!" >> "!logFile!" 2>&1

        :: Verification
        echo Verifying service removal... >> "!logFile!"
        sc query !service! | findstr /i "SERVICE_NAME" >nul
        if !errorlevel! == 0 (
            echo [!] Service !service! still present >> "!logFile!"
        ) else (
            echo [+] Service !service! successfully removed >> "!logFile!"
        )

        echo Verifying file deletion... >> "!logFile!"
        if exist "!driverPath!" (
            echo [!] File !driver! still exists >> "!logFile!"
        ) else (
            echo [+] File !driver! successfully deleted >> "!logFile!"
        )

        echo. >> "!logFile!"
        set "found=1"
    )
)

if "!found!"=="1" (
    echo One or more drivers processed. See results above. >> "!logFile!"
    echo Rebooting system in !rebootDelay! seconds to finalize cleanup... >> "!logFile!"
    echo. >> "!logFile!"
    shutdown /r /t !rebootDelay! /c "Rebooting after VMware NSX driver cleanup in !rebootDelay! seconds." /f
) else (
    echo No target VMware NSX drivers found. Nothing to do. >> "!logFile!"
)

echo Finished at %date% %time% >> "!logFile!"
echo. >> "!logFile!"

endlocal