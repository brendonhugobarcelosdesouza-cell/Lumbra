import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../core/api.dart';

/// Qual conversa está aberta no painel do meio.
///
/// Mora fora da tela de propósito: com o chat dentro da moldura, quem precisa
/// saber a conversa aberta são pelo menos três widgets irmãos — a coluna da
/// esquerda (para destacar), o painel do meio (para desenhar) e o painel de
/// contexto da direita (para explicar). Enquanto isso era um
/// `Navigator.push`, a resposta vivia na pilha de rotas e ninguém conseguia
/// perguntar.
class ConversaAberta {
  const ConversaAberta({
    required this.id,
    this.titulo,
    this.provedor,
    this.localApenas,
  });

  /// O que a lista já sabe sobre a conversa, inclusive a política de modelo.
  ///
  /// `model_policy` sempre veio no contrato (`{privacy, provider}`) e o app
  /// nunca leu. É o que permite dizer "Local" ou "Nuvem" no cabeçalho já na
  /// abertura, sem esperar o usuário trocar de modelo para descobrirmos.
  factory ConversaAberta.daLista(ConversationOut c) {
    final politica = c.modelPolicy;
    final privacidade = politica['privacy'];
    return ConversaAberta(
      id: c.id,
      titulo: c.title,
      provedor: politica['provider'] as String?,
      localApenas: privacidade is String ? privacidade == 'local_only' : null,
    );
  }

  final String id;

  /// O título conhecido pela LISTA. Serve para o cabeçalho aparecer já
  /// preenchido enquanto o histórico carrega; quem manda depois é o
  /// controlador da conversa.
  final String? titulo;

  final String? provedor;

  /// `true` quando a conversa está em `local_only`, `false` em `allow_cloud`,
  /// `null` quando não sabemos. Os três casos são diferentes: não saber não
  /// é o mesmo que ser nuvem, e afirmar "Local" por falta de informação seria
  /// a pior mentira que esta interface poderia contar.
  final bool? localApenas;
}

final conversaAbertaProvider = StateProvider<ConversaAberta?>((_) => null);

/// ChatApi sobre o cliente autenticado (exige Bearer + escopos).
final chatApiProvider = Provider<ChatApi>(
  (ref) => ChatApi(ref.watch(apiClientProvider)),
);

/// Conversas do usuário. Tipado pelo contrato (ConversationOut), não mapa.
final conversationsProvider = FutureProvider.autoDispose<List<ConversationOut>>(
  (ref) async {
    final api = ref.watch(chatApiProvider);
    final res = await api.listConversationsApiV1ChatConversationsGet();
    return res?.conversations ?? const [];
  },
);

/// Um provedor de chat disponível (local ou nuvem). O /providers ainda é
/// mapa livre no contrato — parseado aqui.
class ProviderChoice {
  const ProviderChoice({
    required this.name,
    required this.model,
    required this.isLocal,
  });

  final String name;
  final String model;
  final bool isLocal;
}

/// Cardápio de modelos que o Nó oferece (E2-04). Local não tem custo; nuvem
/// exige a conversa em modo allow_cloud (privacidade é opt-in explícito).
final providersProvider = FutureProvider.autoDispose<List<ProviderChoice>>((
  ref,
) async {
  final api = ref.watch(chatApiProvider);
  final res = await api.providersApiV1ChatProvidersGet();
  return (res?.providers ?? const [])
      .map(
        (p) => ProviderChoice(name: p.name, model: p.model, isLocal: p.isLocal),
      )
      .toList();
});
