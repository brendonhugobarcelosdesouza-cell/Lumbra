import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lumbra_api/api.dart';

import '../../core/api.dart';
import '../../design/secao.dart';
import '../../design/tokens.dart';

/// Os aparelhos que têm permissão de falar com este Nó.
///
/// Foi a primeira tela autenticada do app — existia para provar que a sessão
/// fluía ponta a ponta. Vira uma tela de CONTROLE de verdade quando o P3
/// trouxer o pareamento por QR: até lá, ela mostra quem já está dentro.
class DevicesScreen extends ConsumerWidget {
  const DevicesScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return MolduraDeSecao(
      titulo: 'Dispositivos',
      child: ListaAssincrona<DeviceResponse>(
        valor: ref.watch(devicesListProvider),
        oQueSeria: 'seus dispositivos',
        iconeDoVazio: Icons.devices_outlined,
        quandoVazio:
            'Nenhum aparelho pareado. Parear outro dispositivo com este Nó '
            'chega no P3, junto com a sincronização.',
        aoTerConteudo: (lista) => ColunaDeLeitura(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(
              Espaco.grande,
              Espaco.largo,
              Espaco.grande,
              Espaco.enorme,
            ),
            children: [for (final d in lista) _Dispositivo(dispositivo: d)],
          ),
        ),
      ),
    );
  }
}

class _Dispositivo extends StatelessWidget {
  const _Dispositivo({required this.dispositivo});

  final DeviceResponse dispositivo;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final textos = Theme.of(context).textTheme;

    return CartaoDaLumbra(
      child: Row(
        children: [
          Icon(
            _icone(dispositivo.platform),
            size: 18,
            color: cores.onSurfaceVariant,
          ),
          const SizedBox(width: Espaco.medio),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  dispositivo.name,
                  style: textos.bodyMedium?.copyWith(fontSize: 13.5),
                ),
                const SizedBox(height: Espaco.micro),
                Text(
                  _plataforma(dispositivo.platform),
                  style: TextStyle(
                    fontSize: 11,
                    color: cores.onSurfaceVariant,
                  ),
                ),
              ],
            ),
          ),
          _Estado(dispositivo.state),
        ],
      ),
    );
  }

  static IconData _icone(DevicePlatform p) => switch (p.value) {
    'android' || 'ios' => Icons.smartphone,
    'web' => Icons.language,
    _ => Icons.laptop,
  };

  static String _plataforma(DevicePlatform p) => switch (p.value) {
    'android' => 'Android',
    'ios' => 'iPhone',
    'web' => 'Navegador',
    'windows' => 'Windows',
    'macos' => 'macOS',
    'linux' => 'Linux',
    _ => p.value,
  };
}

/// Se este aparelho pode ou não falar com o Nó agora.
///
/// É a única informação da linha que muda o que a pessoa deve FAZER: um
/// dispositivo revogado ainda aparece na lista, e sem o selo pareceria
/// ativo — que é o oposto do que a tela existe para dizer.
class _Estado extends StatelessWidget {
  const _Estado(this.estado);

  final DeviceState estado;

  @override
  Widget build(BuildContext context) {
    final cores = Theme.of(context).colorScheme;
    final (texto, cor) = switch (estado.value) {
      'active' => ('ativo', const Color(0xFF4CAF7D)),
      'pending' => ('aguardando pareamento', cores.primary),
      'revoked' => ('revogado', cores.error),
      _ => (estado.value, cores.onSurfaceVariant),
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
            texto,
            style: TextStyle(fontSize: 11, color: cores.onSurface),
          ),
        ],
      ),
    );
  }
}
