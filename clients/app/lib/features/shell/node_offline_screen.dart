import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/node_process.dart';
import '../../core/node_status.dart';

/// A tela de quando o Nó não responde.
///
/// Substitui o pior comportamento que o app tinha: cada seção falhando com
/// uma mensagem diferente, nenhuma delas dizendo a verdade. Aqui a causa é
/// dita uma vez, com o comando exato para resolver — e o app volta sozinho
/// quando o Nó subir, sem pedir que ninguém recarregue nada.
///
/// Enquanto o app não sobe o Nó por conta própria (ADR-046), esta tela é a
/// ponte honesta: ela ensina o que o instalador vai automatizar.
class NodeOfflineScreen extends ConsumerWidget {
  const NodeOfflineScreen({super.key});

  static const _comando =
      'cd C:\\dev\\lumbra\\core; & C:\\dev\\lumbra\\.venv\\Scripts\\Activate.ps1; lumbra dev';

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cores = Theme.of(context).colorScheme;
    final textos = Theme.of(context).textTheme;
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.cloud_off_outlined, size: 40, color: cores.primary),
                const SizedBox(height: 20),
                Text('O Nó não está no ar', style: textos.titleLarge),
                const SizedBox(height: 8),
                Text(
                  'A Lumbra guarda tudo no seu computador, e quem responde é o '
                  'Nó. Sem ele, nenhuma tela tem o que mostrar.',
                  style: textos.bodyMedium,
                ),
                // O app TENTOU subir o Nó e sabe por que não conseguiu. Não
                // mostrar isso foi a falha desta tela no primeiro teste do
                // conjunto: ela ofereceu o comando de desenvolvimento como se
                // nada tivesse sido tentado, escondendo a única informação que
                // levava à causa. Guardar o motivo do erro para si é o mesmo
                // pecado do "ApiException 401" — só que ao contrário.
                const _PorQueFalhou(),
                const SizedBox(height: 20),
                Text('Para subir à mão:', style: textos.labelLarge),
                const SizedBox(height: 8),
                const _Comando(comando: _comando),
                const SizedBox(height: 20),
                Row(
                  children: [
                    FilledButton.icon(
                      onPressed: () =>
                          ref.read(nodeStateProvider.notifier).verificarAgora(),
                      icon: const Icon(Icons.refresh),
                      label: const Text('Tentar de novo'),
                    ),
                    const SizedBox(width: 12),
                    // sem prometer o que não controlamos: dizemos que ele
                    // volta sozinho porque o vigia continua perguntando
                    Expanded(
                      child: Text(
                        'Assim que subir, o app entra sozinho.',
                        style: textos.bodySmall,
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                Text('Procurando em $noBaseUrl', style: textos.bodySmall),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// O que aconteceu quando tentamos subir o Nó — se é que tentamos.
class _PorQueFalhou extends ConsumerWidget {
  const _PorQueFalhou();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final erro = ref.watch(gerenteDoNoProvider).ultimoErro;
    if (erro.isEmpty) return const SizedBox.shrink();
    final cores = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.only(top: 16),
      child: Container(
        width: double.infinity,
        decoration: BoxDecoration(
          color: cores.errorContainer,
          borderRadius: BorderRadius.circular(10),
        ),
        padding: const EdgeInsets.all(14),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Tentei subir o Nó e não consegui:',
              style: Theme.of(context).textTheme.labelLarge?.copyWith(
                color: cores.onErrorContainer,
              ),
            ),
            const SizedBox(height: 6),
            SelectableText(
              erro,
              style: TextStyle(fontSize: 12.5, color: cores.onErrorContainer),
            ),
          ],
        ),
      ),
    );
  }
}

/// O comando em caixa própria, com botão de copiar — digitar caminho longo
/// à mão é onde o erro acontece.
class _Comando extends StatelessWidget {
  const _Comando({required this.comando});

  final String comando;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Container(
      decoration: BoxDecoration(
        border: Border.all(color: cores.outline),
        borderRadius: BorderRadius.circular(10),
      ),
      padding: const EdgeInsets.fromLTRB(14, 10, 6, 10),
      child: Row(
        children: [
          Expanded(
            child: SelectableText(
              comando,
              style: const TextStyle(fontFamily: 'monospace', fontSize: 12.5),
            ),
          ),
          IconButton(
            tooltip: 'Copiar',
            icon: const Icon(Icons.copy_all_outlined, size: 18),
            onPressed: () async {
              await Clipboard.setData(ClipboardData(text: comando));
              if (!context.mounted) return;
              ScaffoldMessenger.of(
                context,
              ).showSnackBar(const SnackBar(content: Text('Comando copiado.')));
            },
          ),
        ],
      ),
    );
  }
}
