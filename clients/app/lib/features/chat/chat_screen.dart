import 'package:flutter/material.dart';
import 'package:flutter_markdown/flutter_markdown.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../design/tokens.dart';
import 'chat_models.dart';
import 'chat_providers.dart';
import 'conversa_estado.dart';

/// A conversa: histórico + envio com streaming (P2-c.2). A resposta aparece
/// token a token; as fontes chegam antes do texto e viram chips clicáveis.
///
/// A tela não conduz mais a conversa — quem conduz é o
/// [ControladorDaConversa]. Aqui só se desenha o que ele diz e se avisa o que
/// o usuário fez. A troca não foi estética: enquanto o estado morava neste
/// widget, nenhum painel irmão conseguia saber qual mensagem estava em foco,
/// e o painel de contexto da referência depende exatamente disso.
class ChatScreen extends ConsumerStatefulWidget {
  const ChatScreen({super.key, required this.conversationId, this.title});

  final String conversationId;
  final String? title;

  @override
  ConsumerState<ChatScreen> createState() => _ChatScreenState();
}

class _ChatScreenState extends ConsumerState<ChatScreen> {
  final _campo = TextEditingController();
  final _scroll = ScrollController();

  ControladorDaConversa get _controlador =>
      ref.read(conversaProvider(widget.conversationId).notifier);

  @override
  void initState() {
    super.initState();
    // fora do build: mexer em provider durante a construção do widget é o
    // caminho conhecido para reconstruções em cascata
    WidgetsBinding.instance.addPostFrameCallback(
      (_) => _controlador.adotarTitulo(widget.title),
    );
  }

  @override
  void dispose() {
    _campo.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _enviar() {
    final texto = _campo.text;
    if (texto.trim().isEmpty) return;
    _campo.clear();
    _controlador.enviar(texto);
  }

  void _rolarAoFim() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (_scroll.hasClients) {
        _scroll.jumpTo(_scroll.position.maxScrollExtent);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final conversa = conversaProvider(widget.conversationId);
    // `listen` e não uma chamada solta no build: rolar ao fim é reação a
    // CHEGAR conteúdo novo, não a redesenhar. Chamado no build, um simples
    // redimensionar a janela arrancaria o usuário de volta para baixo no meio
    // de uma leitura.
    ref.listen(conversa, (_, __) => _rolarAoFim());
    final estado = ref.watch(conversa);

    return Scaffold(
      appBar: AppBar(
        title: Text(estado.titulo ?? 'Conversa'),
        actions: [
          TextButton.icon(
            onPressed: _escolherProvedor,
            icon: const Icon(Icons.tune, size: 18),
            label: Text(estado.provedor ?? 'Modelo'),
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(child: _corpo(estado)),
          const Divider(height: 1),
          _entrada(estado),
        ],
      ),
    );
  }

  Widget _corpo(EstadoDaConversa estado) {
    if (estado.carregando) {
      return const Center(child: CircularProgressIndicator());
    }
    if (estado.erroDeCarga != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(Espaco.grande),
          child: Text(
            'Não foi possível carregar a conversa.\n${estado.erroDeCarga}',
          ),
        ),
      );
    }
    final vivas = estado.visiveis;
    if (vivas.isEmpty) {
      return const Center(child: Text('Faça a primeira pergunta.'));
    }
    return ListView.builder(
      controller: _scroll,
      padding: const EdgeInsets.all(Espaco.medio),
      itemCount: vivas.length,
      itemBuilder: (_, i) => _BolhaView(vivas[i]),
    );
  }

