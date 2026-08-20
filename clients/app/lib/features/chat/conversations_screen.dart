import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../design/tokens.dart';
import 'chat_providers.dart';
import 'chat_screen.dart';
import 'coluna_de_conversas.dart';
import 'conversa_estado.dart';
import 'painel_de_contexto.dart';

/// A seção Conversas: a lista à esquerda e a conversa aberta ao lado.
///
/// Duas colunas quando cabem, uma de cada vez quando não cabem. Não é o
/// mesmo desenho comprimido: no estreito, escolher uma conversa SUBSTITUI a
/// lista e um botão de voltar traz ela de volta — que é o gesto natural com o
/// polegar. No largo as duas convivem, porque trocar de conversa é a ação
/// mais frequente de quem usa isto o dia inteiro, e ela não pode custar dois
/// cliques.
class ConversationsScreen extends ConsumerWidget {
  const ConversationsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cores = Theme.of(context).colorScheme;
    final aberta = ref.watch(conversaAbertaProvider);

    return LayoutBuilder(
      builder: (context, espaco) {
        final cabemAsDuas = espaco.maxWidth >= Coluna.cabeAColecao;

        if (!cabemAsDuas) {
          if (aberta == null) return const ColunaDeConversas();
          return _Painel(
            aberta: aberta,
            aoVoltar: () =>
                ref.read(conversaAbertaProvider.notifier).state = null,
          );
        }

        final cabeOContexto = espaco.maxWidth >= Coluna.cabeOContexto;
        final querContexto = ref.watch(painelDeContextoProvider);

        return Row(
          children: [
            const SizedBox(
              width: Coluna.colecao,
              child: ColunaDeConversas(),
            ),
            VerticalDivider(width: 1, color: cores.outlineVariant),
            Expanded(child: _Painel(aberta: aberta)),
            if (aberta != null && cabeOContexto && querContexto) ...[
              VerticalDivider(width: 1, color: cores.outlineVariant),
              SizedBox(
                width: Coluna.contexto,
                child: _Contexto(conversa: aberta.id),
              ),
            ],
          ],
        );
      },
    );
  }
}

class _Painel extends StatelessWidget {
  const _Painel({required this.aberta, this.aoVoltar});

  final ConversaAberta? aberta;
  final VoidCallback? aoVoltar;

  @override
  Widget build(BuildContext context) {
    final conversa = aberta;
    if (conversa == null) return const _NenhumaAberta();
    return ChatScreen(
      // a chave amarra o widget à conversa: sem ela, trocar de conversa
      // reaproveitaria o State anterior e o campo de texto viria com o
      // rascunho da outra
      key: ValueKey(conversa.id),
      conversationId: conversa.id,
      aberta: conversa,
      aoVoltar: aoVoltar,
    );
  }
}

/// O painel de contexto ligado à conversa aberta.
///
/// Fica aqui, e não dentro do [ChatScreen], porque ele é IRMÃO da conversa e
/// não parte dela: ocupa a altura inteira, inclusive ao lado do cabeçalho.
/// Foi para isto que o estado da conversa saiu do widget no R1 — sem aquilo,
/// este painel não teria como saber o que a conversa sabe.
class _Contexto extends ConsumerWidget {
  const _Contexto({required this.conversa});

  final String conversa;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return PainelDeContexto(
      estado: ref.watch(conversaProvider(conversa)),
      aoFechar: () =>
          ref.read(painelDeContextoProvider.notifier).state = false,
    );
  }
}

class _NenhumaAberta extends StatelessWidget {
  const _NenhumaAberta();

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(Espaco.enorme),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(
              Icons.forum_outlined,
              size: 34,
              color: cores.onSurfaceVariant,
            ),
            const SizedBox(height: Espaco.largo),
            Text(
              'Escolha uma conversa ou comece outra.',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
          ],
        ),
      ),
    );
  }
}
