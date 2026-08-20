import 'package:flutter/material.dart';
import 'package:flutter_markdown_plus/flutter_markdown_plus.dart';
import 'package:lumbra_api/api.dart';

import '../../design/markdown.dart';
import '../../design/tokens.dart';
import 'chat_models.dart';

/// As mensagens da conversa.
///
/// As duas não são a mesma coisa com cores diferentes, e por isso não
/// compartilham um widget "bolha genérica". O que a pessoa escreveu é curto,
/// já conhecido e serve de marcador na rolagem — cabe numa bolha compacta,
/// à direita. O que a Lumbra respondeu é longo, novo, tem estrutura e
/// proveniência: precisa de largura de leitura, hierarquia tipográfica e de
/// um lugar para as fontes. Tratá-las igual foi o que fez a tela anterior
/// parecer um aplicativo de mensagens em vez de uma ferramenta de trabalho.
class MensagemDaConversa extends StatelessWidget {
  const MensagemDaConversa(this.bolha, {super.key});

  final ChatBubble bolha;

  @override
  Widget build(BuildContext context) {
    return switch (bolha.role) {
      BubbleRole.user => _DoUsuario(bolha),
      BubbleRole.assistant => _DaLumbra(bolha),
      BubbleRole.error => _DeErro(bolha),
    };
  }
}

class _DoUsuario extends StatelessWidget {
  const _DoUsuario(this.bolha);

