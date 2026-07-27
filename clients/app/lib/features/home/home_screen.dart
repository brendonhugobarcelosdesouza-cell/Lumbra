import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api.dart';
import '../../core/session.dart';

/// Primeira tela autenticada: lista os dispositivos do usuário (exige Bearer
/// + escopo devices:read). Prova que a sessão flui ponta a ponta e liga na
/// identidade do P1-b. As telas de chat/memória/documentos vêm aqui.
class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final dispositivos = ref.watch(devicesListProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Lumbra'),
        actions: [
          IconButton(
            tooltip: 'Sair',
            icon: const Icon(Icons.logout),
            onPressed: () =>
                ref.read(sessionControllerProvider.notifier).logout(),
          ),
        ],
      ),
      body: dispositivos.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (erro, _) => Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text(
              'Não foi possível carregar seus dispositivos.\n$erro',
              textAlign: TextAlign.center,
            ),
          ),
        ),
        data: (lista) => lista.isEmpty
            ? const Center(child: Text('Nenhum dispositivo pareado ainda.'))
            : ListView(
                children: [
                  for (final d in lista)
                    ListTile(
                      leading: const Icon(Icons.devices),
                      title: Text(d.name),
                      subtitle: Text('${d.platform} · ${d.state}'),
                    ),
                ],
              ),
      ),
    );
  }
}
