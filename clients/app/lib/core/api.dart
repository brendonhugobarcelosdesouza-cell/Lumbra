import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import 'http_renovavel.dart';
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

/// Cliente AUTENTICADO: injeta o Bearer da sessão e renova sozinho quando o
/// Nó responde 401 (ADR-068). É a única porta do app para o Core (docs/24,
/// Regra 1): nenhuma requisição HTTP à mão.
///
/// Observa apenas se EXISTE sessão, não qual é o token. A diferença é
/// visível: antes, cada renovação (a cada 10 minutos) trocava a identidade do
/// provider e fazia todas as telas recarregarem do zero — a lista de
/// conversas piscava sem que nada tivesse mudado. Agora só entrar e sair
/// reconstroem o cliente; o token é lido a cada requisição.
final apiClientProvider = Provider<ApiClient>((ref) {
  ref.watch(sessionControllerProvider.select((s) => s.valueOrNull != null));
  return ClienteRenovavel(
    basePath: noBaseUrl,
    tokenAtual: () => ref.read(sessionControllerProvider).valueOrNull?.accessToken,
    renovar: () => ref.read(sessionControllerProvider.notifier).renovarAgora(),
  );
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
