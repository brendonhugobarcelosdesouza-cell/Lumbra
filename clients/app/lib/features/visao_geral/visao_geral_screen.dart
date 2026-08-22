import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../design/secao.dart';
import '../../design/tokens.dart';
import '../agents/agents_providers.dart';
import '../approvals/approvals_providers.dart';
import '../chat/chat_providers.dart';
import '../documents/documents_providers.dart';
import '../memories/memories_providers.dart';
import '../playbooks/playbooks_providers.dart';
import '../shell/secao_atual.dart';
import 'saude_providers.dart';

/// A porta de entrada: o que a Lumbra tem, e se ela está inteira.
///
/// A referência visual desta tela mostrava agenda, tarefas e "a Lumbra
/// percebeu" — tudo do P5, que nem começou. Construí só o que tem dado:
/// o diagnóstico do Nó (a mesma fonte do `lumbra doctor`, que até hoje só
/// existia no Developer Console) e a contagem do que está guardado.
///
/// **Cartão sem dado não entra na tela** (ADR-074). Um painel bonito cheio
/// de números inventados seria a versão em interface do assistente listando
/// capacidades que não tem.
class VisaoGeralScreen extends ConsumerWidget {
  const VisaoGeralScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return MolduraDeSecao(
      titulo: 'Visão geral',
      acoes: [
        IconButton(
          tooltip: 'Verificar de novo',
          iconSize: 18,
          onPressed: () => ref.invalidate(saudeProvider),
          icon: const Icon(Icons.refresh),
        ),
      ],
      child: ColunaDeLeitura(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(
            Espaco.grande,
            Espaco.amplo,
            Espaco.grande,
            Espaco.enorme,
          ),
          children: const [
            _Saudacao(),
            SizedBox(height: Espaco.grande),
            _OQueEstaGuardado(),
            SizedBox(height: Espaco.grande),
            _EstadoDaLumbra(),
          ],
        ),
      ),
    );
  }
}

class _Saudacao extends StatelessWidget {
  const _Saudacao();

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final hora = DateTime.now().hour;
    // sem nome: o Nó não devolve perfil, e chamar alguém pelo começo do
    // e-mail é pior que não chamar por nome nenhum
    final (saudacao, icone) = switch (hora) {
      >= 5 && < 12 => ('Bom dia.', Icons.wb_sunny_outlined),
      >= 12 && < 18 => ('Boa tarde.', Icons.wb_twilight),
      _ => ('Boa noite.', Icons.nightlight_outlined),
    };

    return Row(
      children: [
        Icon(icone, size: 26, color: cores.primary),
        const SizedBox(width: Espaco.largo),
        // Expanded e não largura natural: a frase é fixa, mas a coluna da
        // seção encolhe com a janela e com o painel lateral. Sem isto ela
        // transborda a partir de ~530px — que é exatamente a largura em que
        // alguém usa a Lumbra ao lado de outra janela.
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(saudacao, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: Espaco.micro),
              Text(
                'Isto é o que a Lumbra guarda e como ela está agora.',
                style: TextStyle(fontSize: 12.5, color: cores.onSurfaceVariant),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// Quanto de cada coisa existe — e um caminho para lá.
///
/// As contagens vêm dos MESMOS providers que as seções usam, então elas não
/// podem divergir do que a seção mostra quando aberta. Números repetidos de
/// duas fontes é como um painel começa a mentir sem que ninguém perceba.
class _OQueEstaGuardado extends ConsumerWidget {
  const _OQueEstaGuardado();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _Rotulo('O que a Lumbra guarda'),
        const SizedBox(height: Espaco.medio),
        Wrap(
          spacing: Espaco.medio,
          runSpacing: Espaco.medio,
          children: [
            _Contagem(
              icone: Icons.forum_outlined,
              nome: 'Conversas',
              quantos: ref.watch(conversationsProvider).valueOrNull?.length,
              secao: Secoes.conversas,
            ),
            _Contagem(
              icone: Icons.psychology_outlined,
              nome: 'Memória',
              quantos: ref.watch(memoriesProvider).valueOrNull?.length,
              secao: Secoes.memoria,
            ),
            _Contagem(
              icone: Icons.folder_outlined,
              nome: 'Documentos',
              quantos: ref.watch(documentsProvider).valueOrNull?.length,
              secao: Secoes.documentos,
            ),
            _Contagem(
              icone: Icons.menu_book_outlined,
              nome: 'Procedimentos',
              quantos: ref.watch(playbooksProvider).valueOrNull?.length,
              secao: Secoes.procedimentos,
            ),
            _Contagem(
              icone: Icons.verified_user_outlined,
              nome: 'Aprovações',
              quantos: ref.watch(pendingApprovalsProvider).valueOrNull?.length,
              secao: Secoes.aprovacoes,
              // a única contagem que PEDE ação: um pedido esperando decisão
              // não é inventário, é fila
              chamaAtencao: true,
            ),
            _Contagem(
              icone: Icons.smart_toy_outlined,
              nome: 'Agentes',
              quantos: ref.watch(agentsProvider).valueOrNull?.length,
              secao: Secoes.agentes,
            ),
          ],
        ),
      ],
    );
  }
}

class _Contagem extends ConsumerWidget {
  const _Contagem({
    required this.icone,
    required this.nome,
    required this.quantos,
    required this.secao,
    this.chamaAtencao = false,
  });

  final IconData icone;
  final String nome;

  /// `null` enquanto carrega. Mostrar zero antes de saber é afirmar que não
  /// há nada — e "nada" é uma informação forte demais para se chutar.
  final int? quantos;
  final String secao;
  final bool chamaAtencao;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final cores = Theme.of(context).colorScheme;
    final urgente = chamaAtencao && (quantos ?? 0) > 0;

