import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/node_status.dart';
import '../../core/session.dart';
import '../agents/agents_screen.dart';
import '../approvals/approvals_providers.dart';
import '../approvals/approvals_screen.dart';
import '../chat/conversations_screen.dart';
import '../devices/devices_screen.dart';
import '../documents/documents_screen.dart';
import '../memories/memories_screen.dart';
import '../playbooks/playbooks_screen.dart';
import 'barra_lateral.dart';

/// A moldura do app no desktop.
///
/// Antes, as seções eram ícones espremidos na barra de topo e abriam
/// empilhadas — o padrão de celular esticado numa tela de 1500px. Numa
/// ferramenta de uso contínuo isso cobra dois preços: você nunca sabe onde
/// está, e voltar exige desfazer a pilha.
///
/// Com a barra lateral, as seções são LUGARES: sempre visíveis, sempre no
/// mesmo canto, e trocar entre elas não perde o que estava aberto (o
/// `IndexedStack` mantém cada uma viva, com rolagem e rascunho intactos).
///
/// Os GRUPOS vieram depois, quando a lista chapada chegou a dez itens: dez
/// destinos sem hierarquia se leem inteiros toda vez. "Meu sistema" é o que
/// a Lumbra guarda de você; "Controle" é como você manda nela.
class HomeShell extends ConsumerStatefulWidget {
  const HomeShell({super.key});

