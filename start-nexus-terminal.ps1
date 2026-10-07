$ErrorActionPreference = 'Stop'
$IdeaPath = 'C:\Users\rodri\Desktop\nexus\nexus-ide'
$BatPath = Join-Path $IdeaPath 'nexus-terminal.bat'

if (-not (Test-Path $BatPath)) {
    Write-Error "Bat nao existe: $BatPath"
    exit 1
}

$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = 'cmd.exe'
$psi.WorkingDirectory = $IdeaPath
$psi.UseShellExecute = $true
$psi.WindowStyle = 'Normal'
$psi.Arguments = "/k title NEXUS Terminal && cd /d `"$IdeaPath`" && `"$BatPath`""

$proc = [System.Diagnostics.Process]::Start($psi)
Write-Host "Started NEXUS Terminal (pid=$($proc.Id))"
