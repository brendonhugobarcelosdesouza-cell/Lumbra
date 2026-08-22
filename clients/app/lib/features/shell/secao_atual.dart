import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Os nomes das seções, em um lugar só.
///
/// Eram constantes privadas dentro do `HomeShell`. Deixam de poder ser
/// quando outra tela precisa NAVEGAR: a Visão geral tem cartões que levam
/// para Documentos e Aprovações, e um cartão que manda para uma seção
/// escrita à mão como `'Documentos'` quebra em silêncio no dia em que o
/// nome mudar — o clique simplesmente não faz nada.
abstract final class Secoes {
  static const visaoGeral = 'Visão geral';
  static const conversas = 'Conversas';
  static const memoria = 'Memória';
  static const documentos = 'Documentos';
  static const procedimentos = 'Procedimentos';
  static const aprovacoes = 'Aprovações';
  static const agentes = 'Agentes';
  static const dispositivos = 'Dispositivos';

  /// A ordem em que as seções vivem no `IndexedStack`.
  ///
  /// Esta lista e a de filhos do `IndexedStack` precisam concordar. Ficam
  /// perto uma da outra de propósito, e há teste para o caso de alguém
  /// acrescentar uma seção só de um lado.
  static const ordem = [
    visaoGeral,
    conversas,
    memoria,
    documentos,
    procedimentos,
    aprovacoes,
    agentes,
    dispositivos,
  ];
}

/// Onde a pessoa está agora.
///
/// A Lumbra abre na Visão geral: é a única tela que responde "o que tem aqui
/// e está tudo bem?" sem exigir que se escolha alguma coisa primeiro.
final secaoAtualProvider = StateProvider<String>((_) => Secoes.visaoGeral);
