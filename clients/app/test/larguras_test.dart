import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:lumbra_api/api.dart';
import 'package:lumbra_app/core/api.dart';
import 'package:lumbra_app/features/agents/agents_providers.dart';
import 'package:lumbra_app/features/agents/agents_screen.dart';
import 'package:lumbra_app/features/approvals/approvals_providers.dart';
import 'package:lumbra_app/features/approvals/approvals_screen.dart';
import 'package:lumbra_app/features/chat/chat_providers.dart';
import 'package:lumbra_app/features/chat/conversations_screen.dart';
import 'package:lumbra_app/features/devices/devices_screen.dart';
import 'package:lumbra_app/features/documents/documents_providers.dart';
import 'package:lumbra_app/features/documents/documents_screen.dart';
import 'package:lumbra_app/features/memories/memories_providers.dart';
import 'package:lumbra_app/features/memories/memories_screen.dart';
import 'package:lumbra_app/features/playbooks/playbooks_providers.dart';
import 'package:lumbra_app/features/playbooks/playbooks_screen.dart';
import 'package:lumbra_app/features/visao_geral/saude_providers.dart';
import 'package:lumbra_app/features/visao_geral/visao_geral_screen.dart';

/// Toda seção, em toda largura em que alguém realmente usa a Lumbra.
///
/// Este arquivo existe por um erro concreto: a Visão geral estourava 161px
/// a partir de ~530px de largura, e o teste dela não viu porque abria a
/// janela em 1000. **Um teste que escolhe a largura onde tudo cabe não está
/// testando layout.** Os testes de cada seção continuam cuidando do
/// CONTEÚDO; este cuida da única propriedade que nenhum deles verifica —
/// que o conteúdo CABE.
///
/// As larguras não são redondas por acaso:
///   360  — celular em pé, o menor alvo do P3
///   520  — a janela encostada na metade de uma tela pequena
///   800  — o padrão do `flutter test`, e onde o overflow apareceu
///   1043 — o espaço da seção na tela de 1263px do desenvolvimento
///   1400 — desktop largo, onde o painel de contexto também abre
///
/// O texto dos dados de teste é LONGO de propósito. Título curto cabe em
/// qualquer lugar; quem estoura uma `Row` é o nome de arquivo de 90
/// caracteres que existe no computador de quem usa.

const _larguras = <double>[360, 520, 800, 1043, 1400];

const _tituloLongo =
    'Contrato de prestação de serviços continuados — aditivo 3 (revisão '
    'final aprovada pelo jurídico em 14 de agosto)';
const _textoLongo =
    'Prefere que respostas técnicas venham com o raciocínio antes da '
    'conclusão, e não gosta de resumo executivo no topo quando o assunto '
    'ainda está sendo decidido.';

DocumentOut _documento() => DocumentOut(
  id: 'd1',
  uri: 'file:///C:/Users/brendon/Documentos/Trabalho/$_tituloLongo.pdf',
  title: _tituloLongo,
  source_: 'filesystem',
  processingState: 'indexed',
  version: 3,
);

MemoryItemOut _memoria() => MemoryItemOut(
  id: 'm1',
  userId: 'u',
  kind: 'semantic',
  content: _textoLongo,
  importance: 0.87,
  accessCount: 12,
  lastAccessedAt: '2026-08-01T10:00:00Z',
  createdAt: '2026-08-01T10:00:00Z',
);

PlaybookOut _procedimento() => PlaybookOut(
  id: 'p1',
  title: _tituloLongo,
  whenToUse: _textoLongo,
  origin: 'aprendido',
  createdAt: '2026-08-01T10:00:00Z',
  steps: const ['Abrir o contrato anterior e conferir o número do aditivo'],
  pitfalls: const ['Não confundir a revisão do jurídico com a do financeiro'],
  verification: 'O número do aditivo bate com o do contrato anterior',
  uses: 4,
);

ApprovalOut _aprovacao() => ApprovalOut(
  id: 'a1',
  action: 'documents.index',
  subject: _tituloLongo,
  riskLevel: 'high',
  reason: _textoLongo,
  createdAt: '2026-08-01T10:00:00Z',
);

