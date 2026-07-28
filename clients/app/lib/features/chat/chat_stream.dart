import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:lumbra_api/api.dart';

/// Leitor SSE do chat — a ÚNICA exceção nomeada à regra "só cliente gerado"
/// (ADR-050). O contrato OpenAPI não modela `text/event-stream`, então o
/// cliente gerado não serve para streaming. Este adapter ainda fala com o
/// mesmo Nó, pelo mesmo caminho do contrato e com o mesmo Bearer da sessão —
/// só o transporte (stream de eventos) é que o contrato não expressa.
///
/// Protocolo (doc 11): `sources` (citações, antes do texto), `token` (delta),
/// `done` (fim), `cancelled`, `error`.

sealed class ChatStreamEvent {
  const ChatStreamEvent();
}

class SourcesEvent extends ChatStreamEvent {
  const SourcesEvent(this.citations);
  final List<CitationOut> citations;
}

class TokenEvent extends ChatStreamEvent {
  const TokenEvent(this.delta);
  final String delta;
}

class DoneEvent extends ChatStreamEvent {
  const DoneEvent({required this.messageId, required this.provider, required this.model});
  final String messageId;
  final String provider;
  final String model;
}

class CancelledEvent extends ChatStreamEvent {
  const CancelledEvent({required this.partialSaved});
  final bool partialSaved;
}

class StreamErrorEvent extends ChatStreamEvent {
  const StreamErrorEvent(this.detail);
  final String detail;
}

/// Envia uma mensagem e transmite a resposta do Nó token a token.
/// Cancelar a assinatura do Stream fecha a conexão — o Nó detecta a
/// desconexão e interrompe a geração (libera a GPU).
Stream<ChatStreamEvent> streamChat({
  required String baseUrl,
  required String? token,
  required String conversationId,
  required String content,
  http.Client? client,
}) async* {
  final c = client ?? http.Client();
  try {
    final uri = Uri.parse(
      '$baseUrl/api/v1/chat/conversations/$conversationId/messages/stream',
    );
    final req = http.Request('POST', uri);
    req.headers['content-type'] = 'application/json';
    req.headers['accept'] = 'text/event-stream';
    if (token != null) req.headers['authorization'] = 'Bearer $token';
    req.body = jsonEncode({'content': content, 'use_context': true});

    final resp = await c.send(req);
    if (resp.statusCode >= 400) {
      yield StreamErrorEvent('HTTP ${resp.statusCode}');
      return;
    }

    var evento = 'message';
    final dados = StringBuffer();
    final linhas = resp.stream.transform(utf8.decoder).transform(const LineSplitter());
    await for (final linha in linhas) {
      if (linha.isEmpty) {
        final ev = _parse(evento, dados.toString());
        if (ev != null) yield ev;
        evento = 'message';
        dados.clear();
        continue;
      }
      if (linha.startsWith(':')) continue; // comentário SSE (keep-alive)
      if (linha.startsWith('event:')) {
        evento = linha.substring(6).trim();
      } else if (linha.startsWith('data:')) {
        dados.write(linha.substring(5).trim());
      }
    }
  } finally {
    if (client == null) c.close();
  }
}

ChatStreamEvent? _parse(String evento, String data) {
  if (data.isEmpty) return null;
  final Map<String, dynamic> json;
  try {
    json = jsonDecode(data) as Map<String, dynamic>;
  } catch (_) {
    return null;
  }
  switch (evento) {
    case 'token':
      return TokenEvent(json['delta'] as String? ?? '');
    case 'sources':
      final lista = (json['citations'] as List? ?? const [])
          .map((e) => CitationOut.fromJson(e))
          .whereType<CitationOut>()
          .toList();
      return SourcesEvent(lista);
    case 'done':
      return DoneEvent(
        messageId: json['message_id'] as String? ?? '',
        provider: json['provider'] as String? ?? '',
        model: json['model'] as String? ?? '',
      );
    case 'cancelled':
      return CancelledEvent(partialSaved: json['partial_saved'] as bool? ?? false);
    case 'error':
      return StreamErrorEvent(json['detail'] as String? ?? 'erro');
    default:
      return null;
  }
}
