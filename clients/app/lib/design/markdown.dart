import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';

import 'tokens.dart';

/// Como a Lumbra escreve.
///
/// O padrão do `MarkdownStyleSheet.fromTheme` é legível e genérico — serve
/// para qualquer app. Aqui o texto do assistente é o CONTEÚDO PRINCIPAL da
/// tela: é o que a pessoa vai ler por minutos seguidos, com tabelas de
/// valores, trechos de documento e listas. Cada decisão abaixo é sobre
/// leitura longa, não sobre enfeite.
MarkdownStyleSheet estiloDaLumbra(BuildContext context) {
  final tema = Theme.of(context);
  final cores = tema.colorScheme;
  final corpo = tema.textTheme.bodyMedium!.copyWith(
    // 1.6 e não o 1.2 padrão: parágrafo apertado obriga o olho a caçar a
    // linha seguinte, e é o que faz um texto longo "cansar" sem que se
    // saiba dizer por quê
    height: 1.6,
    fontSize: 14,
  );
  final mono = TextStyle(
    fontFamily: 'monospace',
    fontSize: 12.5,
    height: 1.45,
    color: cores.onSurface,
  );

  return MarkdownStyleSheet.fromTheme(tema).copyWith(
    p: corpo,
    pPadding: const EdgeInsets.only(bottom: Espaco.medio),

    // Títulos com pouca diferença de tamanho entre si e MUITA diferença de
    // espaço acima: numa resposta, o que separa seções é a pausa, não a
    // altura da letra. Títulos enormes dentro de uma conversa gritam.
    h1: corpo.copyWith(fontSize: 17, fontWeight: FontWeight.w700, height: 1.3),
    h2: corpo.copyWith(fontSize: 15.5, fontWeight: FontWeight.w700, height: 1.3),
    h3: corpo.copyWith(fontSize: 14.5, fontWeight: FontWeight.w600, height: 1.3),
    h1Padding: const EdgeInsets.only(top: Espaco.amplo, bottom: Espaco.curto),
    h2Padding: const EdgeInsets.only(top: Espaco.largo, bottom: Espaco.curto),
    h3Padding: const EdgeInsets.only(top: Espaco.medio, bottom: Espaco.minimo),

    listBullet: corpo,
    listIndent: Espaco.amplo,
    listBulletPadding: const EdgeInsets.only(right: Espaco.curto),

    // Código com fundo próprio e SEM borda: a mudança de superfície já
    // separa; a borda somada viraria uma caixa dentro de outra caixa.
    code: mono.copyWith(backgroundColor: cores.surfaceContainerHigh),
    codeblockDecoration: BoxDecoration(
      color: cores.surfaceContainerHigh,
      borderRadius: Raio.bordaItem,
    ),
    codeblockPadding: const EdgeInsets.all(Espaco.medio),

    // Tabela: a referência mostra números alinhados em colunas, e é aí que
    // ela ganha da lista. Linhas horizontais discretas, nenhuma vertical —
    // grade fechada compete com o dado.
    tableHead: corpo.copyWith(
      fontSize: 12.5,
      fontWeight: FontWeight.w600,
      color: cores.onSurfaceVariant,
    ),
    tableBody: corpo.copyWith(fontSize: 13, height: 1.3),
    tableBorder: TableBorder(
      horizontalInside: BorderSide(color: cores.outlineVariant),
    ),
    tableCellsPadding: const EdgeInsets.symmetric(
      horizontal: Espaco.curto,
      vertical: Espaco.curto,
    ),
    tableColumnWidth: const IntrinsicColumnWidth(),

    blockquote: corpo.copyWith(color: cores.onSurfaceVariant),
    blockquoteDecoration: BoxDecoration(
      border: Border(left: BorderSide(color: cores.primary, width: 2)),
    ),
    blockquotePadding: const EdgeInsets.only(left: Espaco.medio),

    // sem opacidade: `withOpacity` e `withValues` trocaram de nome entre
    // versões do Flutter, e essa é a classe de detalhe que quebra o build de
    // quem clonar o repositório amanhã. Cor sólida resolve igual.
    a: corpo.copyWith(
      color: cores.primary,
      decoration: TextDecoration.underline,
      decorationColor: cores.outline,
    ),
    horizontalRuleDecoration: BoxDecoration(
      border: Border(top: BorderSide(color: cores.outlineVariant)),
    ),
  );
}
