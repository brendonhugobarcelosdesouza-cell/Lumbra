import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../core/session.dart';
import '../devices/devices_screen.dart';
import 'chat_providers.dart';
import 'chat_screen.dart';

/// Tela inicial autenticada: as conversas do usuário e um botão para começar
/// uma nova. Tocar numa conversa abre o chat. É o coração do app.
class ConversationsScreen extends ConsumerWidget {
  const ConversationsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final conversas = ref.watch(conversationsProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Lumbra'),
        actions: [
          IconButton(
            tooltip: 'Dispositivos',
            icon: const Icon(Icons.devices),
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute<void>(builder: (_) => const DevicesScreen()),
            ),
          ),
          IconButton(
            tooltip: 'Sair',
            icon: const Icon(Icons.logout),
            onPressed: () =>
                ref.read(sessionControllerProvider.notifier).logout(),
          ),
        ],
      ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _novaConversa(context, ref),
        icon: const Icon(Icons.add),
        label: const Text('Nova conversa'),
      ),
      body: conversas.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (erro, _) => Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text('Não foi possível carregar as conversas.\n$erro'),
          ),
        ),
        data: (lista) => lista.isEmpty
            ? const Center(child: Text('Nenhuma conversa ainda.'))
            : ListView(
                children: [
                  for (final c in lista)
                    ListTile(
                      leading: const Icon(Icons.chat_bubble_outline),
                      title: Text(c.title ?? 'Conversa'),
                      onTap: () => _abrir(context, c.id, c.title),
                    ),
                ],
              ),
      ),
    );
  }

  Future<void> _novaConversa(BuildContext context, WidgetRef ref) async {
    try {
      final api = ref.read(chatApiProvider);
      final iniciada = await api.startApiV1ChatConversationsPost(StartBody());
      if (iniciada == null || !context.mounted) return;
      _abrir(context, iniciada.conversationId, null);
      ref.invalidate(conversationsProvider);
    } catch (e) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('Não foi possível iniciar: $e')));
    }
  }

  void _abrir(BuildContext context, String id, String? titulo) {
    Navigator.of(context).push(
      MaterialPageRoute<void>(
        builder: (_) => ChatScreen(conversationId: id, title: titulo),
      ),
    );
  }
}
