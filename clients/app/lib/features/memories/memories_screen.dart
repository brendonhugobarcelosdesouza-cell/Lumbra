import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import 'memories_providers.dart';

/// O que a Lumbra sabe sobre você — e o botão de apagar ao lado.
///
/// Esta tela nasceu de um episódio concreto: a reflexão automática guardou
/// uma resposta ERRADA como fato ("a fatura é R$ 6.314,94"), a memória
/// passou a vencer o documento na busca, e o chat repetiu o erro por dias. A
/// correção foi apagar o registro — por linha de comando, porque não havia
/// onde clicar.
///
/// Memória que não dá para inspecionar não é memória, é um viés invisível.
/// Por isso a lista mostra TUDO, inclusive o que a plataforma guardou
/// sozinha, e o esquecer fica a um toque.
class MemoriesScreen extends ConsumerWidget {
  const MemoriesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final memorias = ref.watch(memoriesProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Memória')),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 720),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const _FiltroDeCamada(),
              Expanded(
                child: memorias.when(
                  loading: () => const Center(child: CircularProgressIndicator()),
                  error: (erro, _) => Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Text(
                        'Não foi possível carregar a memória.\n$erro',
                        textAlign: TextAlign.center,
                      ),
                    ),
                  ),
                  data: (lista) => lista.isEmpty
                      ? const Center(
                          child: Padding(
                            padding: EdgeInsets.all(24),
                            child: Text(
                              'Nada guardado nesta camada.',
                              textAlign: TextAlign.center,
                            ),
                          ),
                        )
                      : ListView(
                          padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
                          children: [
                            for (final m in lista) _Memoria(memoria: m),
                          ],
                        ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

/// As quatro camadas, na ordem em que esquecem: da mais volátil à mais
/// duradoura. Os nomes técnicos não vão para a tela.
const camadas = <String?, String>{
  null: 'Tudo',
  'temporary': 'Temporária',
  'episodic': 'Episódica',
  'semantic': 'Fatos',
  'procedural': 'Hábitos',
};

class _FiltroDeCamada extends ConsumerWidget {
  const _FiltroDeCamada();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final atual = ref.watch(camadaSelecionadaProvider);
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
      child: Wrap(
        spacing: 8,
        children: [
          for (final entrada in camadas.entries)
            ChoiceChip(
              label: Text(entrada.value),
              selected: atual == entrada.key,
              onSelected: (_) =>
                  ref.read(camadaSelecionadaProvider.notifier).state = entrada.key,
            ),
        ],
      ),
    );
  }
}

class _Memoria extends ConsumerWidget {
  const _Memoria({required this.memoria});

  final MemoryItemOut memoria;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cores = Theme.of(context).colorScheme;
    final textos = Theme.of(context).textTheme;
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: cores.outline),
      ),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 14, 8, 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(memoria.content, style: textos.bodyMedium),
            const SizedBox(height: 8),
            Row(
              children: [
                Text(
                  // camada, quando chegou e quantas vezes foi usada: é o que
                  // permite julgar se aquele "fato" merece continuar existindo
                  '${camadas[memoria.kind] ?? memoria.kind}'
                  ' · ${_data(memoria.createdAt)}'
                  ' · ${_usos(memoria.accessCount)}',
                  style: textos.bodySmall,
                ),
                const Spacer(),
                TextButton.icon(
                  onPressed: () => _esquecer(context, ref),
                  icon: const Icon(Icons.delete_outline, size: 18),
                  label: const Text('Esquecer'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  static String _usos(int quantos) =>
      quantos == 0 ? 'nunca usada' : 'usada ${quantos}x';

  static String _data(String iso) {
    final d = DateTime.tryParse(iso)?.toLocal();
    if (d == null) return 'sem data';
    final dd = d.day.toString().padLeft(2, '0');
    final mm = d.month.toString().padLeft(2, '0');
    return '$dd/$mm/${d.year}';
  }

  Future<void> _esquecer(BuildContext context, WidgetRef ref) async {
    try {
      await ref.read(memoryApiProvider).forgetApiV1MemoryMemoryIdDelete(memoria.id);
      ref.invalidate(memoriesProvider);
      if (!context.mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('Esquecido.')));
    } on ApiException catch (e) {
      if (!context.mounted) return;
      // 409: o gate pediu confirmação — apagar memória é ação de impacto
      final aviso = e.code == 409
          ? 'Precisa da sua confirmação — veja em Aprovações.'
          : 'Não foi possível esquecer: ${e.message ?? e.code}';
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(aviso)));
    } catch (e) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('Não foi possível esquecer: $e')));
    }
  }
}
