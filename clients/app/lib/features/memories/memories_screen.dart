import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../design/secao.dart';
import '../../design/tokens.dart';
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
    final atual = ref.watch(camadaSelecionadaProvider);
    return MolduraDeSecao(
      titulo: 'Memória',
      abaixoDoTitulo: const _FiltroDeCamada(),
      child: ListaAssincrona<MemoryItemOut>(
        valor: ref.watch(memoriesProvider),
        oQueSeria: 'a memória',
        iconeDoVazio: Icons.psychology_outlined,
        // a frase muda com o filtro: "nada guardado" numa camada específica
        // é uma informação diferente de "a Lumbra ainda não sabe nada sobre
        // você", e a segunda assusta quem só trocou de aba
        quandoVazio: atual == null
            ? 'A Lumbra ainda não guardou nada sobre você. O que ela aprender '
                  'nas conversas aparece aqui — e você pode apagar.'
            : 'Nada guardado nesta camada.',
        aoTerConteudo: (lista) => ColunaDeLeitura(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(
              Espaco.grande,
              Espaco.largo,
              Espaco.grande,
              Espaco.enorme,
            ),
            children: [for (final m in lista) _Memoria(memoria: m)],
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
      padding: const EdgeInsets.fromLTRB(
        Espaco.grande,
        Espaco.nada,
        Espaco.grande,
        Espaco.largo,
      ),
      child: Wrap(
        spacing: Espaco.curto,
        runSpacing: Espaco.curto,
        children: [
          for (final entrada in camadas.entries)
            ChoiceChip(
              label: Text(entrada.value),
              selected: atual == entrada.key,
              showCheckmark: false,
              onSelected: (_) =>
                  ref.read(camadaSelecionadaProvider.notifier).state =
                      entrada.key,
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
    return CartaoDaLumbra(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            memoria.content,
            style: textos.bodyMedium?.copyWith(fontSize: 14, height: 1.55),
          ),
          const SizedBox(height: Espaco.medio),
          Row(
            children: [
              Expanded(
                child: Text(
                  // camada, quando chegou e quantas vezes foi usada: é o que
                  // permite julgar se aquele "fato" merece continuar existindo
                  '${camadas[memoria.kind] ?? memoria.kind}'
                  ' · ${_data(memoria.createdAt)}'
                  ' · ${_usos(memoria.accessCount)}',
                  style: TextStyle(
                    fontSize: 11.5,
                    color: cores.onSurfaceVariant,
                  ),
                ),
              ),
              TextButton.icon(
                onPressed: () => _esquecer(context, ref),
                icon: const Icon(Icons.delete_outline, size: 16),
                label: const Text('Esquecer', style: TextStyle(fontSize: 12.5)),
                style: TextButton.styleFrom(
                  foregroundColor: cores.onSurfaceVariant,
                  padding: const EdgeInsets.symmetric(
                    horizontal: Espaco.medio,
                    vertical: Espaco.curto,
                  ),
                ),
              ),
            ],
          ),
        ],
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
      await ref
          .read(memoryApiProvider)
          .forgetApiV1MemoryMemoryIdDelete(memoria.id);
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
