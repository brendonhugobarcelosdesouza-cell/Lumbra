import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

/// URL do Nó Lumbra. No P2-e o app passará a subir e gerenciar o Nó como
/// sidecar (ADR-046); por ora, conecta a um Nó local já no ar. Configurável
/// em tempo de build com --dart-define=LUMBRA_NODE_URL=...
const noBaseUrl = String.fromEnvironment(
  'LUMBRA_NODE_URL',
  defaultValue: 'http://localhost:8000',
);

/// Cliente da Platform API, apontando para o Nó. É a ÚNICA porta do app
/// para o Core (docs/24, Regra 1): nenhuma requisição HTTP à mão.
final apiClientProvider = Provider<ApiClient>(
  (ref) => ApiClient(basePath: noBaseUrl),
);

/// API de operações (health/ready/system) sobre o cliente configurado.
final opsApiProvider = Provider<OpsApi>(
  (ref) => OpsApi(ref.watch(apiClientProvider)),
);

/// Liveness do Nó: `/health` devolve `{status, version}`. Falha de rede
/// vira o estado de erro do `AsyncValue` — é assim que a UI sabe que o Nó
/// está fora do ar.
final nodeHealthProvider = FutureProvider.autoDispose<Map<String, String>>((
  ref,
) async {
  final ops = ref.watch(opsApiProvider);
  final health = await ops.healthHealthGet();
  return health ?? const <String, String>{};
});
