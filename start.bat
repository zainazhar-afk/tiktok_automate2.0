@echo off
echo ============================================
echo   TikTok Automate - Startup
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found! Install Python 3.10+ first.
    pause
    exit /b 1
)

:: Check FFmpeg
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] FFmpeg not found. Install ffmpeg for video processing.
    echo Download: https://ffmpeg.org/download.html
)

:: Check yt-dlp
yt-dlp --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [INFO] Installing yt-dlp...
    pip install yt-dlp
)

:: Install backend dependencies
echo.
echo [1/3] Installing backend Python dependencies...
cd /d "%~dp0backend"
pip install -r requirements.txt --quiet

:: Install frontend dependencies
echo [2/3] Installing frontend Node dependencies...
cd /d "%~dp0frontend"
call npm install --silent

:: Start backend
echo [3/3] Starting services...
echo.
echo Starting FastAPI backend on http://localhost:8000
cd /d "%~dp0backend"
start "TikTok Automate - Backend" cmd /c "python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

:: Wait for backend
timeout /t 3 /nobreak >nul

:: Start frontend
echo Starting Next.js frontend on http://localhost:3000
cd /d "%~dp0frontend"
start "TikTok Automate - Frontend" cmd /c "npm run dev"

echo.
echo ============================================
echo   Backend:  http://localhost:8000/docs
echo   Frontend: http://localhost:3000
echo ============================================
echo.
echo Close this window to stop both services.
pause
