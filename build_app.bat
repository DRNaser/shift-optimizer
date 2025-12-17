@echo off
echo ==========================================
echo      SHIFT OPTIMIZER - BUILD TOOL
echo ==========================================
echo.

echo 1. Building React Frontend...
cd frontend
call npm install
call npm run build
if %ERRORLEVEL% NEQ 0 (
    echo Frontend build failed!
    pause
    exit /b %ERRORLEVEL%
)
cd ..

echo.
echo 2. Packaging Application...
echo This may take a while...
python -m PyInstaller --noconfirm --clean --onedir --windowed --name "ShiftOptimizer" --add-data "frontend/dist;site" --add-data "backend_py/src;src" --add-data "backend_py/data;data" --paths "backend_py" --collect-all ortools --hidden-import=uvicorn.logging --hidden-import=uvicorn.loops --hidden-import=uvicorn.loops.auto --hidden-import=uvicorn.protocols --hidden-import=uvicorn.protocols.http --hidden-import=uvicorn.protocols.http.auto --hidden-import=uvicorn.lifespan --hidden-import=uvicorn.lifespan.on backend_py/desktop_main.py

if %ERRORLEVEL% NEQ 0 (
    echo Packaging failed!
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ==========================================
echo      BUILD COMPLETE!
echo ==========================================
echo App location: dist\ShiftOptimizer\ShiftOptimizer.exe
echo.
pause
