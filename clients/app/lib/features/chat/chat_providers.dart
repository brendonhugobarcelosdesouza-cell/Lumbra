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