  @override
  ConsumerState<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends ConsumerState<HomeShell> {
  static const _conversas = 'Conversas';
  static const _memoria = 'Memória';
  static const _documentos = 'Documentos';
  static const _procedimentos = 'Procedimentos';
  static const _aprovacoes = 'Aprovações';
  static const _agentes = 'Agentes';
  static const _dispositivos = 'Dispositivos';

  /// A ordem aqui casa com a do `IndexedStack` — as duas listas juntas
  /// porque separá-las seria convidar a desalinhá-las.
  static const _ordem = [
    _conversas,
    _memoria,
    _documentos,
    _procedimentos,
    _aprovacoes,
    _agentes,
    _dispositivos,
  ];

  /// Dois selos, duas distâncias. `em breve` é o que já está na fila do P2 e
  /// chega em dias; `P5` é um épico que nem começou. Um selo só para os dois
  /// casos daria a "Agenda" a mesma promessa de proximidade que
  /// "Configurações" — e seria a promessa errada.
  static const _emBreve = 'em breve';

  static final _grupos = <String, List<Secao>>{
    '': [
      const Secao(
        nome: 'Visão geral',
        icone: Icons.auto_awesome_outlined,
        iconeAtivo: Icons.auto_awesome,
        selo: _emBreve,
      ),
    ],
    'Meu sistema': [
      const Secao(
        nome: _conversas,
        icone: Icons.forum_outlined,
        iconeAtivo: Icons.forum,
      ),
      const Secao(
        nome: _memoria,
        icone: Icons.psychology_outlined,
        iconeAtivo: Icons.psychology,
      ),
      const Secao(
        nome: _documentos,
        icone: Icons.folder_outlined,
        iconeAtivo: Icons.folder,
      ),
      const Secao(
        nome: _procedimentos,
        icone: Icons.menu_book_outlined,
        iconeAtivo: Icons.menu_book,
      ),
      // Agenda e Tarefas ainda NÃO EXISTEM — são o P5. Aparecem apagadas,
      // com o selo do épico, e não abrem nada. Ver a justificativa em
      // `Secao.selo`: o meio-termo (listar como se funcionasse e abrir tela
      // vazia) é que seria desonesto.
      const Secao(
        nome: 'Agenda',
        icone: Icons.event_outlined,
        iconeAtivo: Icons.event,
        selo: 'P5',
      ),
      const Secao(
        nome: 'Tarefas',
        icone: Icons.check_circle_outline,
        iconeAtivo: Icons.check_circle,
        selo: 'P5',
      ),
    ],
    'Controle': [
      const Secao(
        nome: _aprovacoes,
        icone: Icons.verified_user_outlined,
        iconeAtivo: Icons.verified_user,
      ),
      const Secao(
        nome: _agentes,
        icone: Icons.smart_toy_outlined,
        iconeAtivo: Icons.smart_toy,
      ),
      const Secao(
        nome: _dispositivos,
        icone: Icons.devices_outlined,
        iconeAtivo: Icons.devices,
      ),
    ],
  };

  static const _fixos = [
    Secao(
      nome: 'Configurações',
      icone: Icons.settings_outlined,
      iconeAtivo: Icons.settings,
      selo: _emBreve,
    ),
  ];

  String _secao = _conversas;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final pendentes = ref.watch(pendingApprovalsProvider).valueOrNull?.length ?? 0;

    return Scaffold(
      body: Row(
        children: [
          BarraLateral(
            grupos: _grupos,
            selecionada: _secao,
            selos: {_aprovacoes: pendentes},
            fixos: _fixos,
            aoSelecionar: (nome) => setState(() => _secao = nome),
            rodape: const _Rodape(),
          ),
          VerticalDivider(width: 1, color: cores.outlineVariant),
          // IndexedStack e não troca de widget: sair de Conversas e voltar
          // não pode perder a rolagem nem recarregar tudo de novo
          Expanded(
            child: IndexedStack(
              index: _ordem.indexOf(_secao),
              children: const [
                ConversationsScreen(),
                MemoriesScreen(),
                DocumentsScreen(),
                PlaybooksScreen(),
                ApprovalsScreen(),
                AgentsScreen(),
                DevicesScreen(),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

/// O pé da barra: quem está usando, e onde a Lumbra está rodando.
///
/// As duas informações moram juntas de propósito. A promessa central do
/// produto é que os dados não saem do computador, e uma promessa que só
/// aparece no material de divulgação não é verificável. Aqui ela fica no
/// canto da tela, o tempo todo, ao lado do estado real do Nó — se ele cair,
/// o mesmo lugar que afirmava "local" passa a dizer "fora do ar".
///
/// O que NÃO fazemos: inventar plano, foto ou nome completo. O Nó não
/// devolve perfil, então mostramos o que sabemos — o e-mail com que se
/// entrou — e nada além disso.
class _Rodape extends ConsumerWidget {
  const _Rodape();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cores = Theme.of(context).colorScheme;
    final textos = Theme.of(context).textTheme;
    final email = ref.watch(sessionControllerProvider).valueOrNull?.email;
    final no = ref.watch(nodeStateProvider);

    return PopupMenuButton<String>(
      tooltip: '',
      offset: const Offset(0, -8),
      position: PopupMenuPosition.over,
      onSelected: (_) =>
          ref.read(sessionControllerProvider.notifier).logout(),
      itemBuilder: (_) => const [
        PopupMenuItem(
          value: 'sair',
          height: 40,
          child: Row(
            children: [
              Icon(Icons.logout, size: 16),
              SizedBox(width: 10),
              Text('Sair', style: TextStyle(fontSize: 13)),
            ],
          ),
        ),
      ],
      child: Padding(
        padding: const EdgeInsets.fromLTRB(14, 12, 12, 14),
        child: Row(
          children: [
            _Inicial(email),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    // sessão antiga (guardada antes deste campo existir) não
                    // tem e-mail: dizer o que se sabe em vez de mentir um nome
                    email ?? 'Sessão ativa',
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: textos.bodyMedium?.copyWith(
                      fontSize: 12.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  const SizedBox(height: 2),
                  _EstadoDoNo(no),
                ],
              ),
            ),
            Icon(
              Icons.unfold_more,
              size: 15,
              color: cores.onSurfaceVariant,
            ),
          ],
        ),
      ),
    );
  }
}

class _Inicial extends StatelessWidget {
  const _Inicial(this.email);

  final String? email;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final letra = (email?.trim().isNotEmpty ?? false)
        ? email!.trim()[0].toUpperCase()
        : '?';
    return Container(
      width: 26,
      height: 26,
      alignment: Alignment.center,
      decoration: BoxDecoration(
        color: cores.surfaceContainerHigh,
        shape: BoxShape.circle,
      ),
      child: Text(
        letra,
        style: TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w700,
          color: cores.onSurfaceVariant,
        ),
      ),
    );
  }
}

class _EstadoDoNo extends StatelessWidget {
  const _EstadoDoNo(this.estado);

  final NodeState estado;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    // verde e âmbar vindos da paleta, vermelho do esquema: o ponto é
    // semáforo, e semáforo que muda de tom entre temas deixa de ser lido
    final (texto, cor) = switch (estado) {
      NodeState.noAr => ('Nó local', const Color(0xFF4CAF7D)),
      NodeState.verificando => ('Verificando o Nó', cores.onSurfaceVariant),
      NodeState.subindo => ('Iniciando o Nó', const Color(0xFFD99A2B)),
      NodeState.demorandoDemais => ('Nó demorando', const Color(0xFFD99A2B)),
      NodeState.foraDoAr => ('Nó fora do ar', cores.error),
    };

    return Row(
      children: [
        Container(
          width: 6,
          height: 6,
          decoration: BoxDecoration(color: cor, shape: BoxShape.circle),
        ),
        const SizedBox(width: 6),
        Flexible(
          child: Text(
            texto,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: TextStyle(fontSize: 11, color: cores.onSurfaceVariant),
          ),
        ),
      ],
    );
  }
}
