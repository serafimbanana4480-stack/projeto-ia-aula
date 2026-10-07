# Configuração antiga do frontend

Estes ficheiros foram preservados ao migrar o frontend para pnpm e para a
configuração flat do ESLint:

- `.eslintrc.json` — configuração antiga, substituída por `frontend/eslint.config.js`.
- `package-lock.json` — lockfile antigo de npm, substituído por `frontend/pnpm-lock.yaml`.
- `fix_jsx.py` — cópia exata do utilitário antigo; outra versão histórica já está em `archive/codemods/`.

Ficam aqui apenas como histórico; o frontend ativo não os usa.
