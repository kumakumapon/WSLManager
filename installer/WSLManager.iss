; WSL Manager installer script for Inno Setup 6.
;
; Build (from the repository root, after building dist\WSLManager.exe and dist\wslmgr.exe):
;   iscc /DAppVersion=1.0.0 installer\WSLManager.iss
; The result is dist\installer\WSLManager-Setup-<version>.exe.
;
; Defaults to a per-user install (no administrator rights, %LOCALAPPDATA%\Programs).
; The user can choose an all-users install (Program Files) in the install dialog, or with
; /ALLUSERS on the command line; /CURRENTUSER forces the per-user install.
;
; Keep this file ASCII only. Non-ASCII text lives in the *.isl message files, which are
; saved as UTF-8 with a BOM.

#if VER < EncodeVer(6, 3, 0)
  #error This script needs Inno Setup 6.3 or later (x64compatible).
#endif

; The version comes from the build (pyproject.toml): iscc /DAppVersion=X.Y.Z
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
; Where the built executables are, and where the installer is written.
#ifndef DistDir
  #define DistDir "..\dist"
#endif
#ifndef OutputDirPath
  #define OutputDirPath "..\dist\installer"
#endif

#define AppName "WSL Manager"
#define AppExeName "WSLManager.exe"
#define CliExeName "wslmgr.exe"
#define AppUrl "https://github.com/kumakumapon/WSLManager"
; Must match the Named Mutex created by wslmgr.py. Setup and the uninstaller refuse to
; replace or remove the application while it is running.
#define AppMutexName "Global\WSLManager_SingleInstance_Mutex"

