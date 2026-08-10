import 'dart:async';
import 'dart:io';

import 'package:flutter/foundation.dart';

import 'node_process.dart';

/// `--no-reload` de propósito: com recarga automática o Nó vira uma ÁRVORE de
/// processos, e matar o pai deixaria o filho vivo segurando a porta. Recarga
/// é ferramenta de quem edita o Core, não de quem usa o app.
const _argumentos = ['dev', '--no-reload'];

/// Sobe o Nó como processo filho no desktop (ADR-046).
///
/// Enquanto não existe instalador, o executável é procurado subindo o diretório
/// atual até achar o ambiente virtual do repositório. Parece improvisado, e é —
/// mas é honesto: no desenvolvimento o Nó mora no repositório, e o dia em que
/// morar ao lado do app o primeiro candidato da lista resolve sozinho.
class GerenteDoNoDesktop implements GerenteDoNo {
  Process? _processo;
  String _erro = '';

  @override
  bool get somosDonos => _processo != null;

  @override
  String get ultimoErro => _erro;

  @override
  Future<PartidaDoNo> iniciar() async {
    if (_processo != null) return PartidaDoNo.iniciado;
    if (!Platform.isWindows && !Platform.isLinux && !Platform.isMacOS) {
      return PartidaDoNo.indisponivel;
    }

    final comando = _localizarExecutavel();
    if (comando == null) {
      _erro = 'não encontrei o executável do Nó (procurei ao lado do app e no '
          'ambiente virtual do repositório)';
      return PartidaDoNo.naoEncontrado;
    }

    try {
      _processo = await Process.start(
        comando.executavel,
        comando.argumentos,
        workingDirectory: comando.diretorio,
        // o Nó é filho de verdade: se o app morrer de forma abrupta, o
        // Windows derruba o grupo junto em vez de deixar um servidor órfão
        // segurando a porta
        mode: ProcessStartMode.normal,
      );
      // sem consumir a saída, o buffer do pipe enche e o processo TRAVA. É a
      // falha clássica de sidecar, e o sintoma (fica lento e para) não parece
      // ter nada a ver com log.
      _processo!.stdout.listen(_registrar, onError: (_) {});
      _processo!.stderr.listen(_registrar, onError: (_) {});
      unawaited(
        _processo!.exitCode.then((codigo) {
          debugPrint('[Nó] encerrou com código $codigo');
          _processo = null;
        }),
      );
      _erro = '';
      return PartidaDoNo.iniciado;
    } catch (e) {
      _erro = '$e';
      _processo = null;
      return PartidaDoNo.falhou;
    }
  }

  @override
  Future<void> parar() async {
    final processo = _processo;
    if (processo == null) return; // não somos donos: não encostamos
    _processo = null;
    processo.kill();
    // dá um tempo para encerrar com dignidade antes de desistir
    await processo.exitCode.timeout(
      const Duration(seconds: 5),
      onTimeout: () {
        processo.kill(ProcessSignal.sigkill);
        return -1;
      },
    );
  }

  static void _registrar(List<int> bytes) {
    if (!kDebugMode) return;
    debugPrint('[Nó] ${String.fromCharCodes(bytes).trimRight()}');
  }

  /// Onde procurar o Nó, em ordem de intenção.
  static _Comando? _localizarExecutavel() {
    // 1. Configuração explícita vence tudo (útil para apontar para um Nó
    //    instalado noutro lugar, ou para um script de depuração).
    const definido = String.fromEnvironment('LUMBRA_NODE_EXE');
    if (definido.isNotEmpty && File(definido).existsSync()) {
      return const _Comando(definido, _argumentos, null);
    }

    // 2. Ao lado do app — o que o instalador vai produzir (ADR-046).
    final aoLado = File(
      '${File(Platform.resolvedExecutable).parent.path}'
      '${Platform.pathSeparator}no${Platform.pathSeparator}$_nomeDoExecutavel',
    );
    if (aoLado.existsSync()) return _Comando(aoLado.path, _argumentos, null);

    // 3. Desenvolvimento: sobe do diretório atual procurando o venv do
    //    repositório. Não fixamos caminho de máquina nenhuma.
    var dir = Directory.current;
    for (var i = 0; i < 5; i++) {
      final candidato = File(
        '${dir.path}${Platform.pathSeparator}$_venv'
        '${Platform.pathSeparator}$_nomeDoExecutavel',
      );
      if (candidato.existsSync()) {
        // o Nó espera rodar de dentro de core/ (alembic.ini, migrações)
        final core = Directory('${dir.path}${Platform.pathSeparator}core');
        return _Comando(
          candidato.path,
          _argumentos,
          core.existsSync() ? core.path : dir.path,
        );
      }
      final pai = dir.parent;
      if (pai.path == dir.path) break;
      dir = pai;
    }
    return null;
  }

  static String get _venv => Platform.isWindows ? r'.venv\Scripts' : '.venv/bin';
  static String get _nomeDoExecutavel => Platform.isWindows ? 'lumbra.exe' : 'lumbra';
}

class _Comando {
  const _Comando(this.executavel, this.argumentos, this.diretorio);

  final String executavel;
  final List<String> argumentos;
  final String? diretorio;
}

GerenteDoNo criarGerenteDoNo() => GerenteDoNoDesktop();
