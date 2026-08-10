import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../core/api.dart';

/// API do acervo — o que a Lumbra leu.
final documentsApiProvider = Provider<DocumentsApi>(
  (ref) => DocumentsApi(ref.watch(apiClientProvider)),
);

final documentsProvider = FutureProvider.autoDispose<List<DocumentOut>>((
  ref,
) async {
  final api = ref.watch(documentsApiProvider);
  final res = await api.listDocumentsApiV1DocumentsGet(limit: 200);
  return res?.documents ?? const [];
});

/// O porquê de um documento estar (ou não estar) pesquisável: etapas do
/// pipeline e histórico de versões.
///
/// Por documento (`family`) e descartável (`autoDispose`): é consulta de
/// diagnóstico, aberta sob demanda — manter em memória o status de um acervo
/// inteiro seria pagar por algo que quase nunca se olha duas vezes.
final documentStatusProvider = FutureProvider.autoDispose
    .family<DocumentStatusOut?, String>((ref, documentId) async {
      final api = ref.watch(documentsApiProvider);
      return api.documentStatusApiV1DocumentsDocumentIdStatusGet(documentId);
    });
