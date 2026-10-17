<#
.SYNOPSIS
  Silent install / upgrade / uninstall check for WSLManager-Setup-<version>.exe.

.DESCRIPTION
  Runs the real installer into a temporary folder as the current user and checks what it
  does: files, shortcuts, the uninstall entry, the optional PATH task and the optional
  desktop shortcut, the uninstaller, and that a file in use stops Setup without damaging
  the installed files. Used by CI (the build job) and runnable by hand.

  It never starts WSL Manager, never touches WSL, and never touches user data
  (settings, logs, snapshots). It changes the *user* PATH (HKCU\Environment) only while the
  PATH checks run, and restores the original value and type exactly at the end.

  Not covered here (needs a person or a GUI): an all-users install (UAC), the wizard UI, and
  "Setup refuses while the GUI is running" (the AppMutex check).

  Safety guards (nothing is changed or deleted when one of them stops the script, exit code 2):
  - It refuses to run when WSL Manager is already installed on this machine, because it installs
    and uninstalls with the same AppId and would replace or remove that real installation.
    Run it on a clean machine (such as a CI runner) or uninstall WSL Manager first.
  - It deletes -InstallDir (before and after the checks), so it refuses a folder that is not under
    the temporary folder or that is not empty. -Force overrides this, but never for a drive root
    or your user profile folder.

  This file is ASCII only on purpose so Windows PowerShell 5.1 and PowerShell 7 read it alike.

