; Instalador da Lumbra para Windows (P2-f.3).
;
; Inno Setup de proposito: nao exige conta de desenvolvedor, nao exige
; assinatura para funcionar, e produz UM executavel que qualquer pessoa sabe
; abrir. MSIX daria integracao melhor com a Loja e exigiria certificado --
; peso que nao se justifica para o primeiro instalador de um produto pessoal.
;
; O que este instalador NAO faz, e por que:
;
; * nao pede administrador. A Lumbra instala por usuario
;   (PrivilegesRequired=lowest), em AppData\Local\Programs. Um programa
;   pessoal que exige elevacao para instalar assusta com razao, e nao
;   precisamos de nada fora da conta de quem usa;
; * nao pergunta onde guardar os dados. Eles vao para %LOCALAPPDATA%\Lumbra,
;   ao lado da chave e do banco. Quem quiser noutro disco define
;   LUMBRA_DATA_DIR -- e uma tela de Configuracoes deve tornar isso visivel
;   um dia, porque variavel de ambiente nao e resposta para usuario comum;
; * nao apaga os dados ao desinstalar. Desinstalar um programa nao e
;   consentimento para apagar o que a pessoa escreveu. A pasta fica, e o
;   desinstalador diz onde.

#define Nome "Lumbra"
#define Versao "0.1.0"
#define Autor "Brendon"
#define Executavel "lumbra_app.exe"

[Setup]
AppId={{B6C0E1F2-4A3D-4E5B-9C7A-1D2E3F4A5B6C}
AppName={#Nome}
AppVersion={#Versao}
AppPublisher={#Autor}
DefaultDirName={autopf}\{#Nome}
DefaultGroupName={#Nome}
DisableProgramGroupPage=yes
; por usuario: sem UAC, sem Program Files, sem susto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=Lumbra-{#Versao}-instalador
SetupIconFile=..\clients\app\windows\runner\resources\app_icon.ico
UninstallDisplayIcon={app}\{#Executavel}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; o pacote passa de 350 MB por causa do PostgreSQL e do modelo de
; embeddings; sem isto o Inno recusa arquivos grandes
DiskSpanning=no
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Area de Trabalho"; GroupDescription: "Atalhos:"
Name: "iniciarcomwindows"; Description: "Abrir a Lumbra quando eu ligar o computador"; GroupDescription: "Inicializacao:"; Flags: unchecked

[Files]
; o app e o No inteiro, do jeito que o montar.ps1 deixou -- inclusive a
; pasta `no\`, que o sidecar procura ao lado do executavel (ADR-067)
Source: "..\clients\app\build\windows\x64\runner\Release\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; o modelo de embeddings viaja junto: sem ele, a primeira execucao exigiria
; internet e minutos de espera calada. Vai para a pasta de DADOS, nao para a
; do programa, porque atualizar a Lumbra nao pode apagar 120 MB a toa
Source: "..\dist\modelos\*"; DestDir: "{localappdata}\{#Nome}\modelos"; Flags: ignoreversion recursesubdirs createallsubdirs skipifsourcedoesntexist onlyifdoesntexist

[Icons]
Name: "{group}\{#Nome}"; Filename: "{app}\{#Executavel}"
Name: "{autodesktop}\{#Nome}"; Filename: "{app}\{#Executavel}"; Tasks: desktopicon
Name: "{userstartup}\{#Nome}"; Filename: "{app}\{#Executavel}"; Tasks: iniciarcomwindows

[Run]
Filename: "{app}\{#Executavel}"; Description: "Abrir a Lumbra"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; os LOGS podem ir: sao nossos, nao do usuario
Type: filesandordirs; Name: "{localappdata}\{#Nome}\logs"

[Code]
function EncerrarNoEmExecucao(): Boolean;
var
  Codigo: Integer;
begin
  { Instalar por cima de um No rodando falha com "acesso negado" num arquivo
    qualquer -- erro que nao diz nada sobre a causa. Pedimos que a pessoa
    feche; NAO matamos processo, porque derrubar o No a forca e exatamente o
    que ja machucou o banco uma vez (ADR-071). }
  Result := True;
  if Exec('cmd.exe', '/C tasklist /FI "IMAGENAME eq {#Executavel}" | find /I "{#Executavel}"',
          '', SW_HIDE, ewWaitUntilTerminated, Codigo) then
  begin
    if Codigo = 0 then
    begin
      MsgBox('A Lumbra esta aberta. Feche a janela dela e clique em OK para continuar.' + #13#10 +
             'Nao vou fechar por conta propria: encerrar o No a forca pode danificar o banco.',
             mbInformation, MB_OK);
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  EncerrarNoEmExecucao();
  Result := '';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    { Desinstalar um programa nao e consentimento para apagar o que a pessoa
      escreveu. Dizemos onde os dados estao e deixamos a decisao com ela. }
    MsgBox('A Lumbra foi removida.' + #13#10 + #13#10 +
           'Suas conversas, documentos e memorias continuam em:' + #13#10 +
           ExpandConstant('{localappdata}\{#Nome}') + #13#10 + #13#10 +
           'Apague essa pasta se quiser remover tambem os seus dados.',
           mbInformation, MB_OK);
  end;
end;
