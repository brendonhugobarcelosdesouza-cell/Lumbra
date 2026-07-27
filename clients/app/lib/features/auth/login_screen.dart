import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/session.dart';

/// Entrar ou criar conta no Nó (email + senha, via /api/v1/auth). O botão
/// mostra progresso local; o erro vem do estado da sessão.
class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});

  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _email = TextEditingController();
  final _senha = TextEditingController();
  bool _registrando = false;
  bool _enviando = false;

  @override
  void dispose() {
    _email.dispose();
    _senha.dispose();
    super.dispose();
  }

  Future<void> _enviar() async {
    setState(() => _enviando = true);
    final controle = ref.read(sessionControllerProvider.notifier);
    final email = _email.text.trim();
    final senha = _senha.text;
    if (_registrando) {
      await controle.register(email, senha);
    } else {
      await controle.login(email, senha);
    }
    // no sucesso, a raiz troca para a Home e este widget é descartado
    if (mounted) setState(() => _enviando = false);
  }

  @override
  Widget build(BuildContext context) {
    final falhou = ref.watch(sessionControllerProvider).hasError;
    final tema = Theme.of(context);
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 360),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Text('Lumbra', style: tema.textTheme.headlineMedium),
                const SizedBox(height: 24),
                TextField(
                  controller: _email,
                  enabled: !_enviando,
                  keyboardType: TextInputType.emailAddress,
                  decoration: const InputDecoration(
                    labelText: 'E-mail',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: _senha,
                  enabled: !_enviando,
                  obscureText: true,
                  onSubmitted: _enviando ? null : (_) => _enviar(),
                  decoration: const InputDecoration(
                    labelText: 'Senha',
                    border: OutlineInputBorder(),
                  ),
                ),
                const SizedBox(height: 20),
                if (falhou)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text(
                      'Não foi possível entrar. Confira os dados e se o Nó está no ar.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: tema.colorScheme.error),
                    ),
                  ),
                SizedBox(
                  width: double.infinity,
                  child: FilledButton(
                    onPressed: _enviando ? null : _enviar,
                    child: _enviando
                        ? const SizedBox(
                            height: 18,
                            width: 18,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : Text(_registrando ? 'Criar conta' : 'Entrar'),
                  ),
                ),
                TextButton(
                  onPressed: _enviando
                      ? null
                      : () => setState(() => _registrando = !_registrando),
                  child: Text(
                    _registrando ? 'Já tenho conta' : 'Criar uma conta',
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
