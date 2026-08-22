import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../core/api.dart';

/// O diagnóstico do Nó — a MESMA fonte de verdade do `lumbra doctor`.
///
/// A rota é pública de propósito (System Health): é a que alguém consulta
/// justamente quando nada funciona, inclusive o login. O cliente autenticado
/// serve do mesmo jeito — sem sessão ele simplesmente não manda o Bearer, e
/// a rota não o exige.
final saudeProvider = FutureProvider.autoDispose<HealthOut?>((ref) async {
  return ref.watch(opsApiProvider).saudeApiV1SystemHealthGet();
});
