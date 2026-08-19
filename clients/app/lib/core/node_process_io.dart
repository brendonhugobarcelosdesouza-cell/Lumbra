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

/// Onde o Nó congelado guarda o que disse.
///
/// O app não conhece a pasta de dados da Lumbra — ela é uma decisão do Core.
/// Mas a convenção é estável (`lumbra.shared.paths`) e o valor de apontar o
/// caminho na tela de erro é grande demais para esperar por uma rota da API
/// que, no cenário em questão, justamente não está no ar.
String? get caminhoDoLogDoNoDaPlataforma {
  if (!Platform.isWindows) return null;
  final base = Platform.environment['LOCALAPPDATA'];
  if (base == null || base.isEmpty) return null;
  return '$base\\Lumbra\\logs\\no.log';
}

/// O comando que sobe o Nó à mão — montado a partir do executável que o app
/// REALMENTE encontrou, nunca de um caminho escrito à mão.
///
/// A versão anterior era a constante `cd C:\dev\lumbra\core; ... lumbra dev`.
/// Ela estava errada de duas formas ao mesmo tempo: só valia na máquina de
/// quem escreveu, e mandava rodar `dev` enquanto o app roda `up` — modos
/// diferentes, bancos diferentes (ADR-069). Uma instrução de socorro que
/// leva a outro lugar é pior que nenhuma.
///
/// `null` quando não achamos o Nó: aí não há comando honesto a oferecer, e a
/// tela simplesmente não mostra a caixa.
String? get comandoParaSubirAMaoDaPlataforma {
  final comando = GerenteDoNoDesktop._localizarExecutavel();
  if (comando == null) return null;
  final linha = '"${comando.executavel}" ${comando.argumentos.first}';
  final dir = comando.diretorio;
  // o diretório importa: é dele que o Nó lê o `.env`, e foi por herdar o
  // diretório errado que um Nó já saiu chamando o Docker sem que ninguém
  // tivesse pedido
  return dir == null ? linha : 'cd "$dir"; & $linha';
}

/// Sobe o Nó como processo filho no desktop (ADR-046).
///
/// Enquanto não existe instalador, o executável é procurado subindo o diretório
/// atual até achar o ambiente virtual do repositório. Parece improvisado, e é —
/// mas é honesto: no desenvolvimento o Nó mora no repositório, e o dia em que
/// morar ao lado do app o primeiro candidato da lista resolve sozinho.
class GerenteDoNoDesktop implements GerenteDoNo {
  Process? _processo;

  @override
  bool get somosDonos => _processo != null;

  /// Observável: o motivo costuma chegar DEPOIS da tela ser desenhada,
  /// porque o Nó pode nascer bem e morrer segundos adiante.
  @override
  final ValueNotifier<String> ultimoErro = ValueNotifier('');

  @override
  Future<PartidaDoNo> iniciar() async {
    if (_processo != null) return PartidaDoNo.iniciado;
    if (!Platform.isWindows && !Platform.isLinux && !Platform.isMacOS) {
      return PartidaDoNo.indisponivel;
    }

    final comando = _localizarExecutavel();
    if (comando == null) {
      ultimoErro.value = 'não encontrei o executável do Nó (procurei ao lado do app e no '
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
      _processo!.stdout.listen(_guardar, onError: (_) {});
      _processo!.stderr.listen(_guardar, onError: (_) {});
      unawaited(
        _processo!.exitCode.then((codigo) {
          debugPrint('[Nó] encerrou com código $codigo');
          _processo = null;
          // Um Nó que NASCE e morre logo depois deixava `ultimoErro` vazio:
          // guardávamos só erros de partida. A tela de "Nó fora do ar" então
          // fingia que nada tinha sido tentado e oferecia o comando manual —
          // escondendo justamente a informação que levava à causa. Quem viu o
          // motivo passar foi o log, e ninguém lê o log de um app.
          if (codigo != 0) {
            ultimoErro.value = 'o Nó encerrou com código $codigo.\n${_ultimasLinhas()}';
          }
        }),
      );
      ultimoErro.value = '';
      return PartidaDoNo.iniciado;
    } catch (e) {
      ultimoErro.value = '$e';
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

  /// As últimas linhas que o Nó disse. Pequeno de propósito: só serve para
  /// explicar uma morte, não para ser um visualizador de log.
  final _saida = <String>[];

  void _guardar(List<int> bytes) {
    // utf8.decode e não String.fromCharCodes: o segundo trata cada byte como
    // um caractere, então "índices" virava "Ã­ndices". `allowMalformed`
    // porque log truncado no meio de um caractere não pode derrubar nada.
    final texto = utf8.decode(bytes, allowMalformed: true).trimRight();
    if (texto.isEmpty) return;
    if (kDebugMode) debugPrint('[Nó] $texto');
    _saida.addAll(texto.split('\n'));
    if (_saida.length > 40) _saida.removeRange(0, _saida.length - 40);
  }

  String _ultimasLinhas() {
    final uteis = _saida.where((l) => l.trim().isNotEmpty).toList();
    return uteis.length <= 8 ? uteis.join('\n') : uteis.sublist(uteis.length - 8).join('\n');
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
    if (aoLado.existsSync()) {
      // o diretório de trabalho é FIXADO na pasta do Nó, e não herdado.
      // Herdado, ele é a pasta de onde o atalho foi clicado — e o Nó
      // passaria a obedecer a qualquer `.env` que existisse ali por acaso.
      // Foi assim que o primeiro teste do conjunto falhou: aberto de dentro
      // do repositório, o Nó leu o `.env` do projeto e foi chamar o Docker.
      return _Comando(aoLado.path, argumentosDoNo, aoLado.parent.path);
    }

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
