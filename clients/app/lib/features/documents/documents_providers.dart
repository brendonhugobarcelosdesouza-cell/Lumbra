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
