import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';

/// Primeira tela: o estado da conexão com o Nó. É o "hello world" real da
/// plataforma — exercita o cliente gerado ponta a ponta (app → contrato →
/// Nó). As telas de chat, memória e documentos vêm sobre esta fundação.
class ConnectionScreen extends ConsumerWidget {
  const ConnectionScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final health = ref.watch(nodeHealthProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Lumbra')),
      body: Center(
        child: health.when(
          loading: () => const CircularProgressIndicator(),
          error: (error, _) => _Estado(
            icon: Icons.cloud_off,
            titulo: 'Nó indisponível',
            detalhe: noBaseUrl,
            acao: FilledButton(
              onPressed: () => ref.invalidate(nodeHealthProvider),
              child: const Text('Tentar de novo'),
            ),
          ),
          data: (dados) => _Estado(
            icon: Icons.cloud_done,
            titulo: 'Conectado ao Nó',
            detalhe: 'versão ${dados['version'] ?? '?'}',
          ),
        ),
      ),
    );
  }
}

class _Estado extends StatelessWidget {
  const _Estado({
    required this.icon,
    required this.titulo,
    required this.detalhe,
    this.acao,
  });

  final IconData icon;
  final String titulo;
  final String detalhe;
  final Widget? acao;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 56),
        const SizedBox(height: 16),
        Text(titulo, style: tema.textTheme.titleMedium),
        const SizedBox(height: 4),
        Text(detalhe, style: tema.textTheme.bodySmall),
        if (acao != null) ...[const SizedBox(height: 16), acao!],
      ],
    );
  }
}
