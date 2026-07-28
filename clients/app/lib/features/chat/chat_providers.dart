import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../core/api.dart';

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
  final lista = (res?['providers'] as List?) ?? const [];
  return lista.map((e) {
    final m = e as Map;
    return ProviderChoice(
      name: m['name'] as String? ?? '?',
      model: m['model'] as String? ?? '',
      isLocal: m['is_local'] as bool? ?? true,
    );
  }).toList();
});
