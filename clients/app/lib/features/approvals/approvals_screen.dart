import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../design/secao.dart';
import '../../design/tokens.dart';
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
    return MolduraDeSecao(
      titulo: 'Aprovações',
      child: ListaAssincrona<ApprovalOut>(
        valor: ref.watch(pendingApprovalsProvider),
        oQueSeria: 'os pedidos',
        iconeDoVazio: Icons.verified_user_outlined,
        quandoVazio:
            'Nada aguardando sua decisão. Quando a Lumbra quiser fazer algo '
            'de impacto, o pedido aparece aqui antes de acontecer.',
        aoTerConteudo: (lista) => ColunaDeLeitura(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(
              Espaco.grande,
              Espaco.largo,
              Espaco.grande,
              Espaco.enorme,
            ),
            children: [
              for (final pedido in lista) _CartaoPedido(pedido: pedido),
            ],
          ),
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
    final cores = Theme.of(context).colorScheme;
    final textos = Theme.of(context).textTheme;

    return CartaoDaLumbra(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Text(
                  _titulo(pedido),
                  style: textos.bodyMedium?.copyWith(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              const SizedBox(width: Espaco.medio),
              _Risco(pedido.riskLevel),
            ],
          ),
          const SizedBox(height: Espaco.minimo),
          Text(
            pedido.action,
            style: TextStyle(
              fontFamily: 'monospace',
              fontSize: 11.5,
              color: cores.onSurfaceVariant,
            ),
          ),
          // a razão só aparece de novo se não virou o título
          if (pedido.reason.isNotEmpty &&
              _titulo(pedido) != pedido.reason) ...[
            const SizedBox(height: Espaco.medio),
            Text(
              pedido.reason,
              style: textos.bodyMedium?.copyWith(fontSize: 13, height: 1.5),
            ),
          ],
          // os passos propostos: é o que o usuário está aprovando de fato
          if (_passos(pedido).isNotEmpty) ...[
            const SizedBox(height: Espaco.medio),
            for (final passo in _passos(pedido))
              Padding(
                padding: const EdgeInsets.only(bottom: Espaco.minimo),
                child: Text(
                  '• $passo',
                  style: textos.bodyMedium?.copyWith(
                    fontSize: 13,
                    height: 1.5,
                  ),
                ),
              ),
          ],
          const SizedBox(height: Espaco.largo),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            children: [
              TextButton(
                onPressed: () => _decidir(context, ref, aprovar: false),
                style: TextButton.styleFrom(
                  foregroundColor: cores.onSurfaceVariant,
                ),
                child: const Text('Descartar'),
              ),
              const SizedBox(width: Espaco.curto),
              FilledButton(
                onPressed: () => _decidir(context, ref, aprovar: true),
                style: FilledButton.styleFrom(
                  padding: const EdgeInsets.symmetric(
                    horizontal: Espaco.grande,
                    vertical: Espaco.medio,
                  ),
                ),
                child: const Text('Aprovar'),
              ),
            ],
          ),
        ],
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

/// O nível de risco do pedido, com cor.
///
/// Cor porque é a única informação do cartão que muda a ATENÇÃO exigida: um
/// pedido de risco alto e um de risco baixo têm a mesma forma e não podem
/// ter o mesmo peso visual. O rótulo vem do Core e não é traduzido aqui —
/// traduzir sem saber o conjunto completo é convidar um `switch` que
/// silenciosamente deixa um caso de fora.
class _Risco extends StatelessWidget {
  const _Risco(this.nivel);

  final String nivel;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final cor = switch (nivel) {
      'critical' || 'high' => cores.error,
      'medium' => cores.primary,
      _ => cores.onSurfaceVariant,
    };
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: Espaco.curto,
        vertical: Espaco.micro,
      ),
      decoration: BoxDecoration(
        color: cores.surfaceContainerHigh,
        borderRadius: Raio.bordaSelo,
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 5,
            height: 5,
            decoration: BoxDecoration(color: cor, shape: BoxShape.circle),
          ),
          const SizedBox(width: Espaco.curto - 2),
          Text(
            _emPortugues(nivel),
            style: TextStyle(fontSize: 11, color: cores.onSurface),
          ),
        ],
      ),
    );
  }

  static String _emPortugues(String nivel) => switch (nivel) {
    'low' => 'risco baixo',
    'medium' => 'risco médio',
    'high' => 'risco alto',
    'critical' => 'risco crítico',
    _ => nivel,
  };
}
