import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:flutter/foundation.dart';

import 'node_process.dart';

/// `up`, não `dev`: `up` é o Nó como PRODUTO — Postgres embutido sem Docker,
/// chave de assinatura própria, sem recarga automática (ADR-069/070). Enquanto
/// isto dizia `dev`, o caminho que o usuário percorre ignorava tudo isso e
/// exigia Docker sem avisar.
///
/// `--seguir-a-entrada` é o que permite desligar o Nó sem matá-lo: fechamos o
/// `stdin` dele, ele vê o fim da entrada e encerra sozinho. No Windows não há
/// sinal para mandar — `kill` vira `TerminateProcess` — e o preço já foi
/// cobrado: o Postgres embutido levou um tiro no meio de um COMMIT e o banco
/// ficou precisando de recuperação (correção ao ADR-069).
const argumentosDoNo = ['up', '--seguir-a-entrada'];

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

    // PEDIR antes de MANDAR. Fechar a entrada padrão é o único canal que
    // funciona nos dois sistemas: no Windows não existe sinal para enviar, e
    // `kill` vira TerminateProcess — foi assim que o Postgres embutido levou
    // um tiro no meio de um COMMIT e o banco precisou de recuperação.
    try {
      await processo.stdin.close();
    } catch (_) {
      // entrada já fechada: seguimos para a espera do mesmo jeito
    }

    // 20 segundos porque desligar o Postgres embutido com checkpoint leva
    // alguns; desistir cedo demais recriaria exatamente o problema que este
    // código existe para evitar.
    final codigo = await processo.exitCode.timeout(
      const Duration(seconds: 20),
      onTimeout: () => _tempoEsgotado,
    );
    if (codigo == _tempoEsgotado) {
      debugPrint('[Nó] não encerrou sozinho em 20s — encerrando à força');
      processo.kill(ProcessSignal.sigkill);
      await processo.exitCode;
    }
  }

  /// Sentinela: nenhum código de saída real é este.
  static const _tempoEsgotado = -999;

  static void _registrar(List<int> bytes) {
    if (!kDebugMode) return;
    // utf8.decode e não String.fromCharCodes: o segundo trata cada byte como
    // um caractere, então "índices" virava "Ã­ndices" no log. `allowMalformed`
    // porque log truncado no meio de um caractere não pode derrubar nada.
    debugPrint('[Nó] ${utf8.decode(bytes, allowMalformed: true).trimRight()}');
  }

  /// Onde procurar o Nó, em ordem de intenção.
  static _Comando? _localizarExecutavel() {
    // 1. Configuração explícita vence tudo (útil para apontar para um Nó
    //    instalado noutro lugar, ou para um script de depuração).
    const definido = String.fromEnvironment('LUMBRA_NODE_EXE');
    if (definido.isNotEmpty && File(definido).existsSync()) {
      return const _Comando(definido, argumentosDoNo, null);
    }

    // 2. Ao lado do app — o que o instalador vai produzir (ADR-046).
    final aoLado = File(
      '${File(Platform.resolvedExecutable).parent.path}'
      '${Platform.pathSeparator}no${Platform.pathSeparator}$_nomeDoExecutavel',
    );
    if (aoLado.existsSync()) return _Comando(aoLado.path, argumentosDoNo, null);

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
          argumentosDoNo,
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
