; Inno Setup script for pyscopegui. Built by build.cmd after PyInstaller.
;
; Installs the one-directory PyInstaller build, so Qt stays as
; separate replaceable DLLs -- what the LGPL asks for -- while the user sees a
; single Start menu entry and an uninstaller.
;
; Download Inno Setup from https://jrsoftware.org/isinfo.php if it is missing.

#define AppName "pyscopegui"
#define AppPublisher "davhodg"
#define AppURL "https://github.com/davhodg/pyscopegui"
#define AppExe "pyscopegui.exe"
; build.cmd passes both, from build\version.py. 0.0.0 marks an installer
; compiled by hand, which has no version to give it.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef FileVersion
  #define FileVersion "0.0.0.0"
#endif

[Setup]
AppId={{483F6D58-C656-464A-9908-D4EC833609B4}
AppName={#AppName}
AppVersion={#AppVersion}
; The setup.exe's own version resource. The file version is numbers only,
; and its text is cut at 20 characters, so the full version -- -dev and
; commit included -- goes in the product version, which is not.
VersionInfoVersion={#FileVersion}
VersionInfoTextVersion={#FileVersion}
VersionInfoProductName={#AppName}
VersionInfoCompany={#AppPublisher}
VersionInfoDescription={#AppName} installer
VersionInfoProductTextVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
LicenseFile=..\LICENSE
; The third-party notices on the page after the licence, before anything is
; installed: what comes with pyscopegui is worth reading before it is on the
; machine, not on the way to Finish.
InfoBeforeFile=..\THIRD-PARTY-NOTICES.txt
OutputDir=..\dist
OutputBaseFilename=pyscopegui-{#AppVersion}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; The installer's own icon, and the one Settings > Apps shows for it. The
; shortcuts need nothing: they take theirs from pyscopegui.exe.
SetupIconFile=..\pyscopegui\resources\pyscopegui.ico
UninstallDisplayIcon={app}\{#AppExe}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Setup asks who it is for: everybody, which needs administrator rights and
; is what it suggests, or only the person running it, which needs none.
PrivilegesRequiredOverridesAllowed=dialog commandline
; For the fileassoc task: Explorer is told to look again.
ChangesAssociations=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"
Name: "fileassoc"; Description: "Open .pyscp captures with pyscopegui"; GroupDescription: "File types:"

; A .pyscp is pyscopegui's own, so pyscopegui opens it. A .npz, as captures
; were saved before, is numpy's and many another program's: pyscopegui is only
; offered in Open with for it, and whatever opens them now keeps them. The
; same values as pyscopegui/core/file_types.py writes from Tools > Settings.
; HKA is HKCU for a per-user install and HKLM for an all-users one. A capture
; double-clicked while pyscopegui is open goes to that one
; (pyscopegui/ui/handoff.py).
[Registry]
Root: HKA; Subkey: "Software\Classes\.pyscp"; ValueType: string; ValueName: ""; ValueData: "pyscopegui.capture"; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\.pyscp\OpenWithProgids"; ValueType: string; ValueName: "pyscopegui.capture"; ValueData: ""; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\pyscopegui.capture"; ValueType: string; ValueName: ""; ValueData: "pyscopegui capture"; Flags: uninsdeletekey; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\pyscopegui.capture\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\pyscopegui.capture\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\.npz\OpenWithProgids"; ValueType: string; ValueName: "pyscopegui.npz"; ValueData: ""; Flags: uninsdeletevalue; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\pyscopegui.npz"; ValueType: string; ValueName: ""; ValueData: "pyscopegui capture or NumPy archive"; Flags: uninsdeletekey; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\pyscopegui.npz\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\{#AppExe},0"; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\pyscopegui.npz\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".pyscp"; ValueData: ""; Flags: uninsdeletekey; Tasks: fileassoc
Root: HKA; Subkey: "Software\Classes\Applications\{#AppExe}\SupportedTypes"; ValueType: string; ValueName: ".npz"; ValueData: ""; Tasks: fileassoc

[Files]
Source: "..\dist\pyscopegui\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

; An upgrade would otherwise leave the last version's shortcuts beside the
; new ones, named for a version that is no longer installed. The desktop
; pattern needs a digit-dot after the name, so a shortcut of somebody's own
; that happens to start with "pyscopegui " is left alone.
[InstallDelete]
Type: files; Name: "{group}\{#AppName} *.lnk"
Type: files; Name: "{autodesktop}\{#AppName} ?.*.lnk"

; Named with the version: an installed pyscopegui stays the version it is
; until the next installer, unlike a source folder's entry, which starts
; whatever was last pulled and is called plain pyscopegui.
[Icons]
Name: "{group}\{#AppName} {#AppVersion}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Third party notices"; Filename: "{app}\THIRD-PARTY-NOTICES.txt"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName} {#AppVersion}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start {#AppName}"; Flags: nowait postinstall skipifsilent

[Messages]
; Say plainly that instrument makers' libraries are the user's to install
FinishedLabel=pyscopegui is installed.%n%nInstrument makers' libraries (the PicoScope SDK and others) are not included: install the one for your instrument and pyscopegui will find it.%n%nYour settings live in %%APPDATA%%\pyscopegui and are left alone by upgrades and by uninstalling.
