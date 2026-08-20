import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../design/secao.dart';
import '../../design/tokens.dart';
import 'agents_providers.dart';

/// Quem trabalha dentro da Lumbra.
///
/// Os agentes existem desde a fase A e sempre foram invisíveis: quando você
/// pergunta sobre um documento, é o `documents-agent` que responde, e nada
/// na tela dizia isso. Uma plataforma que delega precisa mostrar PARA QUEM
/// delega — senão "a Lumbra fez" vira uma caixa-preta com nome bonito.
///
/// Esta tela não cria nem configura agente. Ela responde três perguntas que
/// já têm resposta na API: quem existe, o que cada um sabe fazer, e quanto
/// risco carrega. Criar agente é outro projeto, e a tela não finge o
/// contrário.
class AgentsScreen extends ConsumerWidget {
  const AgentsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return MolduraDeSecao(
      titulo: 'Agentes',
      child: ListaAssincrona<AgentOut>(
        valor: ref.watch(agentsProvider),
        oQueSeria: 'os agentes',
        iconeDoVazio: Icons.smart_toy_outlined,
        quandoVazio:
            'Nenhum agente registrado neste Nó. Os agentes são quem a Lumbra '
            'chama para tarefas especializadas — documentos, memória, '
            'pesquisa.',
        aoTerConteudo: (lista) => ColunaDeLeitura(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(
              Espaco.grande,
              Espaco.largo,
              Espaco.grande,
              Espaco.enorme,
            ),
            children: [for (final a in lista) _Agente(agente: a)],
          ),
        ),
      ),
    );
  }
}

class _Agente extends StatelessWidget {
  const _Agente({required this.agente});

  final AgentOut agente;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final textos = Theme.of(context).textTheme;

    return CartaoDaLumbra(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                Icons.smart_toy_outlined,
                size: 18,
                color: agente.enabled ? cores.primary : cores.onSurfaceVariant,
              ),
              const SizedBox(width: Espaco.medio),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      agente.name,
                      style: textos.bodyMedium?.copyWith(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: Espaco.micro),
                    Text(
                      'versão ${agente.version}',
                      style: TextStyle(
                        fontSize: 11,
                        color: cores.onSurfaceVariant,
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: Espaco.medio),
              if (!agente.enabled) const _Selo('desligado', alerta: true),
              if (agente.enabled) _Risco(agente.riskLevel),
            ],
          ),
          if (agente.description.isNotEmpty) ...[
            const SizedBox(height: Espaco.medio),
            Text(
              agente.description,
              style: textos.bodyMedium?.copyWith(fontSize: 13, height: 1.5),
            ),
          ],
          // as capabilities são o que ele PODE fazer — o limite do que a
          // Lumbra consegue delegar a ele, e portanto o que se está
          // autorizando quando o orquestrador o escolhe
          if (agente.capabilities.isNotEmpty) ...[
            const SizedBox(height: Espaco.largo),
            Text(
              'SABE FAZER',
              style: TextStyle(
                fontSize: 10,
                fontWeight: FontWeight.w700,
                letterSpacing: 0.8,
                color: cores.onSurfaceVariant,
              ),
            ),
            const SizedBox(height: Espaco.curto),
            Wrap(
              spacing: Espaco.curto,
              runSpacing: Espaco.curto,
              children: [
                for (final c in agente.capabilities) _Selo(c),
              ],
            ),
          ],
        ],
      ),
    );
  }
}

class _Selo extends StatelessWidget {
  const _Selo(this.texto, {this.alerta = false});

  final String texto;
  final bool alerta;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    return Container(
      padding: const EdgeInsets.symmetric(
        horizontal: Espaco.curto,
        vertical: Espaco.micro,
      ),
      decoration: BoxDecoration(
        color: cores.surfaceContainerHigh,
        borderRadius: Raio.bordaSelo,
      ),
      child: Text(
        texto,
        style: TextStyle(
          fontSize: 11,
          fontFamily: alerta ? null : 'monospace',
          color: alerta ? cores.error : cores.onSurfaceVariant,
        ),
      ),
    );
  }
}

/// Quanto risco este agente carrega — a mesma escala da fila de aprovações.
///
/// Mesmo vocabulário e mesma cor de propósito: risco alto aqui e risco alto
/// lá são a mesma coisa, e usar dois desenhos para o mesmo conceito faria a
/// pessoa aprender duas vezes.
class _Risco extends StatelessWidget {
  const _Risco(this.nivel);

  final String nivel;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final cor = switch (nivel) {
      'critical' || 'high' => cores.error,
      'medium' => cores.primary,
      _ => const Color(0xFF4CAF7D),
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
            switch (nivel) {
              'low' => 'risco baixo',
              'medium' => 'risco médio',
              'high' => 'risco alto',
              'critical' => 'risco crítico',
              _ => nivel,
            },
            style: TextStyle(fontSize: 11, color: cores.onSurface),
          ),
        ],
      ),
    );
  }
}
