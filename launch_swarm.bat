@echo off
setlocal enabledelayedexpansion

REM Create results directory and clear the results file
set RESULTS_DIR=results
set RESULTS_PATH=%RESULTS_DIR%\results.csv

if not exist %RESULTS_DIR% (
    mkdir %RESULTS_DIR%
)
echo.>%RESULTS_PATH%

REM Set swarm size and proposals
set SWARM_SIZE=30
set PROPOSALS[0]=Go Left
set PROPOSALS[1]=Go Right
set PROPOSALS[2]=Stay Put
set PROPOSALS[3]=Go Forward

REM Launch robots
for /L %%i in (1,1,%SWARM_SIZE%) do (
    set /A IDX=!random! %% 4
    set "PROPOSAL=!PROPOSALS[%IDX%]!"
    set "ROBOT_ID=R%%i"

    echo Launching Robot !ROBOT_ID! with proposal '!PROPOSAL!'

    start /B python robot.py --robot-id !ROBOT_ID! --proposal "!PROPOSAL!" --swarm-size %SWARM_SIZE%
)

REM Wait for all robots to finish
:waitloop
timeout /t 2 >nul
tasklist | findstr /I /C:"python.exe" >nul
if %ERRORLEVEL% == 0 goto waitloop

echo All robots have finished.

endlocal
