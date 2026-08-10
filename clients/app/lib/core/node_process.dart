import 'package:flutter_riverpod/flutter_riverpod.dart';

// Sem `dart:io` no topo: a Web não tem processos, e importar direto quebraria
// a compilação para navegador. A implementação real entra por importação
// condicional — desktop recebe a de verdade, o resto recebe uma que não faz
// nada e diz isso honestamente.
import 'node_process_stub.dart'
    if (dart.library.io) 'node_process_io.dart';

/// Como terminou a tentativa de subir o Nó.
enum PartidaDoNo {
  /// Subiu (ou pelo menos o processo nasceu; quem confirma é o vigia).
  iniciado,

  /// Esta plataforma não sobe processo — Web, e por ora também Android.
  indisponivel,

  /// Não achamos o executável do Nó. É o caso do desenvolvimento sem
  /// instalador: o app não sabe onde o Python mora.
  naoEncontrado,

  /// Tentou e falhou. A mensagem vai no log e na tela.
  falhou,
}

/// Quem sobe e derruba o Nó (ADR-046).
///
/// A regra dura desta camada: **só derrubamos o que nós subimos**. Se você já
/// tinha um `lumbra dev` rodando no terminal, o app usa esse e não encosta
/// nele — matar o servidor de alguém que estava depurando seria uma traição
/// difícil de perdoar, e o sintoma (o Nó "morre sozinho") é dos piores de
/// diagnosticar.
abstract class GerenteDoNo {
  /// Sobe o Nó. Só deve ser chamado quando o vigia disse que ele NÃO está
  /// no ar — subir um segundo Nó na mesma porta só produziria confusão.
  Future<PartidaDoNo> iniciar();

  /// Derruba o Nó **se** fomos nós que o subimos. Idempotente.
  Future<void> parar();

  /// Verdadeiro quando este app é dono do processo em execução.
  bool get somosDonos;

  /// O que explicar ao usuário quando algo deu errado (vazio se está tudo bem).
  String get ultimoErro;
}

final gerenteDoNoProvider = Provider<GerenteDoNo>((ref) {
  final gerente = criarGerenteDoNo();
  ref.onDispose(gerente.parar);
  return gerente;
});