  final ChatBubble bolha;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(top: Espaco.grande, bottom: Espaco.curto),
      child: Align(
        alignment: Alignment.centerRight,
        child: ConstrainedBox(
          // mais estreita que a resposta de propósito: é a pergunta, não o
          // conteúdo — ela orienta a rolagem e sai do caminho
          constraints: const BoxConstraints(maxWidth: Coluna.minimaDaConversa),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.end,
            children: [
              if (bolha.quando != null)
                Padding(
                  padding: const EdgeInsets.only(
                    right: Espaco.minimo,
                    bottom: Espaco.minimo,
                  ),
                  child: Text(
                    horaDe(bolha.quando!),
                    style: TextStyle(
                      fontSize: 11,
                      color: cores.onSurfaceVariant,
                    ),
                  ),
                ),
              Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: Espaco.largo,
                  vertical: Espaco.medio,
                ),
                decoration: BoxDecoration(
                  color: cores.surfaceContainerHigh,
                  borderRadius: Raio.bordaCartao,
                ),
                child: SelectableText(
                  bolha.text,
                  style: Theme.of(
                    context,
                  ).textTheme.bodyMedium?.copyWith(fontSize: 14, height: 1.5),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _DaLumbra extends StatelessWidget {
  const _DaLumbra(this.bolha);

  final ChatBubble bolha;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final fontes = bolha.usedCitations;

    return Padding(
      padding: const EdgeInsets.only(top: Espaco.medio, bottom: Espaco.grande),
      child: Align(
        alignment: Alignment.centerLeft,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: Coluna.leitura),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _Assinatura(bolha: bolha),
              const SizedBox(height: Espaco.curto),
              Container(
                width: double.infinity,
                decoration: BoxDecoration(
                  color: cores.surfaceContainerLow,
                  borderRadius: Raio.bordaCartao,
                  border: Border.all(color: cores.outlineVariant),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Padding(
                      padding: const EdgeInsets.fromLTRB(
                        Espaco.amplo,
                        Espaco.largo,
                        Espaco.amplo,
                        // o Markdown já põe espaço abaixo do último parágrafo
                        Espaco.minimo,
                      ),
                      child: MarkdownBody(
                        data: bolha.text,
                        selectable: true,
                        styleSheet: estiloDaLumbra(context),
                      ),
                    ),
                    if (fontes.isNotEmpty) _Fontes(fontes),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// Quem falou, com que modelo e quando.
///
/// O nome do modelo fica AQUI e não só no topo da conversa porque o modelo
/// pode mudar no meio: uma resposta escrita pelo Ollama continua tendo sido
/// escrita por ele depois de a conversa passar para a nuvem. Atribuir a
/// resposta antiga ao modelo novo seria falsificar o registro.
class _Assinatura extends StatelessWidget {
  const _Assinatura({required this.bolha});

  final ChatBubble bolha;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final discreto = TextStyle(fontSize: 11.5, color: cores.onSurfaceVariant);

    return Row(
      children: [
        Icon(Icons.auto_awesome, size: 13, color: cores.primary),
        const SizedBox(width: Espaco.curto),
        Text(
          'Lumbra',
          style: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w600,
            color: cores.onSurface,
          ),
        ),
        if (bolha.modelo != null) ...[
          Text('  ·  ', style: discreto),
          Flexible(
            child: Text(
              bolha.modelo!,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              style: discreto,
            ),
          ),
        ],
        if (bolha.quando != null) ...[
          Text('  ·  ', style: discreto),
          Text(horaDe(bolha.quando!), style: discreto),
        ],
      ],
    );
  }
}

/// As fontes que a resposta REALMENTE citou, no pé do cartão.
///
/// Ficam presas à resposta, e não soltas na tela, porque proveniência sem
/// dono não vale nada: a pergunta que elas respondem é "de onde veio ISTO".
class _Fontes extends StatelessWidget {
  const _Fontes(this.fontes);

  final List<CitationOut> fontes;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Container(
      width: double.infinity,
      decoration: BoxDecoration(
        border: Border(top: BorderSide(color: cores.outlineVariant)),
      ),
      padding: const EdgeInsets.fromLTRB(
        Espaco.amplo,
        Espaco.medio,
        Espaco.amplo,
        Espaco.medio,
      ),
      child: Wrap(
        spacing: Espaco.curto,
        runSpacing: Espaco.curto,
        crossAxisAlignment: WrapCrossAlignment.center,
        children: [
          Padding(
            padding: const EdgeInsets.only(right: Espaco.minimo),
            child: Text(
              fontes.length == 1 ? '1 fonte' : '${fontes.length} fontes',
              style: TextStyle(fontSize: 11, color: cores.onSurfaceVariant),
            ),
          ),
          for (final f in fontes) _Fonte(f),
        ],
      ),
    );
  }
}

class _Fonte extends StatelessWidget {
  const _Fonte(this.fonte);

  final CitationOut fonte;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Material(
      color: cores.surfaceContainerHigh,
      borderRadius: Raio.bordaSelo,
      child: InkWell(
        borderRadius: Raio.bordaSelo,
        onTap: () => mostrarFonte(context, fonte),
        child: Padding(
          padding: const EdgeInsets.symmetric(
            horizontal: Espaco.curto,
            vertical: Espaco.minimo,
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                iconeDoTipo(fonte.kind),
                size: 12,
                color: cores.onSurfaceVariant,
              ),
              const SizedBox(width: Espaco.minimo + 2),
              Text(
                '[${fonte.ordinal}] ${_rotulo(fonte)}',
                style: TextStyle(fontSize: 11.5, color: cores.onSurface),
              ),
            ],
          ),
        ),
      ),
    );
  }

  static String _rotulo(CitationOut c) {
    final titulo = c.title?.trim();
    if (titulo == null || titulo.isEmpty) return nomeDoTipo(c.kind);
    return titulo.length > 28 ? '${titulo.substring(0, 27)}…' : titulo;
  }
}

/// Nome legível do tipo de fonte. Os valores de `kind` vêm do Core.
String nomeDoTipo(String kind) => switch (kind) {
  'document' => 'Documento',
  'memory' => 'Memória',
  'playbook' => 'Procedimento',
  _ => kind,
};

IconData iconeDoTipo(String kind) => switch (kind) {
  'document' => Icons.description_outlined,
  'memory' => Icons.psychology_outlined,
  'playbook' => Icons.menu_book_outlined,
  _ => Icons.link,
};

/// Abre uma fonte: tipo, relevância, trecho e origem.
///
/// Público porque o chip da resposta e o cartão do painel de contexto abrem
/// a MESMA coisa. Duas telas diferentes para a mesma fonte seriam duas
/// versões da verdade para manter em dia.
void mostrarFonte(BuildContext context, CitationOut fonte) {
  final cores = Theme.of(context).colorScheme;
  showDialog<void>(
    context: context,
    builder: (_) => AlertDialog(
      title: Text(fonte.title ?? 'Fonte [${fonte.ordinal}]'),
      content: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: Coluna.minimaDaConversa),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                // o score do RAG é o quanto esta fonte se parecia com a
                // pergunta. Mostrá-lo é o que separa "a Lumbra disse" de
                // "a Lumbra disse, e dá para conferir"
                fonte.score == null
                    ? nomeDoTipo(fonte.kind)
                    : '${nomeDoTipo(fonte.kind)} · relevância '
                          '${fonte.score!.toStringAsFixed(2)}',
                style: TextStyle(fontSize: 12, color: cores.onSurfaceVariant),
              ),
              if (fonte.snippet != null) ...[
                const SizedBox(height: Espaco.medio),
                SelectableText(fonte.snippet!),
              ],
              if (fonte.uri != null) ...[
                const SizedBox(height: Espaco.medio),
                SelectableText(
                  fonte.uri!,
                  style: TextStyle(
                    fontSize: 11.5,
                    color: cores.onSurfaceVariant,
                  ),
                ),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Fechar'),
        ),
      ],
    ),
  );
}

class _DeErro extends StatelessWidget {
  const _DeErro(this.bolha);

  final ChatBubble bolha;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: Espaco.medio),
      child: Align(
        alignment: Alignment.centerLeft,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: Coluna.leitura),
          child: Container(
            padding: const EdgeInsets.all(Espaco.largo),
            decoration: BoxDecoration(
              color: cores.errorContainer,
              borderRadius: Raio.bordaCartao,
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  Icons.error_outline,
                  size: 16,
                  color: cores.onErrorContainer,
                ),
                const SizedBox(width: Espaco.medio),
                Expanded(
                  child: SelectableText(
                    bolha.text,
                    style: TextStyle(
                      fontSize: 13,
                      color: cores.onErrorContainer,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// `09:41`. Sem data: dentro de uma conversa o dia raramente muda, e quando
/// muda quem conta é o histórico, não o carimbo de cada linha.
String horaDe(DateTime quando) =>
    '${quando.hour.toString().padLeft(2, '0')}:'
    '${quando.minute.toString().padLeft(2, '0')}';
