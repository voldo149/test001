; Instalador de Capturador (Inno Setup 6). Lo compila la acción de GitHub después de PyInstaller:
;   iscc /DVersion=2.3 capturador\instalador.iss   ->   Output\Capturador-Setup-2.3.exe
#ifndef Version
  #define Version "1.0"
#endif

[Setup]
AppId={{8E5B2D41-3F6A-4C9B-9D7E-2A1F4B6C8D90}
AppName=Capturador
AppVersion={#Version}
AppVerName=Capturador {#Version}
AppPublisher=Capturador
; Instalación solo para el usuario: no pide permisos de administrador.
PrivilegesRequired=lowest
DefaultDirName={localappdata}\Programs\Capturador
DisableProgramGroupPage=yes
OutputDir=..\Output
OutputBaseFilename=Capturador-Setup-{#Version}
SetupIconFile=icono.ico
UninstallDisplayIcon={app}\Capturador.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Si la app está abierta, el instalador pide cerrarla (para poder actualizar).
CloseApplications=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "escritorio"; Description: "Crear un acceso directo en el escritorio"
Name: "iniciowindows"; Description: "Abrir con Windows (escondida en la bandeja, junto al reloj)"; Flags: unchecked

[Files]
Source: "..\dist\Capturador\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; AppUserModelID igual al de la ventana: el icono anclado y la ventana abierta son uno solo.
Name: "{userprograms}\Capturador"; Filename: "{app}\Capturador.exe"; AppUserModelID: "CapturadorSilksong"
Name: "{userdesktop}\Capturador"; Filename: "{app}\Capturador.exe"; AppUserModelID: "CapturadorSilksong"; Tasks: escritorio
Name: "{userstartup}\Capturador"; Filename: "{app}\Capturador.exe"; Parameters: "--bandeja"; AppUserModelID: "CapturadorSilksong"; Tasks: iniciowindows

[Run]
Filename: "{app}\Capturador.exe"; Description: "Abrir Capturador"; Flags: nowait postinstall skipifsilent
