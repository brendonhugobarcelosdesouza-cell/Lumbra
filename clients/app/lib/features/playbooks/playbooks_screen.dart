import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

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
    final playbooks = ref.watch(playbooksProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Procedimentos')),
      body: playbooks.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (erro, _) => Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text(
              'Não foi possível carregar os procedimentos.\n$erro',
              textAlign: TextAlign.center,
            ),
          ),
        ),
        data: (lista) => lista.isEmpty
            ? const Center(
                child: Padding(
                  padding: EdgeInsets.all(24),
                  child: Text(
                    'Nenhum procedimento ainda.\n'
                    'A Lumbra propõe um quando resolve algo em vários passos.',
                    textAlign: TextAlign.center,
                  ),
                ),
              )
            : ListView(
                padding: const EdgeInsets.all(12),
                children: [for (final p in lista) _Procedimento(playbook: p)],
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
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: ExpansionTile(
        title: Text(playbook.title),
        subtitle: Text(playbook.whenToUse),
        children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Wrap(
                  spacing: 8,
                  children: [
                    Chip(
                      label: Text(_origem(playbook.origin)),
                      visualDensity: VisualDensity.compact,
                    ),
                    Chip(
                      label: Text('usado ${playbook.uses}x'),
                      visualDensity: VisualDensity.compact,
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                for (var i = 0; i < playbook.steps.length; i++)
                  Padding(
                    padding: const EdgeInsets.only(top: 2),
                    child: Text('${i + 1}. ${playbook.steps[i]}'),
                  ),
                // as armadilhas são onde mora o valor: o erro que já custou caro
                if (playbook.pitfalls.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Text('Atenção:', style: Theme.of(context).textTheme.labelLarge),
                  for (final armadilha in playbook.pitfalls)
                    Padding(
                      padding: const EdgeInsets.only(top: 2),
                      child: Text('• $armadilha'),
                    ),
                ],
                if (playbook.verification.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Text('Como verificar: ${playbook.verification}'),
                ],
                Align(
                  alignment: Alignment.centerRight,
                  child: TextButton.icon(
                    onPressed: () => _esquecer(context, ref),
                    icon: const Icon(Icons.delete_outline),
                    label: const Text('Esquecer'),
                  ),
                ),
              ],
            ),
          ),
        ],
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
