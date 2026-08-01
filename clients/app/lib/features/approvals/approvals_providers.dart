import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../core/api.dart';

/// API de aprovações (L2.0) — gerada do contrato, como todo o resto.
final approvalsApiProvider = Provider<ApprovalsApi>(
  (ref) => ApprovalsApi(ref.watch(apiClientProvider)),
);

/// Pedidos aguardando a decisão do usuário. É a fila que dá destino ao 409
/// das ações de risco: sem esta lista, o "precisa confirmar" morria no erro.
final pendingApprovalsProvider = FutureProvider.autoDispose<List<ApprovalOut>>((
  ref,
) async {
  final api = ref.watch(approvalsApiProvider);
  final fila = await api.listPendingApiV1ApprovalsGet();
  return fila?.approvals ?? const [];
});
