import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/session.dart';
import '../approvals/approvals_providers.dart';
import '../approvals/approvals_screen.dart';
import '../chat/conversations_screen.dart';
import '../devices/devices_screen.dart';
import '../playbooks/playbooks_screen.dart';

/// A moldura do app no desktop: uma barra lateral de seções.
///
/// Antes, as seções eram ícones espremidos na barra de topo e abriam
/// empilhadas — o padrão de celular esticado numa tela de 1500px. Numa
/// ferramenta de uso contínuo isso cobra dois preços: você nunca sabe onde
/// está, e voltar exige desfazer a pilha.
///
/// Com a barra lateral, as seções são LUGARES: sempre visíveis, sempre no
/// mesmo canto, e trocar entre elas não perde o que estava aberto (o
/// `IndexedStack` mantém cada uma viva, com rolagem e rascunho intactos).
class HomeShell extends ConsumerStatefulWidget {
  const HomeShell({super.key});

  @override
  ConsumerState<HomeShell> createState() => _HomeShellState();
}

class _HomeShellState extends ConsumerState<HomeShell> {
  int _secao = 0;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final pendentes = ref.watch(pendingApprovalsProvider).valueOrNull?.length ?? 0;

    return Scaffold(
      body: Row(
        children: [
          NavigationRail(
            selectedIndex: _secao,
            onDestinationSelected: (i) => setState(() => _secao = i),
            labelType: NavigationRailLabelType.all,
            backgroundColor: cores.surface,
            groupAlignment: -1,
            leading: const Padding(
              padding: EdgeInsets.symmetric(vertical: 16),
              child: Icon(Icons.auto_awesome, size: 22),
            ),
            destinations: [
              const NavigationRailDestination(
                icon: Icon(Icons.forum_outlined),
                selectedIcon: Icon(Icons.forum),
                label: Text('Conversas'),
              ),
              NavigationRailDestination(
                // o selo vive aqui e não numa tela: pedido que ninguém vê
                // equivale a pedido negado
                icon: pendentes == 0
                    ? const Icon(Icons.inbox_outlined)
                    : Badge.count(count: pendentes, child: const Icon(Icons.inbox)),
                selectedIcon: const Icon(Icons.inbox),
                label: const Text('Aprovações'),
              ),
              const NavigationRailDestination(
                icon: Icon(Icons.menu_book_outlined),
                selectedIcon: Icon(Icons.menu_book),
                label: Text('Procedimentos'),
              ),
              const NavigationRailDestination(
                icon: Icon(Icons.devices_outlined),
                selectedIcon: Icon(Icons.devices),
                label: Text('Dispositivos'),
              ),
            ],
            trailing: Expanded(
              child: Align(
                alignment: Alignment.bottomCenter,
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 16),
                  child: IconButton(
                    tooltip: 'Sair',
                    icon: const Icon(Icons.logout),
                    onPressed: () =>
                        ref.read(sessionControllerProvider.notifier).logout(),
                  ),
                ),
              ),
            ),
          ),
          VerticalDivider(width: 1, color: cores.outline),
          // IndexedStack e não troca de widget: sair de Conversas e voltar
          // não pode perder a rolagem nem recarregar tudo de novo
          Expanded(
            child: IndexedStack(
              index: _secao,
              children: const [
                ConversationsScreen(),
                ApprovalsScreen(),
                PlaybooksScreen(),
                DevicesScreen(),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
