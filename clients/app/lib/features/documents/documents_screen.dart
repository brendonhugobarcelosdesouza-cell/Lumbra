import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import 'documents_providers.dart';

/// O acervo: o que a Lumbra leu, e em que pé está.
///
/// Até aqui, indexar uma pasta exigia o Developer Console — a coisa mais
/// central da plataforma não tinha caminho de usuário. E o estado do
/// pipeline importa tanto quanto a lista: saber que um arquivo foi visto mas
/// ainda não indexado é a diferença entre "a Lumbra não sabe disso" e "a
/// Lumbra ainda não terminou de ler".
class DocumentsScreen extends ConsumerWidget {
  const DocumentsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final documentos = ref.watch(documentsProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Documentos')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => _pedirPasta(context, ref),
        icon: const Icon(Icons.create_new_folder_outlined),
        label: const Text('Indexar pasta'),
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 720),
          child: documentos.when(
            loading: () => const Center(child: CircularProgressIndicator()),
            error: (erro, _) => Center(
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Text(
                  'Não foi possível carregar o acervo.\n$erro',
                  textAlign: TextAlign.center,
                ),
              ),
            ),
            data: (lista) => lista.isEmpty
                ? const Center(
                    child: Padding(
                      padding: EdgeInsets.all(24),
                      child: Text(
                        'Nenhum documento ainda.\n'
                        'Indexe uma pasta para a Lumbra poder consultá-la.',
                        textAlign: TextAlign.center,
                      ),
                    ),
                  )
                : ListView(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
                    children: [for (final d in lista) _Documento(documento: d)],
                  ),
          ),
        ),
      ),
    );
  }

  Future<void> _pedirPasta(BuildContext context, WidgetRef ref) async {
    final caminho = await showDialog<String>(
      context: context,
      builder: (_) => const _DialogoIndexar(),
    );
    if (caminho == null || caminho.isEmpty || !context.mounted) return;
    try {
      final r = await ref
          .read(documentsApiProvider)
          .indexFolderApiV1DocumentsIndexPost(IndexBody(path: caminho));
      ref.invalidate(documentsProvider);
      if (!context.mounted) return;
      // fala de ENFILEIRADO, não de pronto: quem termina é o worker, e
      // prometer conclusão aqui seria mentira
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            r == null
                ? 'Indexação solicitada.'
                : '${r.discovered} encontrados · ${r.queued} na fila · '
                      '${r.unchanged} sem mudança',
          ),
        ),
      );
    } on ApiException catch (e) {
      if (!context.mounted) return;
      final aviso = e.code == 503
          ? 'Este Nó está sem banco de dados — a indexação precisa dele.'
          : 'Não foi possível indexar: ${e.message ?? e.code}';
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(aviso)));
    } catch (e) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('Não foi possível indexar: $e')));
    }
  }
}

/// Pede o caminho da pasta.
///
/// Digitado, e não escolhido num seletor nativo: o seletor é um plugin por
/// plataforma, e o app roda em seis. Entra quando a janela nativa existir —
/// até lá, colar um caminho funciona em todas.
class _DialogoIndexar extends StatefulWidget {
  const _DialogoIndexar();

  @override
  State<_DialogoIndexar> createState() => _DialogoIndexarState();
}

class _DialogoIndexarState extends State<_DialogoIndexar> {
  final _controle = TextEditingController();

  @override
  void dispose() {
    _controle.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: const Text('Indexar pasta'),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'A Lumbra vai ler os arquivos desta pasta para poder responder '
            'sobre eles. Nada sai do seu computador.',
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _controle,
            autofocus: true,
            decoration: const InputDecoration(
              labelText: 'Caminho',
              hintText: r'C:\Users\voce\Documentos\faturas',
            ),
            onSubmitted: (v) => Navigator.of(context).pop(v.trim()),
          ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Cancelar'),
        ),
        FilledButton(
          onPressed: () => Navigator.of(context).pop(_controle.text.trim()),
          child: const Text('Indexar'),
        ),
      ],
    );
  }
}

/// Como cada estado do pipeline é dito a quem não o construiu.
const estadosDoPipeline = <String, String>{
  'pending': 'na fila',
  'processing': 'lendo',
  'indexed': 'pesquisável',
  'failed': 'falhou',
};

class _Documento extends StatelessWidget {
  const _Documento({required this.documento});

  final DocumentOut documento;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final textos = Theme.of(context).textTheme;
    final falhou = documento.processingState == 'failed';
    return Card(
      margin: const EdgeInsets.only(bottom: 10),
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: cores.outline),
      ),
      child: ListTile(
        leading: Icon(
          falhou ? Icons.error_outline : Icons.description_outlined,
          color: falhou ? cores.error : null,
        ),
        title: Text(documento.title ?? _nomeDoArquivo(documento.uri)),
        subtitle: Text(
          '${estadosDoPipeline[documento.processingState] ?? documento.processingState}'
          '${documento.version > 1 ? ' · versão ${documento.version}' : ''}',
          style: textos.bodySmall,
        ),
      ),
    );
  }

  /// Sem título extraído, o nome do arquivo diz mais que a URI inteira.
  static String _nomeDoArquivo(String uri) {
    final partes = uri.split('/');
    return partes.isEmpty ? uri : Uri.decodeComponent(partes.last);
  }
}
