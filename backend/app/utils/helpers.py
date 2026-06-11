import os
import subprocess
import shutil
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Known Python install paths
_PYTHON_PATHS = [
    shutil.which("python"),
    shutil.which("python3"),
    shutil.which("py"),
    r"C:\Python314\python.exe",
    r"C:\Python313\python.exe",
    r"C:\Python312\python.exe",
    r"C:\Python311\python.exe",
    r"C:\Python310\python.exe",
    r"C:\Python39\python.exe",
    r"C:\Python38\python.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python314\python.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python313\python.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python312\python.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python311\python.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python\Python310\python.exe"),
    os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe"),
    r"C:\Users\Voltic\AppData\Local\Programs\Python\Python314\python.exe",
]


def find_python() -> Optional[str]:
    for path in _PYTHON_PATHS:
        if path and os.path.isfile(path):
            return path
    return None


def _venv_scripts() -> Optional[str]:
    """Scripts dir of the active or project .venv."""
    import sys

    candidates = [
        os.path.join(os.path.dirname(sys.executable), "Scripts"),
        str(Path(__file__).resolve().parents[2] / ".venv" / "Scripts"),
    ]
    for scripts in candidates:
        if scripts and os.path.isdir(scripts):
            return scripts
    return None


def find_ytdlp() -> Optional[str]:
    """Find yt-dlp executable via pipx, pip, or direct download."""
    scripts = _venv_scripts()
    if scripts:
        venv_ytdlp = os.path.join(scripts, "yt-dlp.exe")
        if os.path.isfile(venv_ytdlp):
            return venv_ytdlp

    # Check pipx installs
    pipx_paths = [
        os.path.expandvars(r"%USERPROFILE%\.local\bin\yt-dlp.exe"),
        os.path.expandvars(r"%USERPROFILE%\AppData\Local\bin\yt-dlp.exe"),
        os.path.expandvars(r"%USERPROFILE%\.local\pipx\venvs\yt-dlp\Scripts\yt-dlp.exe"),
    ]
    for path in pipx_paths:
        if os.path.isfile(path):
            return path

    # Check pip user install
    python = find_python()
    if python:
        base = os.path.dirname(python)
        scripts_dir = os.path.join(base, "Scripts")
        ytdlp_path = os.path.join(scripts_dir, "yt-dlp.exe")
        if os.path.isfile(ytdlp_path):
            return ytdlp_path

    # Check PATH
    from_path = shutil.which("yt-dlp")
    if from_path:
        return from_path

    return None


def _winget_bin_glob(pattern: str) -> Optional[str]:
    winget_root = os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages"
    )
    if not os.path.isdir(winget_root):
        return None
    for root, _, files in os.walk(winget_root):
        for f in files:
            if f.lower() == pattern.lower():
                return os.path.join(root, f)
    return None


def find_ffmpeg() -> Optional[str]:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path

    winget_ffmpeg = _winget_bin_glob("ffmpeg.exe")
    if winget_ffmpeg:
        return winget_ffmpeg

    extra_paths = [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\ffmpeg.exe",
        os.path.expandvars(r"%USERPROFILE%\ffmpeg\bin\ffmpeg.exe"),
    ]
    for path in extra_paths:
        if os.path.isfile(path):
            return path
    return None


def find_aria2c() -> Optional[str]:
    aria2_path = shutil.which("aria2c")
    if aria2_path:
        return aria2_path

    winget_aria2 = _winget_bin_glob("aria2c.exe")
    if winget_aria2:
        return winget_aria2

    extra_paths = [
        r"C:\aria2\aria2c.exe",
        os.path.expandvars(r"%USERPROFILE%\aria2\aria2c.exe"),
    ]
    for path in extra_paths:
        if os.path.isfile(path):
            return path
    return None


def run_command(cmd: list[str], timeout: int = 120, cwd: Optional[str] = None) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except Exception as e:
        return -1, "", str(e)