.EXAMPLE
  pwsh -NoProfile -File installer\verify-installer.ps1 `
      -Setup dist\installer\WSLManager-Setup-1.0.0.exe -InstallDir $env:TEMP\wslm-check -ExpectedVersion 1.0.0
#>
param(
  [Parameter(Mandatory)] [string] $Setup,
  [Parameter(Mandatory)] [string] $InstallDir,
  [string] $ExpectedVersion = '',
  [switch] $Force
)
$ErrorActionPreference = 'Stop'

$Setup = (Resolve-Path $Setup).Path
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
$tempRoot = if ($env:RUNNER_TEMP) { $env:RUNNER_TEMP } else { $env:TEMP }
$SetupLog = Join-Path $tempRoot 'wslm-setup.log'

# The AppId is defined once, in the installer script.
$iss = Get-Content (Join-Path $PSScriptRoot 'WSLManager.iss') -Raw
if ($iss -notmatch '(?m)^AppId=\{\{([0-9A-Fa-f-]+)\}') { throw 'AppId not found in WSLManager.iss' }
$AppId = '{' + $Matches[1] + '}_is1'
$UninstKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppId"
$UninstKeyMachine = "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\$AppId"
$StartMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\WSL Manager.lnk'
$Desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) 'WSL Manager.lnk'
$script:fail = 0

function Check($ok, $label) {
  if ($ok) { "  PASS  $label" } else { "  FAIL  $label"; $script:fail++ }
}

function Get-RawPath {
  $k = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment')
  $has = $k.GetValueNames() -contains 'Path'
  $v = $null; $kind = $null
  if ($has) {
    $v = $k.GetValue('Path', $null, 'DoNotExpandEnvironmentNames')
    $kind = $k.GetValueKind('Path').ToString()
  }
  $k.Close()
  [pscustomobject]@{ Exists = $has; Value = $v; Kind = $kind }
}

function Set-RawPath($value, $kind) {
  $k = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
  if ($null -eq $value) {
    if ($k.GetValueNames() -contains 'Path') { $k.DeleteValue('Path') }
  } else {
    $k.SetValue('Path', $value, [Microsoft.Win32.RegistryValueKind]$kind)
  }
  $k.Close()
}

function Invoke-Setup([string[]] $extra = @()) {
  $a = @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/CURRENTUSER', "/DIR=$InstallDir", "/LOG=$SetupLog") + $extra
  $p = Start-Process $Setup -ArgumentList $a -Wait -PassThru
  $p.ExitCode
}

function Invoke-Uninstall {
  $u = Join-Path $InstallDir 'unins000.exe'
  if (-not (Test-Path $u)) { return -1 }
  $p = Start-Process $u -ArgumentList '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART' -Wait -PassThru
  # Wait (with a timeout) until the files are really gone instead of trusting the return.
  $deadline = (Get-Date).AddSeconds(60)
  while ((Test-Path (Join-Path $InstallDir 'WSLManager.exe')) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 300 }
  $deadline = (Get-Date).AddSeconds(20)
  while ((Test-Path $UninstKey) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 300 }
  $p.ExitCode
}

function Show-SetupLogTail {
  if (Test-Path $SetupLog) {
    '--- tail of the Setup log ---'
    Get-Content $SetupLog -Tail 25
    '-----------------------------'
  }
}

function Stop-Unsafe([string] $message) {
  "ERROR: $message"
  exit 2
}

if ((Test-Path $UninstKey) -or (Test-Path $UninstKeyMachine)) {
  Stop-Unsafe ('WSL Manager is already installed on this machine. This script installs and uninstalls with the ' +
    'same AppId and would replace or remove that installation. Run it on a clean machine or uninstall WSL Manager first.')
}
$protected = @($env:USERPROFILE, $env:LOCALAPPDATA, $env:APPDATA, $env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:SystemDrive) |
  Where-Object { $_ } | ForEach-Object { [IO.Path]::GetFullPath($_).TrimEnd('\') }
if (($InstallDir.TrimEnd('\').Length -le 2) -or ($protected -contains $InstallDir.TrimEnd('\'))) {
  Stop-Unsafe "Refusing to use '$InstallDir': it is a drive root or an important user/system folder (even with -Force)."
}
$tempFull = [IO.Path]::GetFullPath($tempRoot).TrimEnd('\')
$underTemp = $InstallDir.StartsWith($tempFull + '\', [StringComparison]::OrdinalIgnoreCase)
$notEmpty = (Test-Path $InstallDir) -and (@(Get-ChildItem $InstallDir -Force).Count -gt 0)
if ((-not $Force) -and ((-not $underTemp) -or $notEmpty)) {
  Stop-Unsafe ("-InstallDir '$InstallDir' will be deleted before and after the checks, so it must be under '$tempFull' " +
    'and empty or missing. Pass -Force only if you are sure.')
}

$saved = Get-RawPath
"Saved HKCU\Environment\Path: exists=$($saved.Exists) kind=$($saved.Kind) length=$(if ($saved.Value) { $saved.Value.Length } else { 0 })"
Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue
$lock = $null
try {
  '=== 1) default silent install (per-user, no tasks)'
  $code = Invoke-Setup
  Check ($code -eq 0) "Setup exit code is 0 (got $code)"
  if ($code -ne 0) { Show-SetupLogTail }
  Check (Test-Path (Join-Path $InstallDir 'WSLManager.exe')) 'WSLManager.exe is installed'
  Check (Test-Path (Join-Path $InstallDir 'wslmgr.exe')) 'wslmgr.exe is installed'
  Check (Test-Path (Join-Path $InstallDir 'LICENSE')) 'LICENSE is installed'
  Check (Test-Path (Join-Path $InstallDir 'unins000.exe')) 'the uninstaller is installed'
  Check (Test-Path $UninstKey) 'the uninstall entry is in HKCU (installed without administrator rights)'
  Check (-not (Test-Path $UninstKeyMachine)) 'nothing is written to HKLM'
  Check (Test-Path $StartMenu) 'the Start menu shortcut exists'
  Check (-not (Test-Path $Desktop)) 'no desktop shortcut by default'
  $now = Get-RawPath
  Check (($now.Value -eq $saved.Value) -and ($now.Kind -eq $saved.Kind)) 'PATH is unchanged by default'
  $cli = Join-Path $InstallDir 'wslmgr.exe'
  $out = (& $cli --version | Out-String).Trim()
  Check (($LASTEXITCODE -eq 0) -and ($out -match '\d+\.\d+\.\d+')) "wslmgr.exe --version works ('$out')"
  if ($ExpectedVersion) {
    Check ($out -match [regex]::Escape($ExpectedVersion)) "wslmgr.exe reports the expected version $ExpectedVersion"
    $entry = Get-ItemProperty $UninstKey
    Check ($entry.DisplayVersion -eq $ExpectedVersion) "the uninstall entry shows version $($entry.DisplayVersion)"
  }
  # Windows PowerShell 5.1 turns a native command's stderr into a terminating error under
  # 'Stop'; relax it for this one call that is expected to write to stderr.
  $previous = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  $null = & $cli nosuchcommand 2>&1
  $invalidExit = $LASTEXITCODE
  $ErrorActionPreference = $previous
  Check ($invalidExit -eq 2) "an invalid command exits with 2 (got $invalidExit)"

  '=== 2) install over the same folder (upgrade)'
  $code = Invoke-Setup
  Check ($code -eq 0) "Setup exit code is 0 (got $code)"
  $entries = @(Get-ChildItem (Split-Path $UninstKey -Parent) | Where-Object { $_.PSChildName -eq $AppId })
  Check ($entries.Count -eq 1) 'the uninstall entry is not duplicated'

  '=== 3) uninstall'
  $code = Invoke-Uninstall
  Check ($code -eq 0) "the uninstaller exit code is 0 (got $code)"
  Check (-not (Test-Path (Join-Path $InstallDir 'WSLManager.exe'))) 'WSLManager.exe is removed'
  Check (-not (Test-Path (Join-Path $InstallDir 'wslmgr.exe'))) 'wslmgr.exe is removed'
  Check (-not (Test-Path $UninstKey)) 'the uninstall entry is removed'
  Check (-not (Test-Path $StartMenu)) 'the Start menu shortcut is removed'
  Check (-not (Test-Path $InstallDir)) 'the (now empty) install folder is removed'

  '=== 4) optional desktop shortcut'
  $code = Invoke-Setup @('/TASKS=desktopicon')
  Check (($code -eq 0) -and (Test-Path $Desktop)) 'the desktop shortcut is created when the task is chosen'
  $null = Invoke-Uninstall
  Check (-not (Test-Path $Desktop)) 'the desktop shortcut is removed on uninstall'

  '=== 5) PATH task (per-user): add and remove'
  $base = '%USERPROFILE%\bin;C:\Tools\a b'
  Set-RawPath $base 'ExpandString'
  $code = Invoke-Setup @('/TASKS=addtopath_user')
  $p1 = Get-RawPath
  Check ($code -eq 0) "Setup exit code is 0 (got $code)"
  Check ($p1.Value -eq "$base;$InstallDir") 'the install folder is appended to PATH'
  Check ($p1.Kind -eq 'ExpandString') 'the value stays REG_EXPAND_SZ'
  Check ($p1.Value.StartsWith('%USERPROFILE%')) '%USERPROFILE% is kept unexpanded'
  $null = Invoke-Setup @('/TASKS=addtopath_user')
  Check ((Get-RawPath).Value -eq $p1.Value) 'installing again does not add it twice'
  $null = Invoke-Uninstall
  $p3 = Get-RawPath
  Check (($p3.Value -eq $base) -and ($p3.Kind -eq 'ExpandString')) 'uninstalling restores the original PATH'

  '=== 6) PATH task: trailing ;, empty PATH, no PATH value'
  Set-RawPath 'C:\x;' 'ExpandString'
  $null = Invoke-Setup @('/TASKS=addtopath_user')
  Check ((Get-RawPath).Value -eq "C:\x;$InstallDir") 'no doubled ; is created after a trailing ;'
  $null = Invoke-Uninstall
  # A trailing ; is only a separator; it cannot be told apart from the one added for us.
  Check ((Get-RawPath).Value -eq 'C:\x') 'uninstalling gives back an equivalent PATH'
  Set-RawPath '' 'ExpandString'
  $null = Invoke-Setup @('/TASKS=addtopath_user')
  Check ((Get-RawPath).Value -eq $InstallDir) 'no leading ; is created in an empty PATH'
  $null = Invoke-Uninstall
  Check (-not (Get-RawPath).Exists) 'a PATH value that becomes empty is deleted again'
  Set-RawPath $null 'String'
  $null = Invoke-Setup @('/TASKS=addtopath_user')
  Check ((Get-RawPath).Value -eq $InstallDir) 'PATH is created when it did not exist'
  $null = Invoke-Uninstall

  '=== 7) PATH task: other entries are left alone'
  Set-RawPath "C:\keep1;$($InstallDir.ToUpper())\;C:\keep2" 'ExpandString'
  $null = Invoke-Setup @('/TASKS=addtopath_user')
  Check ((Get-RawPath).Value -eq "C:\keep1;$($InstallDir.ToUpper())\;C:\keep2") 'not added again when already present (other case, trailing backslash)'
  $null = Invoke-Uninstall
  Check ((Get-RawPath).Value -eq 'C:\keep1;C:\keep2') 'only our own entry is removed'
  Set-RawPath ';C:\a;;C:\b' 'ExpandString'
  $null = Invoke-Setup @('/TASKS=addtopath_user')
  Check ((Get-RawPath).Value -eq ";C:\a;;C:\b;$InstallDir") 'leading and doubled empty entries are kept when adding'
  $null = Invoke-Uninstall
  Check ((Get-RawPath).Value -eq ';C:\a;;C:\b') 'leading and doubled empty entries are kept when removing'

  '=== 8) a file in use stops Setup without damaging the installed files'
  Set-RawPath $saved.Value $(if ($saved.Kind) { $saved.Kind } else { 'String' })
  $code = Invoke-Setup
  Check ($code -eq 0) "install for the in-use check (got $code)"
  $cliPath = Join-Path $InstallDir 'wslmgr.exe'
  $guiPath = Join-Path $InstallDir 'WSLManager.exe'
  $hashCli = (Get-FileHash $cliPath).Hash
  $hashGui = (Get-FileHash $guiPath).Hash
  # A running exe is locked by Windows; an exclusive lock reproduces that without running anything.
  $lock = [IO.File]::Open($cliPath, 'Open', 'Read', 'None')
  $code = Invoke-Setup
  Check ($code -ne 0) "Setup does not report success while wslmgr.exe is in use (exit code $code)"
  $lock.Close(); $lock = $null
  Check ((Get-FileHash $cliPath).Hash -eq $hashCli) 'wslmgr.exe is unchanged'
  Check ((Get-FileHash $guiPath).Hash -eq $hashGui) 'WSLManager.exe is unchanged'
  $code = Invoke-Setup
  Check ($code -eq 0) "Setup succeeds again once the file is free (got $code)"
}
finally {
  if ($lock) { $lock.Close() }
  # Always put the user PATH back exactly as it was.
  Set-RawPath $saved.Value $(if ($saved.Kind) { $saved.Kind } else { 'String' })
  $after = Get-RawPath
  "PATH restored: identical=$(($after.Value -eq $saved.Value) -and ($after.Kind -eq $saved.Kind)) exists=$($after.Exists)"
  # Each cleanup step is separate so that one failure does not skip the rest.
  try {
    if (Test-Path (Join-Path $InstallDir 'unins000.exe')) { $null = Invoke-Uninstall }
  } catch { "cleanup (uninstall) failed: $_" }
  try { Remove-Item $InstallDir -Recurse -Force -ErrorAction SilentlyContinue } catch { "cleanup (folder) failed: $_" }
  try { Remove-Item $Desktop -Force -ErrorAction SilentlyContinue } catch { "cleanup (shortcut) failed: $_" }
}
"=== failed checks: $script:fail"
exit $script:fail
