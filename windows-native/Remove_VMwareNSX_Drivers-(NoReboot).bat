REM ==============================================================================
REM Script Name: Remove_VMwareNSX_Drivers-(NoReboot).bat
REM Description: Removes VMware NSX network security drivers and services from
REM              Windows system without requiring a reboot. Handles driver file
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
REM Input Parameters: None (hardcoded driver/service definitions)
REM
REM Output:
REM   - Log file: C:\Windows\Logs\Remove_VMwareNSX_Drivers.log
REM   - Console output: Silent execution (all output redirected to log)
REM
REM Process Flow:
REM   1. Creates log directory and initializes logging
REM   2. Iterates through predefined driver-service pairs
REM   3. For each found driver:
REM      - Stops associated Windows service
REM      - Deletes the service registration
REM      - Takes ownership of driver file
REM      - Grants full permissions to administrators
REM      - Deletes the driver file
REM      - Verifies successful removal
REM   4. Provides summary of operations performed
REM
REM Exit Codes: Uses standard Windows batch errorlevel conventions
REM
REM Notes:
REM   - Uses delayed expansion for dynamic variable handling
REM   - All operations logged with timestamps
REM   - Includes verification steps for service and file removal
REM   - Non-destructive if target drivers not present
REM
REM Author: Areen Agrawal
REM Version: 1.0
REM ==============================================================================
@echo off
setlocal enabledelayedexpansion

:: Set log path
set "logPath=C:\Windows\Logs"
set "logFile=%logPath%\Remove_VMwareNSX_Drivers.log"

:: Create log directory if missing
if not exist "%logPath%" (
    mkdir "%logPath%"
)

:: Start log
echo Removing VMware NSX drivers >> "%logFile%"
echo Starting at %date% %time% >> "%logFile%"
echo. >> "%logFile%"

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
        echo === Found !driver! === >> "%logFile%"

        :: Stop service
        echo Stopping service: !service! >> "%logFile%"
        sc stop !service! >> "%logFile%" 2>&1

        :: Delete service
        echo Deleting service: !service! >> "%logFile%"
        sc delete !service! >> "%logFile%" 2>&1

        :: Take ownership and grant permissions
        echo Taking ownership and granting rights for !driver! >> "%logFile%"
        takeown /f "!driverPath!" >> "%logFile%" 2>&1
        icacls "!driverPath!" /grant administrators:F >> "%logFile%" 2>&1

        :: Delete driver file
        echo Deleting driver file: !driver! >> "%logFile%"
        del /f /q "!driverPath!" >> "%logFile%" 2>&1

        :: Verification
        echo Verifying service removal... >> "%logFile%"
        sc query !service! | findstr /i "SERVICE_NAME" >nul
        if !errorlevel! == 0 (
            echo [!] Service !service! still present >> "%logFile%"
        ) else (
            echo [+] Service !service! successfully removed >> "%logFile%"
        )

        echo Verifying file deletion... >> "%logFile%"
        if exist "!driverPath!" (
            echo [!] File !driver! still exists >> "%logFile%"
        ) else (
            echo [+] File !driver! successfully deleted >> "%logFile%"
        )

        echo. >> "%logFile%"
        set "found=1"
    )
)

if "!found!"=="1" (
    echo One or more drivers processed. See results above. >> "%logFile%"
) else (
    echo No target VMware NSX drivers found. Nothing to do. >> "%logFile%"
)

echo Finished at %date% %time% >> "%logFile%"
echo. >> "%logFile%"

endlocal