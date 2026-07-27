import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import 'chat_models.dart';
import 'chat_providers.dart';

/// A conversa: histórico + envio. Sem streaming ainda (P2-c.2) — a resposta
/// aparece inteira quando o Nó termina. As citações vêm numeradas e
/// clicáveis, provando o RAG ponta a ponta.
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
  List<ChatBubble> _bolhas = const [];
  bool _carregando = true;
  bool _enviando = false;
  String? _erroCarga;

  @override
  void initState() {
    super.initState();
    _carregarHistorico();
  }

  @override
  void dispose() {
    _campo.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _carregarHistorico() async {
    try {
      final api = ref.read(chatApiProvider);
      final hist = await api
          .historyApiV1ChatConversationsConversationIdMessagesGet(
            widget.conversationId,
          );
      if (!mounted) return;
      setState(() {
        _bolhas = (hist?.messages ?? const [])
            .map(ChatBubble.fromMessage)
            .toList();
        _carregando = false;
      });
      _rolarAoFim();
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _erroCarga = '$e';
        _carregando = false;
      });
    }
  }

  Future<void> _enviar() async {
    final texto = _campo.text.trim();
    if (texto.isEmpty || _enviando) return;
    _campo.clear();
    setState(() {
      _bolhas = [..._bolhas, ChatBubble.user(texto)];
      _enviando = true;
    });
    _rolarAoFim();
    try {
      final api = ref.read(chatApiProvider);
      final resp = await api
          .sendApiV1ChatConversationsConversationIdMessagesPost(
            widget.conversationId,
            SendBody(content: texto),
          );
      if (!mounted) return;
      setState(() {
        if (resp != null) _bolhas = [..._bolhas, ChatBubble.fromResponse(resp)];
        _enviando = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _bolhas = [..._bolhas, ChatBubble.error('Falha ao responder: $e')];
        _enviando = false;
      });
    }
    _rolarAoFim();
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
    return Scaffold(
      appBar: AppBar(title: Text(widget.title ?? 'Conversa')),
      body: Column(
        children: [
          Expanded(child: _corpo()),
          if (_enviando) const LinearProgressIndicator(),
          const Divider(height: 1),
          _entrada(),
        ],
      ),
    );
  }

  Widget _corpo() {
    if (_carregando) return const Center(child: CircularProgressIndicator());
    if (_erroCarga != null) {
      return Center(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Text('Não foi possível carregar a conversa.\n$_erroCarga'),
        ),
      );
    }
    if (_bolhas.isEmpty) {
      return const Center(child: Text('Faça a primeira pergunta.'));
    }
    return ListView.builder(
      controller: _scroll,
      padding: const EdgeInsets.all(12),
      itemCount: _bolhas.length,
      itemBuilder: (_, i) => _BolhaView(_bolhas[i]),
    );
  }

  Widget _entrada() {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
      child: Row(
        children: [
          Expanded(
            child: TextField(
              controller: _campo,
              minLines: 1,
              maxLines: 5,
              enabled: !_enviando,
              textInputAction: TextInputAction.send,
              onSubmitted: (_) => _enviar(),
              decoration: const InputDecoration(
                hintText: 'Pergunte algo…',
                border: OutlineInputBorder(),
              ),
            ),
          ),
          const SizedBox(width: 8),
          IconButton.filled(
            onPressed: _enviando ? null : _enviar,
            icon: const Icon(Icons.send),
          ),
        ],
      ),
    );
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
        margin: const EdgeInsets.symmetric(vertical: 4),
        padding: const EdgeInsets.all(12),
        constraints: const BoxConstraints(maxWidth: 560),
        decoration: BoxDecoration(
          color: cor,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SelectableText(bolha.text),
            if (bolha.citations.isNotEmpty) ...[
              const SizedBox(height: 8),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  for (final c in bolha.citations)
                    ActionChip(
                      label: Text('[${c.ordinal}]'),
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
              const SizedBox(height: 8),
              Text(c.snippet!),
            ],
            if (c.uri != null) ...[
              const SizedBox(height: 8),
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
