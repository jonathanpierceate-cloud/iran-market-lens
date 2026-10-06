$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Url = "http://127.0.0.1:8000/"
$LogDir = Join-Path $ProjectDir "data"
$LogPath = Join-Path $LogDir "launcher.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-LauncherLog([string]$Message) {
  $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
  Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
}

function Test-Dashboard {
  try {
    $response = Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2
    return $response.StatusCode -ge 200 -and $response.StatusCode -lt 500
  } catch {
    return $false
  }
}

try {
  if (-not (Test-Dashboard)) {
    $venvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    if (Test-Path -LiteralPath $venvPython) {
      Write-LauncherLog "Starting Uvicorn from the existing virtual environment."
      Start-Process -FilePath $venvPython `
        -ArgumentList "-m uvicorn app.main:app --host 0.0.0.0 --port 8000" `
        -WorkingDirectory $ProjectDir -WindowStyle Hidden | Out-Null
    } else {
      Write-LauncherLog "Virtual environment not found; starting start.bat for first-time setup."
      $startBat = Join-Path $ProjectDir "start.bat"
      Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "`"$startBat`"" `
        -WorkingDirectory $ProjectDir -WindowStyle Hidden | Out-Null
    }
  } else {
    Write-LauncherLog "Dashboard was already running."
  }

  $deadline = (Get-Date).AddSeconds(40)
  while (-not (Test-Dashboard) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
  }

  if (Test-Dashboard) {
    Write-LauncherLog "Opening $Url"
    Start-Process $Url | Out-Null
  } else {
    Write-LauncherLog "Dashboard did not become available before the timeout."
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show(
      "Dashboard did not start. See data\launcher.log for details.",
      "Market Dashboard",
      "OK",
      "Error"
    ) | Out-Null
  }
} catch {
  Write-LauncherLog ("Launcher error: " + $_.Exception.Message)
  Add-Type -AssemblyName PresentationFramework
  [System.Windows.MessageBox]::Show(
    ("Dashboard launcher error:`n" + $_.Exception.Message),
    "Market Dashboard",
    "OK",
    "Error"
  ) | Out-Null
}
