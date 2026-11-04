<#
.SYNOPSIS
    Builds every WSL Manager distribution file with one command.

.DESCRIPTION
    Run from anywhere (the script works in its own folder):

        powershell -ExecutionPolicy Bypass -File build.ps1

    Output in dist\ :
        WSLManager.exe                         GUI, a single file that needs no Python
        wslmgr.exe                             command-line tool (console)
        installer\WSLManager-Setup-X.Y.Z.exe   installer (when Inno Setup 6.3+ is found)
        WSLManager-X.Y.Z-portable.zip          both executables + README + LICENSE
        SHA256SUMS.txt                         checksums of the files above

    By default a virtual environment is created in .venv (or reused), PyInstaller is
    installed into it with a pinned version, and the unit tests run before the build.
    The CI build job runs this same script, so the local build and the release build
    cannot drift apart.

    Keep this file ASCII only: Windows PowerShell 5.1 reads files without a BOM as ANSI.

.PARAMETER Python
    The Python 3.10+ interpreter to build with. Default: the Python Launcher (py -3),
    then python on PATH.

.PARAMETER NoVenv
    Use the interpreter directly instead of .venv (used by CI, where it is disposable).

.PARAMETER SkipTests
    Do not run the unit tests before building.

.PARAMETER SkipInstaller
    Do not build the installer, even if Inno Setup is installed.

.PARAMETER RequireInstaller
    Fail when Inno Setup is not found (default: warn and skip the installer).

.PARAMETER Iscc
    Path to ISCC.exe (Inno Setup compiler). Default: $env:ISCC, then the usual install
    folders, then iscc on PATH.
#>
[CmdletBinding()]
param(
    [string]$Python = "",
    [switch]$NoVenv,
    [switch]$SkipTests,
    [switch]$SkipInstaller,
    [switch]$RequireInstaller,
    [string]$Iscc = ""
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

# Pinned so that a new PyInstaller release cannot change or break the build unnoticed.
# Raise it on purpose (and check the build) when updating.
$PyInstallerVersion = "6.22.3"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Dist = Join-Path $Root "dist"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked([string]$What, [string]$Exe, [string[]]$Arguments) {
    # pip and PyInstaller write their progress to stderr. Windows PowerShell 5.1 turns that
    # into error records when its output is redirected, and "Stop" would then abort a build
    # that is fine. Let the exit code decide instead.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Exe @Arguments
    }
    finally {
        $ErrorActionPreference = $previous
    }
    if ($LASTEXITCODE -ne 0) {
        throw "$What failed with exit code $LASTEXITCODE"
    }
}

function Get-AppVersion {
    # The single source of the version is wsl_core\__init__.py (pyproject.toml must match;
    # tests\test_packaging.py checks that).
    $text = [System.IO.File]::ReadAllText((Join-Path $Root "wsl_core\__init__.py"))
    $match = [regex]::Match($text, '(?m)^__version__\s*=\s*"([^"]+)"')
    if (-not $match.Success) {
        throw "__version__ was not found in wsl_core\__init__.py"
    }
    $version = $match.Groups[1].Value
    # The installer (VersionInfoVersion) and the exe version resource need numbers only.
    if ($version -notmatch '^\d+\.\d+\.\d+$') {
        throw "The build needs a numeric X.Y.Z version, but wsl_core says '$version'"
    }
    return $version
}

function Get-BasePython {
    # Returns the interpreter as an array: the executable and its leading arguments.
    if ($Python) {
        return ,@($Python)
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return ,@("py", "-3")
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return ,@("python")
    }
    throw "Python 3.10 or later was not found. Install it from https://www.python.org/ or pass -Python <path to python.exe>."
}

function Invoke-Python([string]$What, [string[]]$Interpreter, [string[]]$Arguments) {
    $exe = $Interpreter[0]
    $leading = @()
    if ($Interpreter.Count -gt 1) {
        $leading = $Interpreter[1..($Interpreter.Count - 1)]
    }
    Invoke-Checked $What $exe (@($leading) + @($Arguments))
}

