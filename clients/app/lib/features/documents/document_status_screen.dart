import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../design/secao.dart';
import '../../design/tokens.dart';
import 'documents_providers.dart';
import 'documents_screen.dart' show estadosDoPipeline;

/// Por que este arquivo está — ou não está — pesquisável.
///
/// A lista de documentos diz O QUE aconteceu ("falhou"); esta tela diz ONDE.
/// É a ferramenta de quando a Lumbra "não sabe" de algo que deveria saber:
/// sem ela, a resposta a "por que não achou minha fatura?" seria adivinhação,
/// que foi exatamente como perdemos tempo com a issue #10.
class DocumentStatusScreen extends ConsumerWidget {
  const DocumentStatusScreen({
    required this.documentId,
    required this.titulo,
    super.key,
  });

  final String documentId;
  final String titulo;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(documentStatusProvider(documentId));
    // a última tela que ainda desenhava os próprios estados: roda de
    // progresso crua no carregando, `$erro` despejado na tela no erro. Os
    // três estados agora são os mesmos de todas as seções — carregar,
    // falhar e não ter nada acontecem em toda tela, e aprender três
    // desenhos diferentes para a mesma coisa é custo sem contrapartida.
    return Scaffold(
      appBar: AppBar(title: Text(titulo)),
      body: ColunaDeLeitura(
        child: status.when(
          loading: () => const Carregando(),
          error: (erro, _) => Falhou(
            oQueSeria: 'o estado deste documento',
            detalhe: '$erro',
            aoTentarDeNovo: () =>
                ref.invalidate(documentStatusProvider(documentId)),
          ),
          data: (dados) => dados == null
              ? const Vazio(
                  texto: 'A Lumbra não tem registro do que fez com este '
                      'arquivo. Reindexar cria a trilha.',
                  icone: Icons.hourglass_empty,
                )
              : _Corpo(status: dados),
        ),
      ),
    );
  }
}

class _Corpo extends StatelessWidget {
  const _Corpo({required this.status});

  final DocumentStatusOut status;

  @override
  Widget build(BuildContext context) {
    final textos = Theme.of(context).textTheme;
    return ListView(
      padding: const EdgeInsets.fromLTRB(
        Espaco.grande,
        Espaco.largo,
        Espaco.grande,
        Espaco.enorme,
      ),
      children: [
        Text(
          '${estadosDoPipeline[status.state] ?? status.state}'
          ' · versão ${status.version}',
          style: textos.titleMedium,
        ),
        const SizedBox(height: Espaco.amplo),
        if (status.timeline.isNotEmpty) ...[
          Text('O que a Lumbra fez com ele', style: textos.labelLarge),
          const SizedBox(height: Espaco.curto),
          for (final etapa in status.timeline) _Etapa(etapa: etapa),
          const SizedBox(height: Espaco.grande),
        ],
        if (status.versions.isNotEmpty) ...[
          Text('Histórico', style: textos.labelLarge),
          const SizedBox(height: Espaco.curto),
          for (final v in status.versions) _Versao(versao: v),
        ],
      ],
    );
  }
}

class _Etapa extends StatelessWidget {
  const _Etapa({required this.etapa});

  final TimelineEntryOut etapa;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final textos = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: Espaco.curto),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            etapa.success ? Icons.check_circle_outline : Icons.error_outline,
            size: 18,
            color: etapa.success ? cores.primary : cores.error,
          ),
          const SizedBox(width: Espaco.curto),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(etapa.stage, style: textos.bodyMedium),
                // a mensagem só aparece quando existe: etapa que deu certo
                // em silêncio não precisa de linha extra
                if (etapa.message.isNotEmpty)
                  Text(etapa.message, style: textos.bodySmall),
              ],
            ),
          ),
          Text(_duracao(etapa.durationMs), style: textos.bodySmall),
        ],
      ),
    );
  }

  /// Milissegundo cru não diz nada a quem só quer saber se demorou.
  static String _duracao(num ms) =>
      ms >= 1000 ? '${(ms / 1000).toStringAsFixed(1)} s' : '${ms.round()} ms';
}

class _Versao extends StatelessWidget {
  const _Versao({required this.versao});

  final DocumentVersionOut versao;

  @override
  Widget build(BuildContext context) {
    final textos = Theme.of(context).textTheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: Espaco.curto),
      child: Text(
        'v${versao.version} · ${versao.reason}'
        // indexado nulo é informação, não ausência: significa que aquela
        // versão nunca chegou a ficar pesquisável
        '${versao.indexedAt == null ? ' · nunca indexada' : ''}',
        style: textos.bodySmall,
      ),
    );
  }
}