  Widget _entrada(EstadoDaConversa estado) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(
        Espaco.medio,
        Espaco.curto,
        Espaco.medio,
        Espaco.medio,
      ),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _campo,
              minLines: 1,
              maxLines: 5,
              enabled: !estado.enviando,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => _enviar(),
              decoration: const InputDecoration(
                hintText: 'Pergunte ou diga à Lumbra o que fazer…',
                border: OutlineInputBorder(),
              ),
            ),
          ),
          const SizedBox(width: Espaco.curto),
          if (estado.enviando)
            IconButton.filledTonal(
              tooltip: 'Parar',
              onPressed: _controlador.parar,
              icon: const Icon(Icons.stop),
            )
          else
            IconButton.filled(
              tooltip: 'Enviar',
              onPressed: _enviar,
              icon: const Icon(Icons.send),
            ),
        ],
      ),
    );
  }

  Future<void> _escolherProvedor() async {
    List<ProviderChoice> escolhas;
    try {
      escolhas = await ref.read(providersProvider.future);
    } catch (e) {
      _avisar('Não foi possível listar modelos: $e');
      return;
    }
    if (!mounted) return;
    final escolhido = await showDialog<ProviderChoice>(
      context: context,
      builder: (_) => SimpleDialog(
        title: const Text('Escolher modelo'),
        children: [
          for (final p in escolhas)
            SimpleDialogOption(
              onPressed: () => Navigator.pop(context, p),
              child: ListTile(
                contentPadding: EdgeInsets.zero,
                leading: Icon(p.isLocal ? Icons.computer : Icons.cloud),
                title: Text(p.name),
                subtitle: Text(
                  '${p.model} · ${p.isLocal ? "local, sem custo" : "nuvem"}',
                ),
              ),
            ),
        ],
      ),
    );
    if (escolhido == null) return;
    try {
      await _controlador.escolherProvedor(escolhido);
      _avisar(
        'Modelo: ${escolhido.name} (${escolhido.isLocal ? "local" : "nuvem"})',
      );
    } catch (e) {
      _avisar('Falha ao trocar de modelo: $e');
    }
  }

  void _avisar(String recado) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(recado)));
  }
}

class _BolhaView extends StatelessWidget {
  const _BolhaView(this.bolha);

  final ChatBubble bolha;

  @override
  Widget build(BuildContext context) {
    final tema = Theme.of(context);
    final usuario = bolha.role == BubbleRole.user;
    final erro = bolha.role == BubbleRole.error;
    final cor = erro
        ? tema.colorScheme.errorContainer
        : usuario
        ? tema.colorScheme.primaryContainer
        : tema.colorScheme.secondaryContainer;

    return Align(
      alignment: usuario ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: Espaco.minimo),
        padding: const EdgeInsets.all(Espaco.medio),
        constraints: const BoxConstraints(maxWidth: Coluna.leitura),
        decoration: BoxDecoration(color: cor, borderRadius: Raio.bordaCartao),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // a resposta do assistente vem em Markdown; a do usuário e os
            // erros são texto plano (não interpretar a entrada do usuário)
            if (bolha.role == BubbleRole.assistant)
              MarkdownBody(data: bolha.text, selectable: true)
            else
              SelectableText(bolha.text),
            if (bolha.usedCitations.isNotEmpty) ...[
              const SizedBox(height: Espaco.curto),
              Wrap(
                spacing: Espaco.curto,
                runSpacing: Espaco.curto,
                children: [
                  for (final c in bolha.usedCitations)
                    ActionChip(
                      label: Text('[${c.ordinal}] ${_rotuloCurto(c)}'),
                      onPressed: () => _mostrarCitacao(context, c),
                    ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  /// Rótulo curto da fonte: o título do documento, ou o tipo se não houver.
  /// Faz o chip identificar a fonte, não só numerá-la.
  String _rotuloCurto(CitationOut c) {
    final titulo = c.title;
    if (titulo != null && titulo.trim().isNotEmpty) {
      final t = titulo.trim();
      return t.length > 24 ? '${t.substring(0, 23)}…' : t;
    }
    return c.kind;
  }

  void _mostrarCitacao(BuildContext context, CitationOut c) {
    showDialog<void>(
      context: context,
      builder: (_) => AlertDialog(
        title: Text(c.title ?? 'Fonte [${c.ordinal}]'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Tipo: ${c.kind}'),
            if (c.snippet != null) ...[
              const SizedBox(height: Espaco.curto),
              Text(c.snippet!),
            ],
            if (c.uri != null) ...[
              const SizedBox(height: Espaco.curto),
              Text(c.uri!, style: Theme.of(context).textTheme.bodySmall),
            ],
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Fechar'),
          ),
        ],
      ),
    );
  }
}
