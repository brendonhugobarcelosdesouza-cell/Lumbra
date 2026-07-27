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
}