[Setup]
; AppId identifies this application for upgrades and uninstalling. NEVER change it.
AppId={{8B6B5F71-92D9-4A1C-9145-812D3E9E9C6A}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=kumakumapon
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#AppVersion}.0
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup
DefaultDirName={autopf}\WSL Manager
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
AppMutex={#AppMutexName}
SetupMutex=WSLManagerSetupMutex
; AppMutex only covers the GUI. Do not let Setup close a running wslmgr.exe on its own:
; it may be in the middle of an export or a scheduled snapshot, and killing it would
; leave a broken backup. If a file is in use, Setup stops instead.
CloseApplications=no
; Tell running programs that the PATH changed (only matters when the PATH task is chosen).
ChangesEnvironment=yes
LicenseFile=..\LICENSE
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
OutputDir={#OutputDirPath}
OutputBaseFilename=WSLManager-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl,CustomMessages.en.isl"
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl,CustomMessages.ja.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
; Both PATH tasks are OFF by default. Only the one that matches the install mode is shown.
Name: "addtopath_user"; Description: "{cm:AddToPathUser}"; GroupDescription: "{cm:CommandLineToolGroup}"; Flags: unchecked; Check: not IsAdminInstallMode
Name: "addtopath_system"; Description: "{cm:AddToPathSystem}"; GroupDescription: "{cm:CommandLineToolGroup}"; Flags: unchecked; Check: IsAdminInstallMode

[Files]
Source: "{#DistDir}\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#DistDir}\{#CliExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent runasoriginaluser

; User data (settings, logs and, above all, snapshots) is NOT removed on uninstall: snapshots
; are backups of WSL distributions. They live outside the install folder
; (%APPDATA%\WSLManager and %USERPROFILE%\WSLSnapshots), so there is no [UninstallDelete].

[Code]
const
  UserEnvironmentKey = 'Environment';
  SystemEnvironmentKey = 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment';
  { One environment variable may hold up to 32,767 characters. Stay well below that. }
  MaxPathLength = 30000;

function PathRootKey(): Integer;
begin
  if IsAdminInstallMode then
    Result := HKEY_LOCAL_MACHINE
  else
    Result := HKEY_CURRENT_USER;
end;

function PathSubkey(): String;
begin
  if IsAdminInstallMode then
    Result := SystemEnvironmentKey
  else
    Result := UserEnvironmentKey;
end;

{ Compare PATH entries ignoring case, surrounding blanks and a trailing backslash. }
function NormalizePathEntry(const Entry: String): String;
begin
  Result := Trim(Entry);
  while (Length(Result) > 1) and (Result[Length(Result)] = '\') do
    Delete(Result, Length(Result), 1);
  Result := Lowercase(Result);
end;

{ True if Dir is one of the ';'-separated entries of Paths (whole entries only). }
function PathHasEntry(const Paths, Dir: String): Boolean;
var
  Rest, Entry, Wanted: String;
  P: Integer;
begin
  Result := False;
  Wanted := NormalizePathEntry(Dir);
  Rest := Paths;
  while Rest <> '' do
  begin
    P := Pos(';', Rest);
    if P = 0 then
    begin
      Entry := Rest;
      Rest := '';
    end
    else
    begin
      Entry := Copy(Rest, 1, P - 1);
      Delete(Rest, 1, P);
    end;
    if (Trim(Entry) <> '') and (NormalizePathEntry(Entry) = Wanted) then
    begin
      Result := True;
      Exit;
    end;
  end;
end;

{ Append Dir to Paths without creating a leading, trailing or doubled ';'. }
function PathAppend(const Paths, Dir: String): String;
begin
  if Trim(Paths) = '' then
    Result := Dir
  else if Paths[Length(Paths)] = ';' then
    Result := Paths + Dir
  else
    Result := Paths + ';' + Dir;
end;

{ Remove only the entries equal to Dir. Every other entry is kept exactly as it was. }
function PathRemove(const Paths, Dir: String): String;
var
  Rest, Entry, Wanted: String;
  P: Integer;
  HasMore, HaveKept: Boolean;
begin
  Result := '';
  HaveKept := False;
  Wanted := NormalizePathEntry(Dir);
  Rest := Paths;
  HasMore := Rest <> '';
  while HasMore do
  begin
    P := Pos(';', Rest);
    if P = 0 then
    begin
      Entry := Rest;
      Rest := '';
      HasMore := False;
    end
    else
    begin
      Entry := Copy(Rest, 1, P - 1);
      Delete(Rest, 1, P);
    end;
    if (Trim(Entry) = '') or (NormalizePathEntry(Entry) <> Wanted) then
    begin
      if HaveKept then
        Result := Result + ';' + Entry
      else
        Result := Entry;
      HaveKept := True;
    end;
  end;
end;

procedure AddToPath(const Dir: String);
var
  Paths: String;
begin
  if not RegQueryStringValue(PathRootKey(), PathSubkey(), 'Path', Paths) then
    Paths := '';
  if PathHasEntry(Paths, Dir) then
  begin
    Log('PATH already contains ' + Dir + '; left unchanged.');
    Exit;
  end;
  Paths := PathAppend(Paths, Dir);
  if Length(Paths) > MaxPathLength then
  begin
    Log('PATH would exceed ' + IntToStr(MaxPathLength) + ' characters; not changed.');
    if not WizardSilent then
      MsgBox(CustomMessage('PathNotUpdated'), mbInformation, MB_OK);
    Exit;
  end;
  { Keep the value type REG_EXPAND_SZ so entries such as %USERPROFILE%\bin keep working. }
  if not RegWriteExpandStringValue(PathRootKey(), PathSubkey(), 'Path', Paths) then
  begin
    Log('Could not write PATH.');
    if not WizardSilent then
      MsgBox(CustomMessage('PathNotUpdated'), mbInformation, MB_OK);
  end;
end;

procedure RemoveFromPath(const Dir: String);
var
  Paths, NewPaths: String;
begin
  if not RegQueryStringValue(PathRootKey(), PathSubkey(), 'Path', Paths) then
    Exit;
  if not PathHasEntry(Paths, Dir) then
    Exit;
  NewPaths := PathRemove(Paths, Dir);
  if Trim(NewPaths) = '' then
    RegDeleteValue(PathRootKey(), PathSubkey(), 'Path')
  else
    RegWriteExpandStringValue(PathRootKey(), PathSubkey(), 'Path', NewPaths);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    if WizardIsTaskSelected('addtopath_user') or WizardIsTaskSelected('addtopath_system') then
      AddToPath(ExpandConstant('{app}'));
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  { Remove only our own folder; do nothing if it was never added. }
  if CurUninstallStep = usPostUninstall then
    RemoveFromPath(ExpandConstant('{app}'));
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  { Scheduled snapshots point at the installed wslmgr.exe by its absolute path. }
  if CurPageID = wpFinished then
    WizardForm.FinishedLabel.Caption :=
      WizardForm.FinishedLabel.Caption + #13#10#13#10 + CustomMessage('ScheduledSnapshotNote');
end;