AgentOut _agente() => AgentOut(
  id: 'ag1',
  name: 'documents-agent',
  version: '1.0.0',
  riskLevel: 'low',
  enabled: true,
  description: _textoLongo,
  capabilities: const [
    'documents.search',
    'documents.read',
    'documents.summarize',
  ],
);

DeviceResponse _dispositivo() => DeviceResponse(
  id: 'dev1',
  name: 'Notebook do trabalho (Windows 11, escritório)',
  platform: DevicePlatform.windows,
  state: DeviceState.active,
  publicKey: 'MCowBQYDK2VwAyEAq3f0Zx8Yb2N1cGVyIGxvbmdhIGNoYXZlIGRlIHRlc3Rl',
  createdAt: '2026-08-01T10:00:00Z',
  lastSeenAt: '2026-08-20T18:30:00Z',
  scopes: const ['chat.read', 'chat.write', 'documents.read'],
);

ConversationOut _conversa() => ConversationOut(
  id: 'c1',
  userId: 'u',
  title: _tituloLongo,
  createdAt: '2026-08-01T10:00:00Z',
  lastMessageAt: '2026-08-20T18:30:00Z',
);

HealthOut _saude() => HealthOut(
  version: '0.9.0',
  environment: 'development',
  ready: false,
  summary: ResumoOut(ok: 6, warn: 1, fail: 1),
  modules: const ['chat', 'documents', 'memory', 'playbooks', 'agents'],
  skills: 23,
  checks: [
    CheckOut(name: 'banco', status: 'ok', summary: 'Postgres respondendo.'),
    CheckOut(
      name: 'ollama',
      status: 'fail',
      summary: 'Ollama não respondeu em 127.0.0.1:11434.',
      detail: 'Tempo esgotado depois de 2 segundos sem resposta na porta.',
      fix: 'Abra um terminal e rode `ollama serve`, ou instale o Ollama '
          'em https://ollama.com/download e deixe-o iniciar com o sistema.',
    ),
  ],
);

List<Override> _dados() => [
  documentsProvider.overrideWith((ref) async => [_documento()]),
  memoriesProvider.overrideWith((ref) async => [_memoria()]),
  playbooksProvider.overrideWith((ref) async => [_procedimento()]),
  pendingApprovalsProvider.overrideWith((ref) async => [_aprovacao()]),
  agentsProvider.overrideWith((ref) async => [_agente()]),
  devicesListProvider.overrideWith((ref) async => [_dispositivo()]),
  conversationsProvider.overrideWith((ref) async => [_conversa()]),
  saudeProvider.overrideWith((ref) async => _saude()),
];

/// Cada seção, pelo nome com que aparece na barra lateral.
const _secoes = <String, Widget>{
  'Visão geral': VisaoGeralScreen(),
  'Conversas': ConversationsScreen(),
  'Memória': MemoriesScreen(),
  'Documentos': DocumentsScreen(),
  'Procedimentos': PlaybooksScreen(),
  'Aprovações': ApprovalsScreen(),
  'Agentes': AgentsScreen(),
  'Dispositivos': DevicesScreen(),
};

void main() {
  for (final entrada in _secoes.entries) {
    for (final largura in _larguras) {
      testWidgets('${entrada.key} cabe em ${largura.toInt()}px', (
        tester,
      ) async {
        // alta o bastante para que o que não couber seja culpa da LARGURA;
        // rolagem vertical é resposta legítima, transbordo horizontal não
        tester.view.physicalSize = Size(largura, 1600);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.reset);

        await tester.pumpWidget(
          ProviderScope(
            overrides: _dados(),
            child: MaterialApp(home: Scaffold(body: entrada.value)),
          ),
        );
        await tester.pumpAndSettle();

        // a seção precisa ter DESENHADO alguma coisa; um erro de layout que
        // impedisse a montagem passaria como "não transbordou"
        expect(find.byType(Text), findsWidgets);

        // De propósito NÃO chamamos `takeException` aqui. Ela devolve só o
        // resumo do erro ("transbordou 28px") e descarta o diagnóstico do
        // framework — que é justamente a parte que diz QUAL widget e em que
        // arquivo. Deixado pendente, o próprio flutter_test derruba o teste
        // no fim e imprime a cadeia de criação inteira. Uma falha que não
        // diz onde é meia falha.
      });
    }
  }
}
