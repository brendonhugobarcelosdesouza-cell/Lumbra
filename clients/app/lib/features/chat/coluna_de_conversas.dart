import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../design/tokens.dart';
import 'chat_providers.dart';

/// A lista de conversas como COLUNA, e não como tela.
///
/// Antes ela era a tela inicial e abrir uma conversa empilhava outra por
/// cima. Isso custa duas coisas numa ferramenta de uso contínuo: some a noção
/// de onde se está, e trocar de conversa exige desfazer a pilha primeiro.
/// Como coluna, as conversas ficam sempre à vista e trocar entre elas é um
/// clique — que é como um sistema operacional se comporta e um aplicativo de
/// celular esticado, não.
class ColunaDeConversas extends ConsumerWidget {
  const ColunaDeConversas({super.key, this.aoAbrir});

  /// Chamado depois de selecionar. Existe para a versão estreita poder
  /// esconder a coluna ao abrir — no desktop as duas convivem.
  final VoidCallback? aoAbrir;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cores = Theme.of(context).colorScheme;
    final conversas = ref.watch(conversationsProvider);
    final aberta = ref.watch(conversaAbertaProvider);

    return Container(
      color: cores.surfaceContainerLow,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          _Cabecalho(aoAbrir: aoAbrir),
          Expanded(
            child: conversas.when(
              loading: () => const Center(
                child: SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              ),
              error: (erro, _) => Padding(
                padding: const EdgeInsets.all(Espaco.largo),
                child: Text(
                  'Não foi possível carregar as conversas.\n$erro',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
              data: (lista) => lista.isEmpty
                  ? const _Vazia()
                  : _Lista(
                      conversas: lista,
                      abertaId: aberta?.id,
                      aoSelecionar: (c) {
                        ref.read(conversaAbertaProvider.notifier).state =
                            ConversaAberta.daLista(c);
                        aoAbrir?.call();
                      },
                    ),
            ),
          ),
        ],
      ),
    );
  }
}

class _Vazia extends StatelessWidget {
  const _Vazia();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(Espaco.grande),
        child: Text(
          'Nenhuma conversa ainda.',
          textAlign: TextAlign.center,
          style: Theme.of(context).textTheme.bodySmall,
        ),
      ),
    );
  }
}

class _Cabecalho extends ConsumerWidget {
  const _Cabecalho({this.aoAbrir});

  final VoidCallback? aoAbrir;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        Espaco.largo,
        Espaco.largo,
        Espaco.medio,
        Espaco.curto,
      ),
      child: Row(
        children: [
          Expanded(
            child: Text(
              'Conversas',
              style: Theme.of(context).textTheme.titleMedium,
            ),
          ),
          IconButton.filled(
            tooltip: 'Nova conversa',
            iconSize: 18,
            constraints: const BoxConstraints.tightFor(width: 32, height: 32),
            padding: EdgeInsets.zero,
            onPressed: () => _nova(context, ref),
            icon: const Icon(Icons.add),
          ),
        ],
      ),
    );
  }

  Future<void> _nova(BuildContext context, WidgetRef ref) async {
    try {
      final api = ref.read(chatApiProvider);
      final iniciada = await api.startApiV1ChatConversationsPost(StartBody());
      if (iniciada == null) return;
      ref.read(conversaAbertaProvider.notifier).state = ConversaAberta(
        id: iniciada.conversationId,
      );
      ref.invalidate(conversationsProvider);
      aoAbrir?.call();
    } catch (e) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('Não foi possível iniciar: $e')));
    }
  }
}

class _Lista extends StatelessWidget {
  const _Lista({
    required this.conversas,
    required this.abertaId,
    required this.aoSelecionar,
  });

  final List<ConversationOut> conversas;
  final String? abertaId;
  final ValueChanged<ConversationOut> aoSelecionar;