    return SizedBox(
      width: 168,
      child: Material(
        color: cores.surfaceContainerLow,
        borderRadius: Raio.bordaCartao,
        child: InkWell(
          borderRadius: Raio.bordaCartao,
          onTap: () => ref.read(secaoAtualProvider.notifier).state = secao,
          child: Container(
            decoration: BoxDecoration(
              borderRadius: Raio.bordaCartao,
              border: Border.all(
                color: urgente ? cores.primary : cores.outlineVariant,
              ),
            ),
            padding: const EdgeInsets.all(Espaco.largo),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  icone,
                  size: 17,
                  color: urgente ? cores.primary : cores.onSurfaceVariant,
                ),
                const SizedBox(height: Espaco.medio),
                Text(
                  quantos?.toString() ?? '—',
                  style: Theme.of(context).textTheme.titleLarge?.copyWith(
                    fontSize: 22,
                    fontWeight: FontWeight.w700,
                    color: urgente ? cores.primary : cores.onSurface,
                  ),
                ),
                const SizedBox(height: Espaco.micro),
                Text(
                  nome,
                  style: TextStyle(
                    fontSize: 12,
                    color: cores.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

/// O diagnóstico do Nó, com as mesmas verificações do `lumbra doctor`.
///
/// Ele existia desde a Leva 3 e só era visível no Developer Console — uma
/// página HTML servida pelo próprio Nó, que quem usa a Lumbra nunca abriu.
/// Aqui ela vira parte do produto: cada verificação diz o que está de pé e,
/// quando não está, o que fazer a respeito.
class _EstadoDaLumbra extends ConsumerWidget {
  const _EstadoDaLumbra();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final saude = ref.watch(saudeProvider);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _Rotulo('Como a Lumbra está'),
        const SizedBox(height: Espaco.medio),
        saude.when(
          loading: () => const Padding(
            padding: EdgeInsets.symmetric(vertical: Espaco.grande),
            child: Carregando(),
          ),
          error: (erro, _) => Falhou(
            oQueSeria: 'o diagnóstico',
            detalhe: '$erro',
            aoTentarDeNovo: () => ref.invalidate(saudeProvider),
          ),
          data: (dados) => dados == null
              ? const Vazio(
                  texto: 'O Nó respondeu sem diagnóstico.',
                  icone: Icons.help_outline,
                )
              : _Diagnostico(dados),
        ),
      ],
    );
  }
}

class _Diagnostico extends StatelessWidget {
  const _Diagnostico(this.saude);

  final HealthOut saude;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    // as que estão bem viram uma linha só; as que não estão ganham o espaço.
    // Uma lista de dez "OK" esconde o único "FALHA" no meio.
    final atencao = saude.checks
        .where((c) => c.status != 'ok' && c.status != 'skip')
        .toList();
    final tranquilas = saude.checks.where((c) => c.status == 'ok').toList();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        CartaoDaLumbra(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Icon(
                    saude.ready ? Icons.check_circle : Icons.error_outline,
                    size: 18,
                    color: saude.ready
                        ? const Color(0xFF4CAF7D)
                        : cores.error,
                  ),
                  const SizedBox(width: Espaco.medio),
                  Expanded(
                    child: Text(
                      saude.ready
                          ? 'Tudo pronto para usar.'
                          : 'Há problemas impedindo o funcionamento.',
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: Espaco.medio),
              Text(
                'Lumbra ${saude.version} · ${saude.modules.length} módulos · '
                '${saude.skills} habilidades · '
                '${tranquilas.length} verificações em ordem',
                style: TextStyle(fontSize: 11.5, color: cores.onSurfaceVariant),
              ),
            ],
          ),
        ),
        for (final c in atencao) _Verificacao(c),
      ],
    );
  }
}

class _Verificacao extends StatelessWidget {
  const _Verificacao(this.check);

  final CheckOut check;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final falha = check.status == 'fail';

    return CartaoDaLumbra(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                falha ? Icons.error_outline : Icons.warning_amber_outlined,
                size: 17,
                color: falha ? cores.error : cores.primary,
              ),
              const SizedBox(width: Espaco.medio),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      check.name,
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: Espaco.micro),
                    Text(
                      check.summary,
                      style: const TextStyle(fontSize: 12.5, height: 1.5),
                    ),
                    if (check.detail != null) ...[
                      const SizedBox(height: Espaco.minimo),
                      Text(
                        check.detail!,
                        style: TextStyle(
                          fontSize: 11.5,
                          color: cores.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
          // `fix` é obrigatório em aviso e falha por contrato do Core, e é o
          // que separa um diagnóstico de uma reclamação
          if (check.fix != null) ...[
            const SizedBox(height: Espaco.medio),
            Container(
              width: double.infinity,
              padding: const EdgeInsets.all(Espaco.medio),
              decoration: BoxDecoration(
                color: cores.surfaceContainerHigh,
                borderRadius: Raio.bordaItem,
              ),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Icon(
                    Icons.lightbulb_outline,
                    size: 14,
                    color: cores.onSurfaceVariant,
                  ),
                  const SizedBox(width: Espaco.curto),
                  Expanded(
                    child: SelectableText(
                      check.fix!,
                      style: const TextStyle(fontSize: 12, height: 1.5),
                    ),
                  ),
                ],
              ),
            ),
          ],
        ],
      ),
    );
  }
}

class _Rotulo extends StatelessWidget {
  const _Rotulo(this.texto);

  final String texto;

  @override
  Widget build(BuildContext context) {
    return Text(
      texto.toUpperCase(),
      style: TextStyle(
        fontSize: 10,
        fontWeight: FontWeight.w700,
        letterSpacing: 0.8,
        color: Theme.of(context).colorScheme.onSurfaceVariant,
      ),
    );
  }
}
