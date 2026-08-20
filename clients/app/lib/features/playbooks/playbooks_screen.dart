import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../design/secao.dart';
import '../../design/tokens.dart';
import 'playbooks_providers.dart';

/// Os procedimentos que a Lumbra sabe — o quarto tipo de memória, visível.
///
/// Mostra a PROVENIÊNCIA de cada um (ditado por você ou aprendido pela
/// plataforma) e quantas vezes já foi útil. Sem essa distinção, conhecimento
/// inferido e conhecimento seu pareceriam a mesma coisa — e a diferença é
/// justamente o que decide quanto confiar.
class PlaybooksScreen extends ConsumerWidget {
  const PlaybooksScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return MolduraDeSecao(
      titulo: 'Procedimentos',
      child: ListaAssincrona<PlaybookOut>(
        valor: ref.watch(playbooksProvider),
        oQueSeria: 'os procedimentos',
        iconeDoVazio: Icons.menu_book_outlined,
        quandoVazio:
            'Nenhum procedimento ainda. A Lumbra propõe um quando resolve '
            'algo em vários passos — e só guarda depois que você aprova.',
        aoTerConteudo: (lista) => ColunaDeLeitura(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(
              Espaco.grande,
              Espaco.largo,
              Espaco.grande,
              Espaco.enorme,
            ),
            children: [for (final p in lista) _Procedimento(playbook: p)],
          ),
        ),
      ),
    );
  }
}

class _Procedimento extends ConsumerWidget {
  const _Procedimento({required this.playbook});

  final PlaybookOut playbook;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cores = Theme.of(context).colorScheme;
    final textos = Theme.of(context).textTheme;

    return Padding(
      padding: const EdgeInsets.only(bottom: Espaco.medio),
      child: Material(
        color: cores.surfaceContainerLow,
        clipBehavior: Clip.antiAlias,
        shape: RoundedRectangleBorder(
          borderRadius: Raio.bordaCartao,
          side: BorderSide(color: cores.outlineVariant),
        ),
        child: ExpansionTile(
          // sem as bordas próprias do ExpansionTile: com o contorno do
          // cartão, elas viravam linha dupla
          shape: const Border(),
          collapsedShape: const Border(),
          tilePadding: const EdgeInsets.symmetric(
            horizontal: Espaco.largo,
            vertical: Espaco.minimo,
          ),
          title: Text(
            playbook.title,
            style: textos.bodyMedium?.copyWith(
              fontSize: 14,
              fontWeight: FontWeight.w600,
            ),
          ),
          subtitle: Padding(
            padding: const EdgeInsets.only(top: Espaco.micro),
            child: Text(
              playbook.whenToUse,
              style: TextStyle(fontSize: 12, color: cores.onSurfaceVariant),
            ),
          ),
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                Espaco.largo,
                Espaco.nada,
                Espaco.largo,
                Espaco.medio,
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    children: [
                      _Selo(_origem(playbook.origin)),
                      const SizedBox(width: Espaco.curto),
                      _Selo(
                        playbook.uses == 0
                            ? 'nunca usado'
                            : 'usado ${playbook.uses}x',
                      ),
                    ],
                  ),
                  const SizedBox(height: Espaco.largo),
                  for (var i = 0; i < playbook.steps.length; i++)
                    _Passo(numero: i + 1, texto: playbook.steps[i]),
                  // as armadilhas são onde mora o valor: o erro que já
                  // custou caro uma vez
                  if (playbook.pitfalls.isNotEmpty) ...[
                    const SizedBox(height: Espaco.largo),
                    const _Rotulo('Atenção'),
                    for (final armadilha in playbook.pitfalls)
                      Padding(
                        padding: const EdgeInsets.only(top: Espaco.minimo),
                        child: Text(
                          '• $armadilha',
                          style: textos.bodyMedium?.copyWith(
                            fontSize: 13,
                            height: 1.5,
                          ),
                        ),
                      ),
                  ],
                  if (playbook.verification.isNotEmpty) ...[
                    const SizedBox(height: Espaco.largo),
                    const _Rotulo('Como verificar'),
                    Padding(
                      padding: const EdgeInsets.only(top: Espaco.minimo),
                      child: Text(
                        playbook.verification,
                        style: textos.bodyMedium?.copyWith(
                          fontSize: 13,
                          height: 1.5,
                        ),
                      ),
                    ),
                  ],
                  Align(
                    alignment: Alignment.centerRight,
                    child: TextButton.icon(
                      onPressed: () => _esquecer(context, ref),
                      icon: const Icon(Icons.delete_outline, size: 16),
                      label: const Text(
                        'Esquecer',
                        style: TextStyle(fontSize: 12.5),
                      ),
                      style: TextButton.styleFrom(
                        foregroundColor: cores.onSurfaceVariant,
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  static String _origem(String origin) => switch (origin) {
    'agent' => 'aprendido pela Lumbra',
    'imported' => 'importado',
    _ => 'ditado por você',
  };

  Future<void> _esquecer(BuildContext context, WidgetRef ref) async {
    try {
      await ref
          .read(playbooksApiProvider)
          .forgetApiV1PlaybooksPlaybookIdDelete(playbook.id);
      ref.invalidate(playbooksProvider);
      if (!context.mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('Procedimento esquecido.')));
    } on ApiException catch (e) {
      if (!context.mounted) return;
      // 409 = o gate pediu confirmação humana; o pedido está na outra tela,
      // então em vez de mostrar um erro cru, apontamos para onde decidir
      final aviso = e.code == 409
          ? 'Precisa da sua confirmação — veja em Aprovações.'
          : 'Não foi possível esquecer: ${e.message ?? e.code}';
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(aviso)));
    } catch (e) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('Não foi possível esquecer: $e')));
    }
  }
}

/// Etiqueta neutra: proveniência e uso. Não é botão e não deve parecer um —
/// o `Chip` do Material tem peso de controle e convidava ao clique.
class _Selo extends StatelessWidget {
  const _Selo(this.texto);

  final String texto;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: Espaco.curto,
        vertical: Espaco.micro,
      ),
      decoration: BoxDecoration(
        color: cores.surfaceContainerHigh,
        borderRadius: Raio.bordaSelo,
      ),
      child: Text(
        texto,
        style: TextStyle(fontSize: 11, color: cores.onSurfaceVariant),
      ),
    );
  }
}

class _Rotulo extends StatelessWidget {
  const _Rotulo(this.texto);

  final String texto;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Text(
      texto.toUpperCase(),
      style: TextStyle(
        fontSize: 10,
        fontWeight: FontWeight.w700,
        letterSpacing: 0.8,
        color: cores.onSurfaceVariant,
      ),
    );
  }
}

/// Um passo do procedimento, com o número FORA do texto.
///
/// Numerar dentro da string ("1. faça isso") quebra o alinhamento quando o
/// passo ocupa duas linhas: a segunda volta para a margem e a lista deixa de
/// se ler como lista.
class _Passo extends StatelessWidget {
  const _Passo({required this.numero, required this.texto});

  final int numero;
  final String texto;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(bottom: Espaco.curto),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: Espaco.amplo,
            child: Text(
              '$numero.',
              style: TextStyle(fontSize: 13, color: cores.onSurfaceVariant),
            ),
          ),
          Expanded(
            child: Text(
              texto,
              style: Theme.of(
                context,
              ).textTheme.bodyMedium?.copyWith(fontSize: 13, height: 1.5),
            ),
          ),
        ],
      ),
    );
  }
}
