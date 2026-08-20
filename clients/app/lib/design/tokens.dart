/// Os valores que definem a densidade visual da Lumbra.
///
/// Existe porque, até aqui, cada tela inventou o próprio `EdgeInsets.all(12)`
/// e o próprio `BorderRadius.circular(10)`. Enquanto o app era uma lista de
/// telas soltas isso passava; a partir do momento em que a moldura, a coluna
/// de conversas e o painel de contexto dividem a mesma janela, a diferença de
/// dois pixels entre um cartão e o vizinho é o que separa "interface
/// desenhada" de "interface montada".
///
/// A regra: nenhum número solto no código de tela. Se um valor não está aqui,
/// ou ele merece estar, ou ele não merece existir.
library;

import 'package:flutter/widgets.dart';

/// Espaçamento. Escala de 4 em 4 — o suficiente para ter escolha, pouco o
/// bastante para não haver dúvida sobre qual usar.
///
/// Os nomes são tamanhos e não usos ("médio", não "entre cartões") de
/// propósito: nome por uso envelhece na primeira vez que o mesmo valor serve
/// para outra coisa, e aí ou se mente no nome ou se duplica a constante.
abstract final class Espaco {
  static const nada = 0.0;
  static const micro = 2.0;
  static const minimo = 4.0;
  static const curto = 8.0;
  static const medio = 12.0;
  static const largo = 16.0;
  static const amplo = 20.0;
  static const grande = 24.0;
  static const enorme = 32.0;
  static const vasto = 40.0;
}

/// Raio de canto. Quanto maior a superfície, maior o raio — um selo de 18px
/// com raio 16 vira uma pílula sem querer.
abstract final class Raio {
  /// Selos, contadores, marcadores de score.
  static const selo = 6.0;

  /// Itens de menu, botões, chips.
  static const item = 8.0;

  /// Cartões e caixas de conteúdo.
  static const cartao = 12.0;

  /// Superfícies grandes: o campo de escrita, diálogos.
  static const painel = 16.0;

  /// As mesmas medidas já como `BorderRadius`, e **const**.
  ///
  /// `BorderRadius.circular()` não é construtor constante, então usá-lo
  /// impede o widget de ser `const` e obriga a reconstruí-lo a cada quadro.
  /// Numa lista que rola, isso é desperdício silencioso — o tipo de custo que
  /// não aparece em teste nenhum e aparece na bateria de um notebook.
  static const bordaSelo = BorderRadius.all(Radius.circular(selo));
  static const bordaItem = BorderRadius.all(Radius.circular(item));
  static const bordaCartao = BorderRadius.all(Radius.circular(cartao));
  static const bordaPainel = BorderRadius.all(Radius.circular(painel));

  /// Pílula: para contadores e selos arredondados por completo.
  static const pilula = BorderRadius.all(Radius.circular(999));
}

/// Larguras das colunas da moldura.
///
/// Números, e não frações da janela, porque o conteúdo delas é de largura
/// fixa por natureza: um nome de seção não fica melhor com 30% de tela, e um
/// título de conversa truncado é ruim em qualquer proporção. Quem estica é a
/// conversa, que é onde a leitura acontece.
abstract final class Coluna {
  /// Barra lateral com rótulos.
  static const lateral = 220.0;

  /// Barra lateral recolhida: só os ícones.
  static const lateralRecolhida = 60.0;

  /// Lista de conversas.
  static const colecao = 280.0;

  /// Painel de contexto à direita.
  static const contexto = 300.0;

  /// Largura máxima de leitura confortável no meio.
  ///
  /// Linha longa demais cansa: o olho perde o começo da seguinte. Este é o
  /// limite da BOLHA, não da coluna — a coluna cresce e o texto se centra.
  static const leitura = 720.0;
}

/// Quando a moldura muda de forma.
///
/// Não são tamanhos de aparelho, e sim os pontos em que uma coluna deixa de
/// caber. Pensar em "celular/tablet/desktop" leva a interface a acertar os
/// três aparelhos que se testou e errar todos os outros.
abstract final class Largura {
  /// Abaixo disto não cabe barra lateral nem coluna: uma coisa por vez, com
  /// a navegação em gaveta.
  static const compacta = 720.0;

  /// Cabe a barra lateral e o conteúdo. A lista de conversas ainda não —
  /// ela vira a própria tela, e abrir uma conversa a substitui.
  static const media = 1100.0;

  /// Cabem barra lateral, lista de conversas e a conversa.
  static const larga = 1400.0;

  /// Cabem as três colunas E o painel de contexto, ainda sobrando largura de
  /// leitura decente no meio.
  ///
  /// O número saiu de uma conta, não do gosto: 220 + 280 + 300 = 800 px de
  /// molduras. Abrir o painel de contexto a 1400 deixaria 600 px para a
  /// conversa; a 1100, deixaria 300 — e aí o painel estaria roubando
  /// justamente aquilo que a tela existe para mostrar. O teste em
  /// `tokens_test.dart` guarda essa conta.
  static const total = 1700.0;
}

/// Durações de animação.
///
/// Curtas de propósito. Numa ferramenta de uso contínuo, a animação existe
/// para explicar de onde a coisa veio — não para ser notada. O que se nota
/// duas vezes por dia encanta; o que se nota duzentas, irrita.
abstract final class Duracao {
  /// Realce ao passar o mouse, foco, seleção.
  static const toque = Duration(milliseconds: 120);

  /// Painel abrindo, coluna recolhendo.
  static const painel = Duration(milliseconds: 220);
}

/// Opacidades com significado, para não haver 0.45 solto no código.
abstract final class Opacidade {
  /// Seção que existe no menu mas ainda não foi construída.
  static const futuro = 0.45;

  /// Elemento desabilitado por estado (enviando, sem permissão).
  static const inerte = 0.38;
}