  @override
  Widget build(BuildContext context) {
    final grupos = agruparPorData(conversas);
    return ListView(
      padding: const EdgeInsets.only(bottom: Espaco.largo),
      children: [
        for (final rotulo in ordemDosGrupos)
          if (grupos[rotulo] != null) ...[
            _TituloDoGrupo(rotulo),
            for (final c in grupos[rotulo]!)
              _ItemDeConversa(
                conversa: c,
                aberta: c.id == abertaId,
                aoTocar: () => aoSelecionar(c),
              ),
          ],
      ],
    );
  }
}

class _TituloDoGrupo extends StatelessWidget {
  const _TituloDoGrupo(this.texto);

  final String texto;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        Espaco.largo,
        Espaco.largo,
        Espaco.largo,
        Espaco.minimo,
      ),
      child: Text(
        texto,
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
          fontWeight: FontWeight.w700,
          letterSpacing: 0.4,
          fontSize: 10.5,
        ),
      ),
    );
  }
}

class _ItemDeConversa extends StatelessWidget {
  const _ItemDeConversa({
    required this.conversa,
    required this.aberta,
    required this.aoTocar,
  });

  final ConversationOut conversa;
  final bool aberta;
  final VoidCallback aoTocar;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final textos = Theme.of(context).textTheme;

    return Padding(
      padding: const EdgeInsets.symmetric(
        horizontal: Espaco.curto,
        vertical: 1,
      ),
      child: Material(
        color: aberta ? cores.surfaceContainerHigh : Colors.transparent,
        borderRadius: Raio.bordaItem,
        child: InkWell(
          onTap: aoTocar,
          borderRadius: Raio.bordaItem,
          child: Padding(
            padding: const EdgeInsets.symmetric(
              horizontal: Espaco.medio,
              vertical: Espaco.curto,
            ),
            child: Row(
              children: [
                Expanded(
                  child: Text(
                    // conversa sem título é conversa que ainda não teve
                    // pergunta: dizer isso é melhor que repetir "Conversa"
                    conversa.title ?? 'Nova conversa',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: textos.bodyMedium?.copyWith(
                      fontSize: 13,
                      color: aberta ? cores.onSurface : cores.onSurfaceVariant,
                      fontWeight: aberta ? FontWeight.w600 : FontWeight.w400,
                    ),
                  ),
                ),
                const SizedBox(width: Espaco.curto),
                Text(
                  horaCurtaDe(conversa),
                  style: TextStyle(fontSize: 11, color: cores.onSurfaceVariant),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// A hora, quando é de hoje; o dia, quando é mais antiga.
///
/// Dentro de um grupo que já diz "Hoje", repetir a data é ruído; o que
/// distingue as conversas ali é o horário. Nos grupos antigos vale o inverso.
String horaCurtaDe(ConversationOut c, {DateTime? agora}) {
  final quando = DateTime.tryParse(c.lastMessageAt ?? c.createdAt)?.toLocal();
  if (quando == null) return '';
  final hoje = agora ?? DateTime.now();
  final mesmoDia =
      quando.year == hoje.year &&
      quando.month == hoje.month &&
      quando.day == hoje.day;
  return mesmoDia
      ? '${_dois(quando.hour)}:${_dois(quando.minute)}'
      : '${_dois(quando.day)}/${_dois(quando.month)}';
}

String _dois(int n) => n.toString().padLeft(2, '0');

/// Agrupa as conversas por quando aconteceram.
///
/// Uma lista corrida de "Conversa, Conversa, Conversa" não diz nada: o que
/// localiza a pessoa é o TEMPO ("aquilo foi ontem"), não a posição. Os grupos
/// são os que a memória usa — hoje, ontem, a semana, o resto.
Map<String, List<ConversationOut>> agruparPorData(
  List<ConversationOut> conversas, {
  DateTime? agora,
}) {
  final referencia = agora ?? DateTime.now();
  final hoje = DateTime(referencia.year, referencia.month, referencia.day);
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
