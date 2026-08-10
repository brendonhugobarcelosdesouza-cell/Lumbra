import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../core/api.dart';

/// API de memória (o que a Lumbra sabe sobre você) — gerada do contrato.
final memoryApiProvider = Provider<MemoryApi>(
  (ref) => MemoryApi(ref.watch(apiClientProvider)),
);

/// Camada em exibição. `null` = todas.
///
/// A memória da Lumbra tem quatro camadas com meias-vidas diferentes
/// (temporária, episódica, semântica, procedural). Filtrar por camada não é
/// enfeite: é como se acha o fato errado entre centenas de certos.
final camadaSelecionadaProvider = StateProvider<String?>((ref) => null);

/// As memórias do usuário, na camada escolhida.
///
/// Sem `query`: a rota LISTA em vez de buscar — é a visão auditável, que
/// mostra tudo, inclusive o que a plataforma guardou sozinha.
final memoriesProvider = FutureProvider.autoDispose<List<MemoryItemOut>>((
  ref,
) async {
  final api = ref.watch(memoryApiProvider);
  final camada = ref.watch(camadaSelecionadaProvider);
  final res = await api.listMemoriesApiV1MemoryGet(kind: camada, limit: 200);
  return res?.items ?? const [];
});
