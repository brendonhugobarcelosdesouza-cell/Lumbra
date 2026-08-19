import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api.dart';
import 'node_process.dart';

/// Em que pé está o Nó — a primeira coisa que o app precisa saber.
enum NodeState {
  /// Ainda perguntando. Só no começo; não vira tela de erro.
  verificando,

  /// Respondeu `/health`. Tudo o mais faz sentido.
  noAr,

  /// Estamos subindo o Nó agora (sidecar). É espera, não erro.
  subindo,

  /// Não respondeu. NADA no app funciona sem isso.
  foraDoAr,

  /// Nasceu, continua vivo, e passou do tempo que uma partida deveria levar.
  /// Não é "fora do ar" — o processo existe — e não é mais "subindo", porque
  /// a essa altura ninguém deveria seguir esperando em silêncio.
  demorandoDemais,
}

/// Quanto tempo uma partida pode levar antes de virar suspeita.
///
/// Quatro minutos porque recuperar um banco interrompido no Windows passa de
/// um; menos que isso acusaria de travado um Nó que está trabalhando.
const _pacienciaComAPartida = Duration(minutes: 4);

/// Vigia do Nó (P2-e, ADR-046).
///
/// Sem isto, o Nó fora do ar aparecia como um erro diferente em cada tela —
/// "não foi possível carregar as conversas", "…os procedimentos", "…a
/// memória" — e nenhum deles dizia a verdade, que é: o servidor não está
/// rodando. Um problema, uma explicação.
///
/// É também o primeiro degrau do sidecar: quando o app passar a SUBIR o Nó
/// sozinho, quem decide que ele precisa subir é este vigia.
class EstadoDoNo extends Notifier<NodeState> {
  Timer? _relogio;
  bool _jaTentamosSubir = false;
  DateTime? _nascendoDesde;

  @override
  NodeState build() {
    ref.onDispose(() => _relogio?.cancel());
    unawaited(_verificar());
    return NodeState.verificando;
  }

  /// Pergunta de novo agora (o botão "Tentar de novo" e a volta do foco).
  Future<void> verificarAgora() {
    // pedido explícito do usuário zera a desistência: se ele instalou o Nó
    // agora, merece uma nova tentativa de subir
    _jaTentamosSubir = false;
    _nascendoDesde = null;
    return _verificar();
  }

  Future<void> _verificar() async {
    _relogio?.cancel();
    try {
      await ref.read(opsApiProvider).healthHealthGet();
      state = NodeState.noAr;
    } catch (_) {
      // qualquer falha aqui é "não respondeu": diferenciar recusa de conexão,
      // timeout e DNS não muda NADA do que o usuário pode fazer
      state = await _tentarSubir();
    }
    // fora do ar (ou subindo), pergunta com frequência — a pessoa está
    // esperando; no ar, só de vez em quando, para perceber uma queda sem
    // virar ruído
    final intervalo = state == NodeState.noAr
        ? const Duration(seconds: 20)
        : const Duration(seconds: 3);
    // 'demorandoDemais' continua perguntando de 3 em 3: se o Nó finalmente
    // subir, o app entra sozinho, sem exigir que ninguém clique em nada.
    _relogio = Timer(intervalo, _verificar);
  }

  /// Só para teste: finge que a partida começou noutro momento.
  ///
  /// Existe porque a alternativa seria esperar quatro minutos de verdade
  /// numa suíte que roda em segundos, ou injetar um relógio inteiro para
  /// exercitar um `DateTime.now()`. Nomeado com `debug` para que ninguém o
  /// use por engano em código de produção.
  @visibleForTesting
  void debugNasceuEm(DateTime quando) => _nascendoDesde = quando;

  /// Só para teste: verifica sem zerar a contagem da partida.
  @visibleForTesting
  Future<void> debugVerificarSemZerar() => _verificar();

  /// Sobe o Nó UMA vez por sessão de fora-do-ar (ADR-046).
  ///
  /// Uma só: se o Nó não sobe, insistir a cada 3 segundos criaria uma fila de
  /// processos zumbis e esconderia a causa real. Falhou, a tela explica e o
  /// usuário decide — é dele a máquina.
  Future<NodeState> _tentarSubir() async {
    final gerente = ref.read(gerenteDoNoProvider);

    // Processo NOSSO ainda vivo é Nó nascendo, não Nó ausente. Sem esta
    // linha, o vigia perguntava de novo três segundos depois, via que já
    // tinha tentado uma vez e declarava "fora do ar" — enquanto o Nó
    // trabalhava. E ele pode trabalhar bastante: recuperar um banco
    // interrompido leva mais de meio minuto (adendo ao ADR-069).
    //
    // Mas COM TETO. A primeira versão desta linha não tinha, e trocou um
    // problema por outro: o app passou a esperar para sempre, com o mesmo
    // círculo girando, por um Nó que podia estar travado. Prometer que algo
    // está acontecendo sem ter como saber se ainda está é tão desonesto
    // quanto desistir cedo demais.
    if (gerente.somosDonos) {
      _nascendoDesde ??= DateTime.now();
      if (DateTime.now().difference(_nascendoDesde!) < _pacienciaComAPartida) {
        return NodeState.subindo;
      }
      return NodeState.demorandoDemais;
    }
    _nascendoDesde = null;

    if (_jaTentamosSubir) return NodeState.foraDoAr;
    _jaTentamosSubir = true;

    final resultado = await gerente.iniciar();
    // 'subindo' só quando o processo nasceu: o vigia é quem confirma que
    // ele passou a responder. Prometer "no ar" aqui seria adivinhação.
    return resultado == PartidaDoNo.iniciado ? NodeState.subindo : NodeState.foraDoAr;
  }
}

final nodeStateProvider = NotifierProvider<EstadoDoNo, NodeState>(EstadoDoNo.new);
