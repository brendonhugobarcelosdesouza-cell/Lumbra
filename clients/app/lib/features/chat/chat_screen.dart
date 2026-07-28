import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../core/api.dart';
import '../../core/session.dart';
import 'chat_models.dart';
import 'chat_providers.dart';
import 'chat_stream.dart';

/// A conversa: histórico + envio com STREAMING (P2-c.2). A resposta aparece
/// token a token; as fontes chegam antes do texto e viram chips clicáveis.
/// "Parar" cancela a geração (fecha a conexão — o Nó libera a GPU).
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

  StreamSubscription<ChatStreamEvent>? _sub;
  String? _parcial; // texto do assistente em construção (null = sem stream)
  List<CitationOut> _parciaisCitacoes = const [];
  String? _ultimoTexto; // para re-tentar após renovar o token (401)
  bool _tentouRenovar = false;

  @override
  void initState() {
    super.initState();
    _carregarHistorico();
  }

  @override
  void dispose() {
    _sub?.cancel();
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

  void _enviar() {
    final texto = _campo.text.trim();
    if (texto.isEmpty || _enviando) return;
    _campo.clear();
    _ultimoTexto = texto;
    _tentouRenovar = false;
    setState(() {
      _bolhas = [..._bolhas, ChatBubble.user(texto)];
    });
    _rolarAoFim();
    _iniciarStream(texto);
  }

  void _iniciarStream(String texto) {
    final token = ref.read(sessionControllerProvider).valueOrNull?.accessToken;
    setState(() {
      _parcial = '';
      _parciaisCitacoes = const [];
      _enviando = true;
    });
    _sub =
        streamChat(
          baseUrl: noBaseUrl,
          token: token,
          conversationId: widget.conversationId,
          content: texto,
        ).listen(
          _aoEvento,
          onError: (Object e) {
            if (!mounted) return;
            setState(() {
              _bolhas = [..._bolhas, ChatBubble.error('Falha ao responder: $e')];
              _limparStream();
            });
          },
          onDone: () {
            if (!mounted || _parcial == null) return;
            setState(_finalizar);
          },
        );
  }

  void _aoEvento(ChatStreamEvent ev) {
    if (!mounted) return;
    // token expirou (401): renova com o refresh e re-tenta a última mensagem
    // uma única vez, sem incomodar o usuário.
    if (ev is StreamErrorEvent &&
        ev.detail.contains('401') &&
        !_tentouRenovar &&
        _ultimoTexto != null) {
      _tentouRenovar = true;
      setState(_limparStream);
      _renovarERetentar();
      return;
    }
    setState(() {
      if (ev is TokenEvent) {
        _parcial = (_parcial ?? '') + ev.delta;
      } else if (ev is SourcesEvent) {
        _parciaisCitacoes = ev.citations;
      } else if (ev is DoneEvent || ev is CancelledEvent) {
        _finalizar();
      } else if (ev is StreamErrorEvent) {
        _bolhas = [..._bolhas, ChatBubble.error(ev.detail)];
        _limparStream();
      }
    });
    _rolarAoFim();
  }

  Future<void> _renovarERetentar() async {
    await ref.read(sessionControllerProvider.notifier).refresh();
    if (mounted && _ultimoTexto != null) _iniciarStream(_ultimoTexto!);
  }

  /// Fixa o texto acumulado como bolha final. Chamado dentro de setState.
  void _finalizar() {
    final texto = _parcial;
    if (texto != null && texto.isNotEmpty) {
      _bolhas = [
        ..._bolhas,
        ChatBubble(BubbleRole.assistant, texto, citations: _parciaisCitacoes),
      ];
    }
    _limparStream();
  }

  void _limparStream() {
    _parcial = null;
    _parciaisCitacoes = const [];
    _enviando = false;
    _sub?.cancel();
    _sub = null;
  }

  void _parar() => setState(_finalizar);

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
    // bolha viva do stream (se houver) entra no fim da lista
    final vivas = <ChatBubble>[
      ..._bolhas,
      if (_parcial != null)
        ChatBubble(
          BubbleRole.assistant,
          _parcial!.isEmpty ? '…' : _parcial!,
          citations: _parciaisCitacoes,
        ),
    ];
    if (vivas.isEmpty) {
      return const Center(child: Text('Faça a primeira pergunta.'));
    }
    return ListView.builder(
      controller: _scroll,
      padding: const EdgeInsets.all(12),
      itemCount: vivas.length,
      itemBuilder: (_, i) => _BolhaView(vivas[i]),
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
          if (_enviando)
            IconButton.filledTonal(
              tooltip: 'Parar',
              onPressed: _parar,
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
