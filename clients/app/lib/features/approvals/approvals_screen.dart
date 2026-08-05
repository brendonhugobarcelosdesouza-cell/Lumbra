import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import 'approvals_providers.dart';

/// A caixa de aprovações (L2.0/L2) — onde o Human-in-the-Loop deixa de ser
/// infraestrutura e vira uma pergunta.
///
/// Mostra o pedido INTEIRO, não só o nome da ação: o usuário decide vendo o
/// que será feito, não confiando que a plataforma escolheu bem. É esta tela
/// que torna seguro a Lumbra propor procedimentos sozinha — sem ela, aprender
/// e escrever em silêncio seriam a mesma coisa.
class ApprovalsScreen extends ConsumerWidget {
  const ApprovalsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final pendentes = ref.watch(pendingApprovalsProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Aprovações')),
      body: pendentes.when(
        loading: () => const Center(child: CircularProgressIndicator()),
        error: (erro, _) => Center(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Text(
              'Não foi possível carregar os pedidos.\n$erro',
              textAlign: TextAlign.center,
            ),
          ),
        ),
        data: (lista) => lista.isEmpty
            ? const Center(child: Text('Nada aguardando sua decisão.'))
            : ListView(
                padding: const EdgeInsets.all(12),
                children: [
                  for (final pedido in lista)
                    _CartaoPedido(pedido: pedido),
                ],
              ),
      ),
    );
  }
}

class _CartaoPedido extends ConsumerWidget {
  const _CartaoPedido({required this.pedido});

  final ApprovalOut pedido;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    _titulo(pedido),
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                Chip(
                  label: Text(pedido.riskLevel),
                  visualDensity: VisualDensity.compact,
                ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              pedido.action,
              style: Theme.of(context).textTheme.bodySmall,
            ),
            // a razao so aparece de novo se nao virou o titulo
            if (pedido.reason.isNotEmpty && _titulo(pedido) != pedido.reason) ...[
              const SizedBox(height: 8),
              Text(pedido.reason),
            ],
            // os passos propostos: é o que o usuário está aprovando de fato
            for (final passo in _passos(pedido))
              Padding(
                padding: const EdgeInsets.only(top: 4, left: 8),
                child: Text('• $passo'),
              ),
            const SizedBox(height: 12),
            Row(
              mainAxisAlignment: MainAxisAlignment.end,
              children: [
                TextButton(
                  onPressed: () => _decidir(context, ref, aprovar: false),
                  child: const Text('Descartar'),
                ),
                const SizedBox(width: 8),
                FilledButton(
                  onPressed: () => _decidir(context, ref, aprovar: true),
                  child: const Text('Aprovar'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  /// O que a pessoa le primeiro — e o que ela vai usar para decidir.
  ///
  /// Prefere o titulo do proprio pedido; senao, a frase que a skill escreveu
  /// sobre si ("esquecer o procedimento X"). O nome tecnico da acao so vira
  /// titulo em ultimo caso: "playbook.forget" nao ajuda ninguem a julgar.
  static String _titulo(ApprovalOut pedido) {
    final titulo = pedido.payload['title'];
    if (titulo is String && titulo.isNotEmpty) return titulo;
    if (pedido.reason.isNotEmpty) return pedido.reason;
    return pedido.action;
  }

  /// Traduz a falha para o que de fato aconteceu com o PEDIDO.
  ///
  /// O 404 nao e um erro tecnico a ser despejado na tela: significa que o
  /// pedido deixou de existir — tipicamente porque o No reiniciou antes de
  /// voce decidir. Dizer isso e a diferenca entre uma tela que explica e uma
  /// que assusta.
  static String _recado(ApiException e) => switch (e.code) {
    404 => 'Este pedido expirou (o No foi reiniciado). Peca a acao de novo.',
    409 => 'Este pedido ja tinha sido decidido.',
    403 => 'Voce nao tem permissao para esta acao.',
    _ => 'Nao foi possivel decidir: ${e.message ?? e.code}',
  };

  static List<String> _passos(ApprovalOut pedido) {
    final passos = pedido.payload['steps'];
    if (passos is! List) return const [];
    return passos.whereType<String>().toList();
  }

  Future<void> _decidir(
    BuildContext context,
    WidgetRef ref, {
    required bool aprovar,
  }) async {
    final api = ref.read(approvalsApiProvider);
    try {
      if (aprovar) {
        // aprovar EXECUTA o pedido guardado — não é só registrar um sim
        await api.approveApiV1ApprovalsApprovalIdApprovePost(pedido.id);
      } else {
        await api.rejectApiV1ApprovalsApprovalIdRejectPost(pedido.id);
      }
      ref.invalidate(pendingApprovalsProvider);
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(aprovar ? 'Aprovado.' : 'Descartado.')),
      );
    } on ApiException catch (e) {
      // a lista some junto: insistir num pedido que nao existe mais so
      // repetiria o erro
      ref.invalidate(pendingApprovalsProvider);
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(_recado(e))));
    } catch (e) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text('Não foi possível decidir: $e')));
    }
  }
}
