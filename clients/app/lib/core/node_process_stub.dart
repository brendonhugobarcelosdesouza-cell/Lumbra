import 'node_process.dart';

/// Sem processo, sem log de processo.
String? get caminhoDoLogDoNoDaPlataforma => null;

/// Plataformas sem processos (Web, e por ora Android).
///
/// Não finge que subiu: devolve `indisponivel` para a interface poder dizer a
/// verdade — "aqui você precisa apontar para um Nó que já está no ar" — em vez
/// de ficar tentando para sempre.
class GerenteIndisponivel implements GerenteDoNo {
  @override
  Future<PartidaDoNo> iniciar() async => PartidaDoNo.indisponivel;

  @override
  Future<void> parar() async {}

  @override
  bool get somosDonos => false;

  @override
  String get ultimoErro => '';
}

GerenteDoNo criarGerenteDoNo() => GerenteIndisponivel();