function Find-Iscc {
    if ($Iscc) {
        if (-not (Test-Path -LiteralPath $Iscc)) {
            throw "ISCC.exe was not found at $Iscc"
        }
        return $Iscc
    }
    $candidates = @()
    if ($env:ISCC) {
        $candidates += $env:ISCC
    }
    # Machine-wide installs, then the per-user install that winget uses
    foreach ($base in @(${env:ProgramFiles(x86)}, $env:ProgramFiles)) {
        if ($base) {
            $candidates += (Join-Path $base "Inno Setup 6\ISCC.exe")
        }
    }
    if ($env:LOCALAPPDATA) {
        $candidates += (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    }
    foreach ($candidate in $candidates) {
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    $command = Get-Command iscc -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }
    return $null
}

function Write-Checksums([string]$Directory, [string[]]$Names) {
    # Same format as sha256sum (lower-case hash, two spaces, name; LF line endings), so
    # "sha256sum -c SHA256SUMS.txt" and Get-FileHash can both check the files.
    $lines = foreach ($name in $Names) {
        $hash = (Get-FileHash -LiteralPath (Join-Path $Directory $name) -Algorithm SHA256).Hash
        "$($hash.ToLowerInvariant())  $name"
    }
    $path = Join-Path $Directory "SHA256SUMS.txt"
    [System.IO.File]::WriteAllText($path, (($lines -join "`n") + "`n"), [System.Text.Encoding]::ASCII)
}

Push-Location $Root
try {
    $version = Get-AppVersion
    Write-Host "WSL Manager $version"

    # ---- Python environment -------------------------------------------------------------
    $base = Get-BasePython
    if ($NoVenv) {
        $py = $base
    }
    else {
        $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $venvPython)) {
            Write-Step "Creating the build environment (.venv)"
            Invoke-Python "Creating .venv" $base @("-m", "venv", (Join-Path $Root ".venv"))
        }
        $py = @($venvPython)
    }
    Invoke-Python "Checking the Python version" $py @(
        "-c", "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 'Python 3.10 or later is required')"
    )

    Write-Step "Installing PyInstaller $PyInstallerVersion"
    Invoke-Python "pip install" $py @(
        "-m", "pip", "install", "--disable-pip-version-check", "--quiet", "pyinstaller==$PyInstallerVersion"
    )

    # ---- Tests --------------------------------------------------------------------------
    if (-not $SkipTests) {
        Write-Step "Running the unit tests"
        Invoke-Python "Unit tests" $py @("-m", "unittest", "discover", "-s", "tests")
    }

    # ---- Executables --------------------------------------------------------------------
    Write-Step "Building dist\WSLManager.exe (GUI)"
    Invoke-Python "PyInstaller (GUI)" $py @("-m", "PyInstaller", "--clean", "--noconfirm", "WSLManager.spec")
    Write-Step "Building dist\wslmgr.exe (command line)"
    Invoke-Python "PyInstaller (CLI)" $py @("-m", "PyInstaller", "--clean", "--noconfirm", "WSLManagerCLI.spec")

    $gui = Join-Path $Dist "WSLManager.exe"
    $cli = Join-Path $Dist "wslmgr.exe"
    foreach ($exe in @($gui, $cli)) {
        if (-not (Test-Path -LiteralPath $exe)) {
            throw "$exe was not created"
        }
    }
    $reported = (& $cli --version | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $reported -notmatch [regex]::Escape($version)) {
        throw "wslmgr.exe --version reported '$reported' (exit code $LASTEXITCODE), expected $version"
    }
    Write-Host "wslmgr.exe --version: $reported"

    # ---- Installer ----------------------------------------------------------------------
    $releaseFiles = @()
    $setupName = "WSLManager-Setup-$version.exe"
    if ($SkipInstaller) {
        Write-Step "Skipping the installer (-SkipInstaller)"
    }
    else {
        $isccPath = Find-Iscc
        if ($isccPath) {
            Write-Step "Building dist\installer\$setupName (Inno Setup)"
            Invoke-Checked "Inno Setup" $isccPath @("/Q", "/DAppVersion=$version", (Join-Path $Root "installer\WSLManager.iss"))
            $setup = Join-Path $Dist "installer\$setupName"
            if (-not (Test-Path -LiteralPath $setup)) {
                throw "$setup was not created"
            }
            Copy-Item -LiteralPath $setup -Destination (Join-Path $Dist $setupName) -Force
            $releaseFiles += $setupName
        }
        elseif ($RequireInstaller) {
            throw "Inno Setup 6.3 or later (ISCC.exe) was not found"
        }
        else {
            Write-Warning "Inno Setup 6.3 or later was not found, so the installer is skipped. Install it with: winget install JRSoftware.InnoSetup"
        }
    }

    # ---- Portable ZIP -------------------------------------------------------------------
    $zipName = "WSLManager-$version-portable.zip"
    Write-Step "Packing dist\$zipName"
    $staging = Join-Path $Root "build\portable"
    $folder = Join-Path $staging "WSLManager-$version"
    if (Test-Path -LiteralPath $staging) {
        Remove-Item -LiteralPath $staging -Recurse -Force
    }
    New-Item -ItemType Directory -Path $folder | Out-Null
    foreach ($file in @($gui, $cli, "README.md", "README.ja.md", "LICENSE", "CHANGELOG.md")) {
        Copy-Item -LiteralPath $file -Destination $folder
    }
    $zip = Join-Path $Dist $zipName
    if (Test-Path -LiteralPath $zip) {
        Remove-Item -LiteralPath $zip -Force
    }
    Compress-Archive -LiteralPath $folder -DestinationPath $zip
    $releaseFiles += $zipName
    $releaseFiles += @("WSLManager.exe", "wslmgr.exe")

    Write-Checksums $Dist $releaseFiles

    Write-Step "Done"
    foreach ($name in ($releaseFiles + @("SHA256SUMS.txt"))) {
        $item = Get-Item -LiteralPath (Join-Path $Dist $name)
        Write-Host ("  dist\{0,-40} {1,8:N1} MB" -f $name, ($item.Length / 1MB))
    }
}
finally {
    Pop-Location
}
