# clipeverything setup (Windows). Safe to re-run: it only installs what is missing
# and updates yt-dlp. Run with:
#   powershell -ExecutionPolicy Bypass -File setup.ps1
param([string]$Model = "small")

# "Continue", not "Stop": Windows PowerShell 5.1 turns harmless native-program warnings (pip, Hugging Face)
# into fatal errors under "Stop". Every important step below checks $LASTEXITCODE itself.
$ErrorActionPreference = "Continue"
$Base = Join-Path $env:USERPROFILE ".clipeverything"
$Venv = Join-Path $Base "venv"
$Py   = Join-Path $Venv "Scripts\python.exe"
New-Item -ItemType Directory -Force -Path $Base | Out-Null

function Refresh-Path {
    $m = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $u = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$m;$u"
}
function Has($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Winget-Install($id) {
    if (-not (Has winget)) { throw "winget is missing. Install 'App Installer' from the Microsoft Store, then re-run." }
    Write-Host "Installing $id ..."
    winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements | Out-Host
    Refresh-Path
}

Write-Host "== clipeverything setup =="

# 1. FFmpeg
if (-not ((Has ffmpeg) -and (Has ffprobe))) { Winget-Install "Gyan.FFmpeg" }

# 2. A JavaScript runtime (YouTube needs one for yt-dlp)
if (-not ((Has deno) -or (Has node))) { Winget-Install "DenoLand.Deno" }

# 3. Python 3.10-3.13 (the AI libraries do not support the newest Python yet)
function Find-Python {
    $old = $ErrorActionPreference
    $ErrorActionPreference = "Continue"   # native stderr must not abort the script
    try {
        $cands = @()
        if (Has py) {
            foreach ($line in (& py -0p 2>$null)) {
                if ($line -match '([A-Za-z]:\\[^\r\n]*?python[^\\]*\.exe)') { $cands += $Matches[1] }
            }
        }
        foreach ($c in (Get-Command python, python3 -All -ErrorAction SilentlyContinue)) { $cands += $c.Source }
        $found = @{}
        foreach ($exe in ($cands | Select-Object -Unique)) {
            $v = & $exe -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $v) { $found[$v.Trim()] = $exe }
        }
        foreach ($v in "3.12", "3.11", "3.13", "3.10") { if ($found.ContainsKey($v)) { return $found[$v] } }
        return $null
    } finally { $ErrorActionPreference = $old }
}
$SysPy = Find-Python
if (-not $SysPy) {
    Winget-Install "Python.Python.3.12"
    $SysPy = Find-Python
    if (-not $SysPy) { throw "Python 3.12 was installed but could not be found. Close this window, open a new one and re-run." }
}
Write-Host "Using Python: $SysPy"

# 4. Virtual environment + packages
if (-not (Test-Path $Py)) { & $SysPy -m venv $Venv }
if (-not (Test-Path $Py)) { throw "could not create the Python environment at $Venv" }
& $Py -m pip install --quiet --upgrade pip
# OpenCV 5 dropped the face detector we use, so stay on 4.x
& $Py -m pip install --quiet --upgrade "yt-dlp[default]" faster-whisper "opencv-python-headless<5" numpy
if ($LASTEXITCODE -ne 0) { throw "pip install failed" }

# 5. Whisper speech model (downloaded once; 'small' is about 460 MB)
Write-Host "Downloading the '$Model' speech model (first time only) ..."
& $Py -c "from faster_whisper import WhisperModel; WhisperModel('$Model', device='cpu', compute_type='int8'); print('model ok')"
if ($LASTEXITCODE -ne 0) { throw "could not download the Whisper model" }

# 6. Check everything
$Clip = Join-Path $PSScriptRoot "clip.py"
& $Py $Clip doctor
if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Done. Restart Claude Code, then say:  clip this video <link>"
} else {
    exit 1
}
