import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/features/chat/chat_models.dart';

void main() {
  test('mensagem do usuário vira bolha de usuário sem citações', () {
    final m = ChatMessageOut(
      id: '1',
      conversationId: 'c',
      role: 'user',
      content: 'oi',
      createdAt: 'now',
    );
    final b = ChatBubble.fromMessage(m);
    expect(b.role, BubbleRole.user);
    expect(b.text, 'oi');
    expect(b.citations, isEmpty);
  });

  test('resposta do assistente preserva texto e citações tipadas', () {
    final resp = SendResponse(
      messageId: '2',
      text: 'a resposta',
      provider: 'ollama',
      model: 'qwen',
      tokensIn: 10,
      tokensOut: 20,
      citations: [CitationOut(kind: 'document', ordinal: 1, refId: 'x')],
    );
    final b = ChatBubble.fromResponse(resp);
    expect(b.role, BubbleRole.assistant);
    expect(b.text, 'a resposta');
    expect(b.citations.single.ordinal, 1);
    expect(b.citations.single.kind, 'document');
  });

  test('bolha de erro é local e sem citações', () {
    const b = ChatBubble.error('falhou');
    expect(b.role, BubbleRole.error);
    expect(b.citations, isEmpty);
  });

  CitationOut cite(int n) =>
      CitationOut(kind: 'document', ordinal: n, refId: 'r$n');

  test('usedCitations mostra só as fontes citadas com [n] no texto', () {
    final todas = [cite(1), cite(2), cite(3)];
    final usadas = citationsUsedIn('O total é 7.016,60 [2] na fatura.', todas);
    expect(usadas.map((c) => c.ordinal), [2]);
  });

  test('sem nenhuma referência, devolve todas as fontes consultadas', () {
    final todas = [cite(1), cite(2)];
    expect(citationsUsedIn('resposta sem citação', todas), todas);
  });

  test('números fora de colchetes não contam como citação', () {
    final todas = [cite(1), cite(2)];
    final usadas = citationsUsedIn('custa 1800 reais, ver [1]', todas);
    expect(usadas.map((c) => c.ordinal), [1]);
  });

  test('ChatBubble.usedCitations aplica o filtro sobre o próprio texto', () {
    final b = ChatBubble(
      BubbleRole.assistant,
      'vencimento em 10/04 [1]',
      citations: [cite(1), cite(2)],
    );
    expect(b.usedCitations.map((c) => c.ordinal), [1]);
  });
}
