import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../core/api.dart';

/// AgentsApi sobre o cliente autenticado.
final agentsApiProvider = Provider<AgentsApi>(
  (ref) => AgentsApi(ref.watch(apiClientProvider)),
);

/// Os agentes registrados neste Nó.
///
/// A rota existe desde o A7.5 e nunca teve tela: a barra lateral prometia
/// "Agentes — em breve" enquanto o dado já atravessava o fio. Isto aqui não
/// é funcionalidade nova, é uma promessa sendo cumprida com o que já havia.
final agentsProvider = FutureProvider.autoDispose<List<AgentOut>>((ref) async {
  final res = await ref.watch(agentsApiProvider).listAgentsApiV1AgentsGet();
  return res?.agents ?? const [];
});
