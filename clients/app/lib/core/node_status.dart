import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'api.dart';

/// Em que pé está o Nó — a primeira coisa que o app precisa saber.
enum NodeState {
  /// Ainda perguntando. Só no começo; não vira tela de erro.
  verificando,

  /// Respondeu `/health`. Tudo o mais faz sentido.
  noAr,

  /// Não respondeu. NADA no app funciona sem isso.
  foraDoAr,
}

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

  @override
  NodeState build() {
    ref.onDispose(() => _relogio?.cancel());
    unawaited(_verificar());
    return NodeState.verificando;
  }

  /// Pergunta de novo agora (o botão "Tentar de novo" e a volta do foco).
  Future<void> verificarAgora() => _verificar();

  Future<void> _verificar() async {
    _relogio?.cancel();
    try {
      await ref.read(opsApiProvider).healthHealthGet();
      state = NodeState.noAr;
    } catch (_) {
      // qualquer falha aqui é "não respondeu": diferenciar recusa de conexão,
      // timeout e DNS não muda NADA do que o usuário pode fazer
      state = NodeState.foraDoAr;
    }
    // fora do ar, pergunta com frequência (a pessoa está esperando voltar);
    // no ar, só de vez em quando, para perceber uma queda sem virar ruído
    final intervalo = state == NodeState.foraDoAr
        ? const Duration(seconds: 4)
        : const Duration(seconds: 20);
    _relogio = Timer(intervalo, _verificar);
  }
}

final nodeStateProvider = NotifierProvider<EstadoDoNo, NodeState>(EstadoDoNo.new);
