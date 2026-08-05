import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../core/api.dart';

/// API de memória procedural (L1.5) — gerada do contrato.
final playbooksApiProvider = Provider<PlaybooksApi>(
  (ref) => PlaybooksApi(ref.watch(apiClientProvider)),
);

/// Os procedimentos do usuário. Existe porque ele é DONO do que a plataforma
/// aprendeu sobre o próprio trabalho: sem esta lista, o conhecimento seria
/// dela, não dele.
final playbooksProvider = FutureProvider.autoDispose<List<PlaybookOut>>((
  ref,
) async {
  final api = ref.watch(playbooksApiProvider);
  final lista = await api.listPlaybooksApiV1PlaybooksGet();
  return lista?.playbooks ?? const [];
});
