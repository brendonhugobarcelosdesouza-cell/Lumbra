import 'package:lumbra_api/api.dart';

/// Papel de uma bolha na conversa. `error` é local (falha ao responder),
/// não vem do Nó.
enum BubbleRole { user, assistant, error }

/// Uma bolha do chat, unificando o que vem do histórico (ChatMessageOut) e
/// da resposta de envio (SendResponse) num único modelo de UI. As citações
/// são tipadas pelo contrato (CitationOut) — nada de mapa solto.
class ChatBubble {
  const ChatBubble(
    this.role,
    this.text, {
    this.citations = const [],
    this.quando,
    this.modelo,
  });

  ChatBubble.user(this.text)
    : role = BubbleRole.user,
      citations = const [],
      quando = DateTime.now(),
      modelo = null;

  const ChatBubble.error(this.text)
    : role = BubbleRole.error,
      citations = const [],
      quando = null,
      modelo = null;

  ChatBubble.fromMessage(ChatMessageOut m)
    : role = m.role == 'user' ? BubbleRole.user : BubbleRole.assistant,
      text = m.content,
      citations = m.citations,
      quando = DateTime.tryParse(m.createdAt)?.toLocal(),
      modelo = m.model;

  ChatBubble.fromResponse(SendResponse r)
    : role = BubbleRole.assistant,
      text = r.text,
      citations = r.citations,
      quando = DateTime.now(),
      modelo = r.model;

  final BubbleRole role;
  final String text;
  final List<CitationOut> citations;

  /// Quando a mensagem existiu. Vem do Nó no histórico (`created_at`) e do
  /// relógio local no que acabou de ser enviado. `null` só nos erros, que
  /// são locais e não têm hora que importe.
  final DateTime? quando;

  /// Que modelo escreveu esta resposta. Vem do histórico e do evento `done`.
  /// Mostrar isto por mensagem, e não só no topo, importa porque o modelo
  /// pode ter mudado no meio da conversa — e a resposta antiga continua
  /// tendo sido escrita pelo antigo.
  final String? modelo;

  /// As citações que a resposta REALMENTE usou: aquelas cujo número `[n]`
  /// aparece no texto. O RAG traz várias fontes ao contexto, mas o modelo
  /// costuma citar só algumas — mostrar todas como se tivessem sido usadas
  /// engana. Se o modelo não citou ninguém, devolve todas (as fontes
  /// consultadas), para não esconder a proveniência.
  List<CitationOut> get usedCitations => citationsUsedIn(text, citations);
}

final _refCitada = RegExp(r'\[(\d+)\]');

/// Filtra as citações às referenciadas por `[n]` no texto. Exposto à parte
/// para ser testável sem widget.
List<CitationOut> citationsUsedIn(String text, List<CitationOut> all) {
  final usados = _refCitada
      .allMatches(text)
      .map((m) => int.parse(m.group(1)!))
      .toSet();
  if (usados.isEmpty) return all;
  return all.where((c) => usados.contains(c.ordinal)).toList();
}
