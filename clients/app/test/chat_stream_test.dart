import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:lumbra_app/features/chat/chat_stream.dart';

void main() {
  test('parseia sources, tokens e done na ordem', () async {
    final sse = [
      'event: sources\n'
          'data: {"citations":[{"ordinal":1,"kind":"document","ref_id":"x"}]}\n\n',
      'event: token\ndata: {"delta":"Oi"}\n\n',
      'event: token\ndata: {"delta":" mundo"}\n\n',
      'event: done\n'
          'data: {"message_id":"m","provider":"ollama","model":"qwen","usage":{"in":1,"out":2}}\n\n',
    ].join();

    final client = MockClient.streaming((req, body) async {
      return http.StreamedResponse(Stream.value(utf8.encode(sse)), 200);
    });

    final eventos = await streamChat(
      baseUrl: 'http://no',
      token: 't',
      conversationId: 'c',
      content: 'oi',
      client: client,
    ).toList();

    expect(eventos.length, 4);
    expect(eventos[0], isA<SourcesEvent>());
    expect((eventos[0] as SourcesEvent).citations.single.ordinal, 1);
    expect((eventos[1] as TokenEvent).delta, 'Oi');
    expect((eventos[2] as TokenEvent).delta, ' mundo');
    expect((eventos[3] as DoneEvent).provider, 'ollama');
  });

  test('erro HTTP vira StreamErrorEvent', () async {
    final client = MockClient.streaming((req, body) async {
      return http.StreamedResponse(Stream<List<int>>.value(const []), 401);
    });

    final eventos = await streamChat(
      baseUrl: 'http://no',
      token: null,
      conversationId: 'c',
      content: 'oi',
      client: client,
    ).toList();

    expect(eventos.single, isA<StreamErrorEvent>());
  });

  test('evento de erro no stream vira StreamErrorEvent', () async {
    const sse = 'event: error\ndata: {"detail":"provedor caiu"}\n\n';
    final client = MockClient.streaming((req, body) async {
      return http.StreamedResponse(Stream.value(utf8.encode(sse)), 200);
    });

    final eventos = await streamChat(
      baseUrl: 'http://no',
      token: 't',
      conversationId: 'c',
      content: 'oi',
      client: client,
    ).toList();

    expect(eventos.single, isA<StreamErrorEvent>());
    expect((eventos.single as StreamErrorEvent).detail, 'provedor caiu');
  });
}
