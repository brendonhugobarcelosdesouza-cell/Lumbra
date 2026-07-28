import 'package:lumbra_api/api.dart';

/// Papel de uma bolha na conversa. `error` é local (falha ao responder),
/// não vem do Nó.
enum BubbleRole { user, assistant, error }

/// Uma bolha do chat, unificando o que vem do histórico (ChatMessageOut) e
/// da resposta de envio (SendResponse) num único modelo de UI. As citações
/// são tipadas pelo contrato (CitationOut) — nada de mapa solto.
class ChatBubble {
  const ChatBubble(this.role, this.text, {this.citations = const []});

  const ChatBubble.user(this.text) : role = BubbleRole.user, citations = const [];

  const ChatBubble.error(this.text)
    : role = BubbleRole.error,
      citations = const [];

  ChatBubble.fromMessage(ChatMessageOut m)
    : role = m.role == 'user' ? BubbleRole.user : BubbleRole.assistant,
      text = m.content,
      citations = m.citations;

  ChatBubble.fromResponse(SendResponse r)
    : role = BubbleRole.assistant,
      text = r.text,
      citations = r.citations;

  final BubbleRole role;
  final String text;
  final List<CitationOut> citations;

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
