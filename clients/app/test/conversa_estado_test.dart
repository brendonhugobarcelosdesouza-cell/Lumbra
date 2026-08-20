import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/core/api.dart';
import 'package:lumbra_app/core/session.dart';
import 'package:lumbra_app/features/chat/chat_models.dart';
import 'package:lumbra_app/features/chat/chat_providers.dart';
import 'package:lumbra_app/features/chat/chat_stream.dart';
import 'package:lumbra_app/features/chat/conversa_estado.dart';

import 'session_test.dart';

/// O caminho do stream é o mais frágil do app: é onde mora a renovação de
/// token no meio da resposta, e é onde uma falha se apresenta como sucesso —
/// a tela mostra texto normalmente e o que some são as fontes, ou a
/// retentativa. Até aqui ele só estava coberto no nível do parser
/// (`chat_stream_test.dart`), nunca no de quem conduz a conversa.
///
/// Estes testes existem porque o R1 desmontou esse caminho para tirá-lo de
/// dentro do widget. Foram escritos ANTES da mudança, contra o comportamento
/// que já funcionava.

class _ChatApiVazia extends ChatApi {
  @override
  Future<HistoryResponse?> historyApiV1ChatConversationsConversationIdMessagesGet(
    String conversationId, {
    int? limit,
  }) async => HistoryResponse(messages: []);
}

class _ChatApiQuebrada extends ChatApi {
  @override
  Future<HistoryResponse?> historyApiV1ChatConversationsConversationIdMessagesGet(
    String conversationId, {
    int? limit,
  }) async => throw Exception('sem rede');
}

/// Leitor de stream de mentira: entrega os roteiros na ordem em que for
/// chamado. Um roteiro por chamada — é assim que se testa a retentativa.
class _Roteirista {
  _Roteirista(this.roteiros);

  final List<List<ChatStreamEvent>> roteiros;
  var chamadas = 0;
  final conteudos = <String>[];

  LeitorDeStream get leitor =>
      ({
        required String baseUrl,
        required String? token,
        required String conversationId,
        required String content,
      }) {
        conteudos.add(content);
        final i = chamadas++;
        final roteiro = i < roteiros.length ? roteiros[i] : const <ChatStreamEvent>[];
        return Stream.fromIterable(roteiro);
      };
}

ProviderContainer _montar(
  _Roteirista roteirista, {
  ChatApi? api,
  Session? sessao = const Session(accessToken: 'abc', refreshToken: 'ref'),
}) {
  final container = ProviderContainer(
    overrides: [
      chatApiProvider.overrideWithValue(api ?? _ChatApiVazia()),
      leitorDeStreamProvider.overrideWithValue(roteirista.leitor),
      tokenStorageProvider.overrideWithValue(FakeTokenStorage(sessao)),
      authApiProvider.overrideWithValue(FakeAuthApi()),
    ],
  );
  addTearDown(container.dispose);
  _segurar(container);
  return container;
}

/// Mantem o provider VIVO durante o teste.
///
/// `conversaProvider` e autoDispose: sem ninguem escutando, cada `read`
/// constroi, devolve e joga fora. O teste entao lia o estado inicial de uma
/// instancia recem-nascida e concluia que nada tinha acontecido — com o
/// agravante de que o envio REALMENTE tinha rodado, so que noutra instancia.
///
/// No app quem segura e o widget que assiste. Aqui precisa ser explicito.
void _segurar(ProviderContainer container) {
  final assinatura = container.listen(
    conversaProvider(conversa),
    (_, __) {},
    fireImmediately: true,
  );
  addTearDown(assinatura.close);
}

const conversa = 'conv-1';

CitationOut _fonte(int n, String titulo) => CitationOut(
  kind: 'document',
  ordinal: n,
  refId: 'doc-$n',
  title: titulo,
  score: 0.9,
);

