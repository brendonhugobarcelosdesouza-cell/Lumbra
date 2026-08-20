import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/features/chat/coluna_de_conversas.dart';

/// O agrupamento por data é o que transforma "Conversa, Conversa, Conversa"
/// numa lista onde dá para achar algo. Quem localiza a pessoa é o TEMPO
/// ("aquilo foi ontem"), não a posição na lista.

final _agora = DateTime(2026, 8, 5, 14, 30);

ConversationOut _conversa(String id, DateTime? ultima, {DateTime? criada}) =>
    ConversationOut(
      id: id,
      userId: 'u',
      createdAt: (criada ?? _agora).toIso8601String(),
      lastMessageAt: ultima?.toIso8601String(),
      modelPolicy: const {},
    );

void main() {
  test('separa hoje, ontem, semana, mês e o resto', () {
    final grupos = agruparPorData([
      _conversa('a', _agora.subtract(const Duration(hours: 2))),
      _conversa('b', _agora.subtract(const Duration(days: 1))),
      _conversa('c', _agora.subtract(const Duration(days: 3))),
      _conversa('d', _agora.subtract(const Duration(days: 12))),
      _conversa('e', _agora.subtract(const Duration(days: 200))),
    ], agora: _agora);

    expect(grupos['Hoje']!.map((c) => c.id), ['a']);
    expect(grupos['Ontem']!.map((c) => c.id), ['b']);
    expect(grupos['Últimos 7 dias']!.map((c) => c.id), ['c']);
    expect(grupos['Últimos 30 dias']!.map((c) => c.id), ['d']);
    expect(grupos['Mais antigas']!.map((c) => c.id), ['e']);
  });

  test('conversa sem mensagem cai na data de criação', () {
    // conversa recém-aberta e ainda vazia não pode sumir da lista
    final grupos = agruparPorData([
      _conversa('nova', null, criada: _agora),
    ], agora: _agora);
    expect(grupos['Hoje']!.map((c) => c.id), ['nova']);
  });

  test('data ilegível não derruba a lista', () {
    final quebrada = ConversationOut(
      id: 'x',
      userId: 'u',
      createdAt: 'nao-e-uma-data',
      modelPolicy: const {},
    );
    final grupos = agruparPorData([quebrada], agora: _agora);
    expect(grupos['Sem data']!.map((c) => c.id), ['x']);
  });

  test('a ordem dos grupos vai do recente ao antigo', () {
    // a lista renderiza nessa ordem; se alguém inventar um rótulo novo sem
    // colocá-lo aqui, ele simplesmente não aparece — este teste é o lembrete
    expect(ordemDosGrupos.first, 'Hoje');
    expect(ordemDosGrupos.last, 'Sem data');
    final grupos = agruparPorData([
      _conversa('a', _agora),
      _conversa('b', _agora.subtract(const Duration(days: 400))),
    ], agora: _agora);
    for (final rotulo in grupos.keys) {
      expect(ordemDosGrupos, contains(rotulo));
    }
  });
}
