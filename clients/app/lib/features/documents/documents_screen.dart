import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../design/secao.dart';
import '../../design/tokens.dart';
import 'document_status_screen.dart';
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
    // sem acervo, o estado vazio JÁ oferece o botão, centralizado e
    // explicado. Dois botões idênticos na mesma tela não são duas
    // oportunidades: são a pessoa decidindo em qual clicar.
    final vazio = documentos.valueOrNull?.isEmpty ?? false;

    return MolduraDeSecao(
      titulo: 'Documentos',
      acoes: [
        if (!vazio)
          FilledButton.icon(
            onPressed: () => _pedirPasta(context, ref),
            icon: const Icon(Icons.create_new_folder_outlined, size: 17),
            label: const Text('Indexar pasta'),
            style: FilledButton.styleFrom(
              padding: const EdgeInsets.symmetric(
                horizontal: Espaco.largo,
                vertical: Espaco.medio,
              ),
              textStyle: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
      ],
      child: ListaAssincrona<DocumentOut>(
        valor: documentos,
        oQueSeria: 'o acervo',
        iconeDoVazio: Icons.folder_outlined,
        quandoVazio:
            'Nenhum documento ainda. Indexe uma pasta para a Lumbra poder '
            'consultá-la — os arquivos ficam onde estão, no seu computador.',
        acaoDoVazio: FilledButton.icon(
          onPressed: () => _pedirPasta(context, ref),
          icon: const Icon(Icons.create_new_folder_outlined, size: 17),
          label: const Text('Indexar pasta'),
        ),
        aoTerConteudo: (lista) => ColunaDeLeitura(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(
              Espaco.grande,
              Espaco.largo,
              Espaco.grande,
              Espaco.enorme,
            ),
            children: [for (final d in lista) _Documento(documento: d)],
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
    final pronto = documento.processingState == 'indexed';
    final nome = documento.title ?? _nomeDoArquivo(documento.uri);

    return CartaoDaLumbra(
      // a lista diz O QUE aconteceu; tocar mostra ONDE
      aoTocar: () => Navigator.of(context).push(
        MaterialPageRoute<void>(
          builder: (_) =>
              DocumentStatusScreen(documentId: documento.id, titulo: nome),
        ),
      ),
      child: Row(
        children: [
          Icon(
            falhou ? Icons.error_outline : Icons.description_outlined,
            size: 18,
            color: falhou ? cores.error : cores.onSurfaceVariant,
          ),
          const SizedBox(width: Espaco.medio),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  nome,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: textos.bodyMedium?.copyWith(fontSize: 13.5),
                ),
                if (documento.version > 1)
                  Padding(
                    padding: const EdgeInsets.only(top: Espaco.micro),
                    child: Text(
                      'versão ${documento.version}',
                      style: TextStyle(
                        fontSize: 11,
                        color: cores.onSurfaceVariant,
                      ),
                    ),
                  ),
              ],
            ),
          ),
          const SizedBox(width: Espaco.medio),
          _EstadoDoPipeline(
            estado: documento.processingState,
            falhou: falhou,
            pronto: pronto,
          ),
          const SizedBox(width: Espaco.curto),
          Icon(Icons.chevron_right, size: 18, color: cores.onSurfaceVariant),
        ],
      ),
    );
  }

  /// Sem título extraído, o nome do arquivo diz mais que a URI inteira.
  static String _nomeDoArquivo(String uri) {
    final partes = uri.split('/');
    return partes.isEmpty ? uri : Uri.decodeComponent(partes.last);
  }
}

/// Em que pé está a leitura deste arquivo.
///
/// Vale um selo com cor porque a diferença entre "na fila" e "pesquisável" é
/// a diferença entre "a Lumbra ainda não sabe disso" e "pode perguntar" — e
/// alguém que pergunta cedo demais conclui que a indexação não funcionou.
class _EstadoDoPipeline extends StatelessWidget {
  const _EstadoDoPipeline({
    required this.estado,
    required this.falhou,
    required this.pronto,
  });

  final String estado;
  final bool falhou;
  final bool pronto;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final cor = falhou
        ? cores.error
        : (pronto ? const Color(0xFF4CAF7D) : cores.onSurfaceVariant);

    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: Espaco.curto,
        vertical: Espaco.micro,
      ),
      decoration: BoxDecoration(
        color: cores.surfaceContainerHigh,
        borderRadius: Raio.bordaSelo,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 5,
            height: 5,
            decoration: BoxDecoration(color: cor, shape: BoxShape.circle),
          ),
          const SizedBox(width: Espaco.curto - 2),
          Text(
            estadosDoPipeline[estado] ?? estado,
            style: TextStyle(fontSize: 11, color: cores.onSurface),
          ),
        ],
      ),
    );
  }
}
