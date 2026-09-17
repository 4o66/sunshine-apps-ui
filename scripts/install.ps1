# SPDX-License-Identifier: GPL-3.0-or-later
#
# Install sunshine-apps-ui on a Windows machine that has no Python.
#
# The installer is written in Python, which is fine everywhere except the one
# place it matters: a Windows machine has no interpreter to run it with. This
# script is the bootstrap -- the only part of the program that cannot be written
# in the language the program is written in.
#
# It fetches CPython's official embeddable distribution, checks it against the
# hash python.org publishes beside it, and hands over. Everything after that is
# the ordinary installer, including provisioning the interpreter it will keep.
#
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#
# The pinned hash below must match interpreter.py's CPYTHON artifact. There is a
# test that says so, because two copies of one constant is how they drift.

[CmdletBinding()]
param(
    [string]$Prefix = "",
    [switch]$WithoutInterpreter
)

$ErrorActionPreference = "Stop"

$CPythonUrl    = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip"
$CPythonSha256 = "4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3"

$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path (Join-Path $root "src\sunshine_apps_ui"))) {
    throw "Run this from the checkout: $root does not look like one."
}

function Find-Python {
    # Whatever is already here will do for the few seconds the installer runs.
    foreach ($candidate in @("py", "python3", "python")) {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $found) { continue }
        try {
            $version = & $found.Source -c "import sys; print(sys.version_info[:2])" 2>$null
        } catch { continue }
        # The Microsoft Store stub answers `where python` and then does nothing
        # but open the Store, so a version is what proves this is real.
        if ($version) { return $found.Source }
    }
    return $null
}

$python = Find-Python
if ($python) {
    Write-Host "Using the Python already here: $python"
} else {
    Write-Host "No Python on this machine. Fetching one to install with."
    $workspace = Join-Path $env:TEMP ("sunshine-apps-ui-bootstrap-" + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $workspace -Force | Out-Null
    $zip = Join-Path $workspace "python-embed.zip"

    $ProgressPreference = "SilentlyContinue"   # the progress bar makes this slower
    Invoke-WebRequest -Uri $CPythonUrl -OutFile $zip -UseBasicParsing

    $got = (Get-FileHash -Path $zip -Algorithm SHA256).Hash.ToLower()
    if ($got -ne $CPythonSha256) {
        Remove-Item -Recurse -Force $workspace
        throw ("The interpreter did not match its published checksum.`n" +
               "  expected $CPythonSha256`n  got      $got`n" +
               "Nothing was installed.")
    }
    Write-Host "Checksum verified."

    $unpacked = Join-Path $workspace "python"
    Expand-Archive -Path $zip -DestinationPath $unpacked -Force
    # The embeddable distribution ignores PYTHONPATH and imports from nothing
    # but its own zip until its ._pth says otherwise. This one only has to run
    # the installer, which then provisions the interpreter that stays.
    $pth = Get-ChildItem -Path $unpacked -Filter "*._pth" | Select-Object -First 1
    @("python312.zip", ".", "$root\src", "import site") |
        Set-Content -Path $pth.FullName -Encoding ascii
    $python = Join-Path $unpacked "python.exe"
    Write-Host "Bootstrapped with $python"
}

$arguments = @("-m", "sunshine_apps_ui", "--install")
if ($Prefix) { $arguments += @("--prefix", $Prefix) }
$arguments += $(if ($WithoutInterpreter) { "--without-interpreter" } else { "--with-interpreter" })

$env:PYTHONPATH = "$root\src;$env:PYTHONPATH"
Push-Location $root
try {
    & $python @arguments
    $code = $LASTEXITCODE
} finally {
    Pop-Location
}

if ($code -ne 0) { throw "The installer exited $code." }
Write-Host ""
Write-Host "Done. Open Sunshine's web UI to see the tile, or run a scan with:"
Write-Host "  `"$env:LOCALAPPDATA\Programs\sunshine-apps-ui\sunshine-apps-ui.cmd`" --scan"
