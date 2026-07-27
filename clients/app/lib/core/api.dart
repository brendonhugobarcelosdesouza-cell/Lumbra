import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import 'session.dart';

/// URL do Nó Lumbra. No P2-e o app passará a subir e gerenciar o Nó como
/// sidecar (ADR-046); por ora, conecta a um Nó local já no ar. Configurável
/// em tempo de build com --dart-define=LUMBRA_NODE_URL=...
const noBaseUrl = String.fromEnvironment(
  'LUMBRA_NODE_URL',
  defaultValue: 'http://localhost:8000',
);

/// Cliente SEM autenticação, para as rotas públicas (login, registro,
/// health). Existe separado para quebrar o ciclo de providers: o AuthApi
/// não pode depender da sessão, que depende do AuthApi.
final _plainApiClientProvider = Provider<ApiClient>(
  (ref) => ApiClient(basePath: noBaseUrl),
);

/// AuthApi sobre o cliente plano — usado pelo SessionController.
final authApiProvider = Provider<AuthApi>(
  (ref) => AuthApi(ref.watch(_plainApiClientProvider)),
);

/// Cliente AUTENTICADO: injeta o Bearer da sessão. Reconstrói quando o
/// token muda (login/logout), então as APIs abaixo passam a carregar (ou
/// deixar de carregar) o Authorization automaticamente. É a única porta do
/// app para o Core (docs/24, Regra 1): nenhuma requisição HTTP à mão.
final apiClientProvider = Provider<ApiClient>((ref) {
  final token = ref.watch(sessionControllerProvider).valueOrNull?.accessToken;
  final auth = token == null ? null : (HttpBearerAuth()..accessToken = token);
  return ApiClient(basePath: noBaseUrl, authentication: auth);
});

/// API de operações (health/ready/system) sobre o cliente configurado.
final opsApiProvider = Provider<OpsApi>(
  (ref) => OpsApi(ref.watch(apiClientProvider)),
);

/// API de dispositivos (exige Bearer + escopo devices:read).
final devicesApiProvider = Provider<DevicesApi>(
  (ref) => DevicesApi(ref.watch(apiClientProvider)),
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

/// Dispositivos do usuário autenticado. Prova o fluxo Bearer + escopos
/// ponta a ponta (liga na identidade do P1-b).
final devicesListProvider = FutureProvider.autoDispose<List<DeviceResponse>>((
  ref,
) async {
  final devices = ref.watch(devicesApiProvider);
  return (await devices.listDevicesApiV1DevicesGet()) ?? const [];
});