void main() {
  Future<EstadoDaConversa> assentar(ProviderContainer c) async {
    // o histórico carrega fora do build (unawaited); sem ceder o loop, o
    // teste leria o estado inicial e passaria por engano
    await c.read(sessionControllerProvider.future);
    await pumpEventQueue();
    return c.read(conversaProvider(conversa));
  }

  test('carrega o histórico e sai do estado de carregando', () async {
    final c = _montar(_Roteirista(const []));
    final estado = await assentar(c);
    expect(estado.carregando, isFalse);
    expect(estado.erroDeCarga, isNull);
  });

  test('histórico que falha vira erro, não tela em branco eterna', () async {
    final c = _montar(_Roteirista(const []), api: _ChatApiQuebrada());
    final estado = await assentar(c);
    expect(estado.carregando, isFalse);
    expect(estado.erroDeCarga, contains('sem rede'));
  });

  test('os tokens se acumulam e viram uma bolha ao concluir', () async {
    final roteirista = _Roteirista([
      const [
        TokenEvent('Oi'),
        TokenEvent(', Brendon'),
        DoneEvent(
          messageId: 'm1',
          provider: 'ollama',
          model: 'qwen2.5:14b',
          tokensIn: 120,
          tokensOut: 45,
        ),
      ],
    ]);
    final c = _montar(roteirista);
    await assentar(c);

    c.read(conversaProvider(conversa).notifier).enviar('oi');
    await pumpEventQueue();

    final estado = c.read(conversaProvider(conversa));
    expect(estado.enviando, isFalse);
    expect(estado.bolhas.map((b) => b.text), ['oi', 'Oi, Brendon']);
    expect(estado.bolhas.last.role, BubbleRole.assistant);
  });

  test('o custo da resposta chega ao estado (o `usage` do evento done)', () async {
    // este dado SEMPRE atravessou o fio e morria no parser: o Nó manda
    // usage.in/usage.out desde o primeiro dia do streaming
    final roteirista = _Roteirista([
      const [
        TokenEvent('resposta'),
        DoneEvent(
          messageId: 'm1',
          provider: 'ollama',
          model: 'qwen2.5:14b',
          tokensIn: 120,
          tokensOut: 45,
        ),
      ],
    ]);
    final c = _montar(roteirista);
    await assentar(c);

    c.read(conversaProvider(conversa).notifier).enviar('oi');
    await pumpEventQueue();

    final resposta = c.read(conversaProvider(conversa)).ultimaResposta;
    expect(resposta?.model, 'qwen2.5:14b');
    expect(resposta?.tokensIn, 120);
    expect(resposta?.tokensOut, 45);
    expect(resposta?.duracao, isNotNull);
  });

  test('as fontes chegam antes do texto e ficam na bolha final', () async {
    final roteirista = _Roteirista([
      [
        SourcesEvent([_fonte(1, 'Contrato.pdf'), _fonte(2, 'Fatura.pdf')]),
        const TokenEvent('Segundo o [1], sim.'),
        const DoneEvent(messageId: 'm1', provider: 'ollama', model: 'q'),
      ],
    ]);
    final c = _montar(roteirista);
    await assentar(c);

    c.read(conversaProvider(conversa).notifier).enviar('pergunta');
    await pumpEventQueue();

    final ultima = c.read(conversaProvider(conversa)).bolhas.last;
    expect(ultima.citations, hasLength(2));
    // só a citada aparece: trazer as duas fingiria que ambas foram usadas
    expect(ultima.usedCitations.map((f) => f.ordinal), [1]);
  });

  test('401 no meio da resposta renova e re-tenta UMA vez', () async {
    final roteirista = _Roteirista([
      const [StreamErrorEvent('HTTP 401')],
      const [
        TokenEvent('agora vai'),
        DoneEvent(messageId: 'm1', provider: 'ollama', model: 'q'),
      ],
    ]);
    final c = _montar(roteirista);
    await assentar(c);

    c.read(conversaProvider(conversa).notifier).enviar('oi');
    await pumpEventQueue();

    final estado = c.read(conversaProvider(conversa));
    expect(roteirista.chamadas, 2, reason: 'renovou e tentou de novo');
    expect(roteirista.conteudos, ['oi', 'oi'], reason: 'a MESMA pergunta');
    expect(estado.bolhas.map((b) => b.text), ['oi', 'agora vai']);
    // e nenhuma bolha de erro: o usuário não deve saber que houve um 401
    expect(estado.bolhas.any((b) => b.role == BubbleRole.error), isFalse);
  });

  test('401 duas vezes seguidas desiste e mostra o erro', () async {
    // sem este limite, um token irrecuperável viraria laço infinito de
    // renovação — e o sintoma seria o app "pensando" para sempre
    final roteirista = _Roteirista([
      const [StreamErrorEvent('HTTP 401')],
      const [StreamErrorEvent('HTTP 401')],
    ]);
    final c = _montar(roteirista);
    await assentar(c);

    c.read(conversaProvider(conversa).notifier).enviar('oi');
    await pumpEventQueue();

    expect(roteirista.chamadas, 2);
    final estado = c.read(conversaProvider(conversa));
    expect(estado.enviando, isFalse);
    expect(estado.bolhas.last.role, BubbleRole.error);
  });

  test('erro que não é 401 vira bolha de erro na hora', () async {
    final roteirista = _Roteirista([
      const [StreamErrorEvent('falha ao gerar a resposta')],
    ]);
    final c = _montar(roteirista);
    await assentar(c);

    c.read(conversaProvider(conversa).notifier).enviar('oi');
    await pumpEventQueue();

    final estado = c.read(conversaProvider(conversa));
    expect(roteirista.chamadas, 1);
    expect(estado.bolhas.last.role, BubbleRole.error);
    expect(estado.bolhas.last.text, 'falha ao gerar a resposta');
  });

  test('parar guarda o que já tinha chegado', () async {
    // o parcial não pode ser jogado fora: metade de uma resposta longa ainda
    // é a resposta que a pessoa pediu
    final controle = StreamController<ChatStreamEvent>();
    addTearDown(controle.close);
    Stream<ChatStreamEvent> leitor({
      required String baseUrl,
      required String? token,
      required String conversationId,
      required String content,
    }) => controle.stream;

    final c = ProviderContainer(
      overrides: [
        chatApiProvider.overrideWithValue(_ChatApiVazia()),
        leitorDeStreamProvider.overrideWithValue(leitor),
        tokenStorageProvider.overrideWithValue(
          FakeTokenStorage(const Session(accessToken: 'a', refreshToken: 'r')),
        ),
      ],
    );
    addTearDown(c.dispose);
    _segurar(c);
    await pumpEventQueue();

    final notifier = c.read(conversaProvider(conversa).notifier);
    notifier.enviar('escreva um texto longo');
    controle.add(const TokenEvent('Era uma vez'));
    await pumpEventQueue();
    expect(c.read(conversaProvider(conversa)).enviando, isTrue);

    notifier.parar();
    final estado = c.read(conversaProvider(conversa));
    expect(estado.enviando, isFalse);
    expect(estado.bolhas.last.text, 'Era uma vez');
  });

  test('enviar duas vezes seguidas não abre dois streams', () async {
    final controle = StreamController<ChatStreamEvent>();
    addTearDown(controle.close);
    var aberturas = 0;
    Stream<ChatStreamEvent> leitor({
      required String baseUrl,
      required String? token,
      required String conversationId,
      required String content,
    }) {
      aberturas++;
      return controle.stream;
    }

    final c = ProviderContainer(
      overrides: [
        chatApiProvider.overrideWithValue(_ChatApiVazia()),
        leitorDeStreamProvider.overrideWithValue(leitor),
        tokenStorageProvider.overrideWithValue(
          FakeTokenStorage(const Session(accessToken: 'a', refreshToken: 'r')),
        ),
      ],
    );
    addTearDown(c.dispose);
    _segurar(c);
    await pumpEventQueue();

    final notifier = c.read(conversaProvider(conversa).notifier);
    notifier.enviar('primeira');
    notifier.enviar('segunda');
    expect(aberturas, 1);
  });

  test('a conversa ganha título na primeira pergunta', () async {
    final c = _montar(_Roteirista(const []));
    await assentar(c);
    expect(c.read(conversaProvider(conversa)).titulo, isNull);

    c.read(conversaProvider(conversa).notifier).enviar('  Plano   financeiro  ');
    expect(c.read(conversaProvider(conversa)).titulo, 'Plano financeiro');
  });

  test('título vindo da lista não sobrescreve o que já existe', () async {
    final c = _montar(_Roteirista(const []));
    await assentar(c);
    final notifier = c.read(conversaProvider(conversa).notifier);

    notifier.adotarTitulo('Da lista');
    expect(c.read(conversaProvider(conversa)).titulo, 'Da lista');
    notifier.adotarTitulo('Outro qualquer');
    expect(c.read(conversaProvider(conversa)).titulo, 'Da lista');
  });
}
