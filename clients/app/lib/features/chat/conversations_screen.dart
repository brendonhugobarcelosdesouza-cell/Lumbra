import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

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
      // sem ícones de navegação aqui: as seções viraram lugares na barra
      // lateral (HomeShell), não atalhos escondidos no topo
      appBar: AppBar(title: const Text('Conversas')),
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
            : _ListaAgrupada(conversas: lista, aoAbrir: _abrir),
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

/// A lista com cabeçalhos de data e largura de leitura.
///
/// A largura importa: numa tela de 1500px, texto correndo de ponta a ponta
/// obriga o olho a varrer a linha inteira. Uma coluna de ~720px é o que se
/// lê sem cansar — o resto da tela é respiro, não desperdício.
class _ListaAgrupada extends StatelessWidget {
  const _ListaAgrupada({required this.conversas, required this.aoAbrir});

  final List<ConversationOut> conversas;
  final void Function(BuildContext, String, String?) aoAbrir;

  @override
  Widget build(BuildContext context) {
    final grupos = agruparPorData(conversas);
    final estiloGrupo = Theme.of(context).textTheme.labelMedium?.copyWith(
      color: Theme.of(context).colorScheme.primary,
      fontWeight: FontWeight.w700,
      letterSpacing: 0.6,
    );
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 720),
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
          children: [
            for (final rotulo in ordemDosGrupos)
              if (grupos[rotulo] != null) ...[
                Padding(
                  padding: const EdgeInsets.fromLTRB(12, 20, 12, 6),
                  child: Text(rotulo.toUpperCase(), style: estiloGrupo),
                ),
                for (final c in grupos[rotulo]!)
                  ListTile(
                    leading: const Icon(Icons.chat_bubble_outline, size: 20),
                    title: Text(c.title ?? 'Conversa'),
                    onTap: () => aoAbrir(context, c.id, c.title),
                  ),
              ],
          ],
        ),
      ),
    );
  }
}

/// Agrupa as conversas por quando aconteceram.
///
/// Uma lista corrida de "Conversa, Conversa, Conversa" não diz nada: o que
/// localiza a pessoa é o TEMPO ("aquilo foi ontem"), não a posição. Os grupos
/// são os que a memória usa — hoje, ontem, a semana, o resto.
Map<String, List<ConversationOut>> agruparPorData(
  List<ConversationOut> conversas, {
  DateTime? agora,
}) {
  final hoje = DateTime(
    (agora ?? DateTime.now()).year,
    (agora ?? DateTime.now()).month,
    (agora ?? DateTime.now()).day,
  );
  final grupos = <String, List<ConversationOut>>{};
  for (final c in conversas) {
    final quando = DateTime.tryParse(c.lastMessageAt ?? c.createdAt)?.toLocal();
    final rotulo = quando == null
        ? 'Sem data'
        : _rotuloDe(DateTime(quando.year, quando.month, quando.day), hoje);
    grupos.putIfAbsent(rotulo, () => []).add(c);
  }
  return grupos;
}

String _rotuloDe(DateTime dia, DateTime hoje) {
  final dias = hoje.difference(dia).inDays;
  if (dias <= 0) return 'Hoje';
  if (dias == 1) return 'Ontem';
  if (dias < 7) return 'Últimos 7 dias';
  if (dias < 30) return 'Últimos 30 dias';
  return 'Mais antigas';
}

/// A ordem em que os grupos aparecem — do mais recente ao mais antigo.
const ordemDosGrupos = [
  'Hoje',
  'Ontem',
  'Últimos 7 dias',
  'Últimos 30 dias',
  'Mais antigas',
  'Sem data',
];
