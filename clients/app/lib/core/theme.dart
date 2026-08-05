import 'package:flutter/material.dart';

/// A identidade visual da Lumbra — claro e escuro, um só lugar.
///
/// Existe porque o app estava no tema PADRÃO do Flutter, com o roxo do
/// template (`0xFF6750A4`). Um assistente pessoal que guarda faturas, saúde
/// e memórias não pode parecer um projeto recém-criado: a aparência é parte
/// de confiar nele.
///
/// O nome dá a paleta. *Lumbra* — **lumen** (luz) e **umbra** (penumbra): um
/// âmbar quente de luz sobre neutros frios e profundos. O âmbar aparece
/// pouco e sempre com intenção (ação principal, seleção, foco); o resto é
/// silêncio, para o conteúdo do usuário ser a única coisa colorida na tela.
///
/// Sem fontes de internet DE PROPÓSITO: o `google_fonts` baixa arquivos em
/// tempo de execução, e uma plataforma local-first não deveria depender da
/// rede para desenhar a própria interface. Usamos a fonte da plataforma e
/// mexemos no que importa — escala, peso e espaçamento.
class LumbraTheme {
  const LumbraTheme._();

  /// A luz: âmbar quente. É a única cor viva do sistema.
  static const _luz = Color(0xFFD99A2B);

  /// A penumbra: azul-ardósia profundo, quase preto, mas nunca preto puro —
  /// preto absoluto vibra contra texto claro e cansa em uso longo.
  static const _penumbraProfunda = Color(0xFF14161B);
  static const _penumbra = Color(0xFF1C1F26);

  /// Papel: off-white levemente quente. Branco puro é duro no claro.
  static const _papel = Color(0xFFFAF8F5);

  static ThemeData get claro => _montar(Brightness.light);
  static ThemeData get escuro => _montar(Brightness.dark);

  static ThemeData _montar(Brightness brilho) {
    final escuro = brilho == Brightness.dark;
    // fromSeed garante um esquema COMPLETO e acessível; fixamos só o que dá
    // caráter (a luz e os neutros), em vez de escrever 30 cores à mão
    final cores = ColorScheme.fromSeed(
      seedColor: _luz,
      brightness: brilho,
    ).copyWith(
      primary: escuro ? _luz : const Color(0xFF8A5A12),
      surface: escuro ? _penumbraProfunda : _papel,
      onSurface: escuro ? const Color(0xFFE6E3DD) : const Color(0xFF1B1A17),
      outline: escuro ? const Color(0xFF3A3F49) : const Color(0xFFD6D0C6),
    );

    final base = ThemeData(colorScheme: cores, useMaterial3: true);
    final corpo = cores.onSurface;
    // tom secundário FIXO em vez de opacidade sobre o corpo: opacidade muda
    // de nome entre versões do Flutter (withOpacity/withValues) e é o tipo de
    // detalhe que quebra o build sem avisar
    final discreto = escuro ? const Color(0xFF9B968D) : const Color(0xFF6B665E);

    return base.copyWith(
      scaffoldBackgroundColor: cores.surface,
      // títulos um pouco mais apertados e pesados; texto de leitura com
      // altura de linha generosa — a Lumbra é feita de parágrafos, não de
      // rótulos soltos
      textTheme: base.textTheme.copyWith(
        titleLarge: base.textTheme.titleLarge?.copyWith(
          fontWeight: FontWeight.w600,
          letterSpacing: -0.4,
          color: corpo,
        ),
        titleMedium: base.textTheme.titleMedium?.copyWith(
          fontWeight: FontWeight.w600,
          letterSpacing: -0.2,
          color: corpo,
        ),
        bodyLarge: base.textTheme.bodyLarge?.copyWith(height: 1.5, color: corpo),
        bodyMedium: base.textTheme.bodyMedium?.copyWith(height: 1.5, color: corpo),
        bodySmall: base.textTheme.bodySmall?.copyWith(height: 1.4, color: discreto),
        labelLarge: base.textTheme.labelLarge?.copyWith(fontWeight: FontWeight.w600),
      ),
      // barra de topo sem sombra e sem cor própria: ela é moldura, não peça
      appBarTheme: AppBarTheme(
        backgroundColor: cores.surface,
        foregroundColor: corpo,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        titleTextStyle: base.textTheme.titleLarge?.copyWith(
          fontWeight: FontWeight.w600,
          letterSpacing: -0.4,
          color: corpo,
        ),
      ),
      dividerTheme: DividerThemeData(color: cores.outline, thickness: 1, space: 1),
      // campos de texto com fundo, sem borda pesada: o cursor é o destaque
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: escuro ? _penumbra : Colors.white,
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: cores.outline),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: cores.outline),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(12),
          borderSide: BorderSide(color: cores.primary, width: 1.6),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
          textStyle: const TextStyle(fontWeight: FontWeight.w600),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
        ),
      ),
      // selo neutro: o Chip aqui é etiqueta (risco, proveniência), não botão
      chipTheme: ChipThemeData(
        backgroundColor: escuro ? _penumbra : const Color(0xFFF1EDE6),
        side: BorderSide(color: cores.outline),
        labelStyle: base.textTheme.labelMedium?.copyWith(color: discreto),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(8)),
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      ),
      listTileTheme: ListTileThemeData(
        iconColor: discreto,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
      floatingActionButtonTheme: FloatingActionButtonThemeData(
        backgroundColor: cores.primary,
        foregroundColor: escuro ? const Color(0xFF241800) : Colors.white,
      ),
    );
  }
}
