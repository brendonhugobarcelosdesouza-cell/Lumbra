import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../core/session.dart';
import '../approvals/approvals_providers.dart';
import '../approvals/approvals_screen.dart';
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
          const _BotaoAprovacoes(),
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

/// Entrada para a caixa de aprovações, com contador do que aguarda decisão.
///
/// O contador existe porque um pedido que ninguém vê é igual a um pedido
/// negado: a plataforma pode aprender sozinha justamente porque há onde
/// perguntar, e o usuário precisa perceber que foi perguntado. Sem pendências
/// (o caso comum), some — não vira ruído.
class _BotaoAprovacoes extends ConsumerWidget {
  const _BotaoAprovacoes();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final pendentes = ref.watch(pendingApprovalsProvider);
    final quantos = pendentes.valueOrNull?.length ?? 0;
    // erro ou carga do Nó não pode esconder o acesso: o botão fica, sem selo
    final icone = quantos == 0
        ? const Icon(Icons.inbox_outlined)
        : Badge.count(count: quantos, child: const Icon(Icons.inbox));
    return IconButton(
      tooltip: 'Aprovações',
      icon: icone,
      onPressed: () => Navigator.of(context).push(
        MaterialPageRoute<void>(builder: (_) => const ApprovalsScreen()),
      ),
    );
  }
}
