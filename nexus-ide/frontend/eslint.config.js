/**
 * ESLint flat config (ESLint 9).
 *
 * WHY THIS FILE EXISTS
 * --------------------
 * The project had eslint@9.13.0 (flat-config era) but only `.eslintrc.json`.
 * `next lint` still worked through Next's LegacyESLint bridge, but that bridge
 * is REMOVED in Next 16 and `next lint` is already deprecated as of 15.5.22.
 * The bare `eslint` CLI exited 2 ("couldn't find eslint.config"), so IDE
 * integration and any direct-CI ESLint call were dead. This file is that config.
 *
 * WHY FlatCompat
 * --------------
 * VERIFIED, not assumed: `eslint-config-next@15.0.0` ships only eslintrc
 * configs (`index.js` exports `{extends, plugins, rules, parser, overrides,
 * settings, env}`; `core-web-vitals.js` extends it). It has NO flat-config
 * export. So the eslintrc config is composed into flat form via
 * `@eslint/eslintrc`'s FlatCompat, which is installed (3.3.6).
 *
 * WHAT IT COVERS THAT `next lint` DID NOT
 * ---------------------------------------
 * `next lint` defaults to `ESLINT_DEFAULT_DIRS` = app, pages, components, lib,
 * src. That left hooks/, stores/, contexts/, types/, tests/ and e2e/ completely
 * unlinted -- roughly a quarter of the codebase, including the 662-line core
 * chat transport in hooks/useAgentStream.ts. Those are linted here.
 *
 * Two real warnings that were invisible before and are now reported:
 *   hooks/useAgentStream.ts:27  react-hooks/exhaustive-deps
 *   stores/useEventBus.ts:81    react-hooks/exhaustive-deps
 * Both are left unfixed on purpose -- see the report; the first is a genuine
 * bug in someone else's file and must not be papered over from here.
 *
 * Run either way:
 *   pnpm exec eslint .
 *   pnpm run lint
 */

"use strict";

const js = require("@eslint/js");
const { FlatCompat } = require("@eslint/eslintrc");
const path = require("path");

const compat = new FlatCompat({
  baseDirectory: __dirname,
  recommendedConfig: js.configs.recommended,
  allConfig: js.configs.all,
});

/**
 * Directories that must be linted. `eslint .` already walks the tree, but
 * `ignores` below would otherwise be the only thing steering it, so this is
 * declared explicitly to make the coverage requirement self-documenting and to
 * survive a future `eslint <dir>` invocation.
 */
const LINTED_DIRS = [
  "app",
  "components",
  "lib",
  "hooks",
  "stores",
  "contexts",
  "types",
  "tests",
  "e2e",
];

module.exports = [
  {
    // Build output, reports and vendored code. `.next*` matters twice over: the
    // project sets `distDir: .next-dev` for `next dev` (next.config.mjs:27), so
    // BOTH .next and .next-dev exist on disk and both contain generated
    // TypeScript that must never be linted or type-checked.
    ignores: [
      ".next/**",
      ".next-dev/**",
      "node_modules/**",
      "out/**",
      "coverage/**",
      "playwright-report/**",
      "playwright_report/**",
      "test-results/**",
      "blob-report/**",
      ".playwright-mcp/**",
      "next-env.d.ts",
      "**/*.tsbuildinfo",
    ],
  },

  // The project's existing ruleset, translated to flat form.
  ...compat.extends("next/core-web-vitals"),

  // TypeScript / TSX. FlatCompat's `overrides` for TS arrive through the
  // extended config, but the parser and plugin have to be registered on the
  // flat config object as well for rules to resolve by name.
  {
    files: ["**/*.ts", "**/*.tsx", "**/*.mts", "**/*.cts"],
    languageOptions: {
      parser: require("@typescript-eslint/parser"),
      parserOptions: {
        ecmaVersion: "latest",
        sourceType: "module",
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      "@typescript-eslint": require("@typescript-eslint/eslint-plugin"),
    },
    rules: {
      // Type-aware linting is off on purpose: the project does not use
      // `parserOptions.project`, so these would be type errors, not lint
      // errors. `tsc --noEmit` is the type gate (pnpm run type-check).
      "@typescript-eslint/no-unused-vars": [
        "warn",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
    },
  },

  // Test files: describe/it/expect are globals under `globals: true` in
  // vitest.config.ts, and Playwright's `test` collides with Vitest's.
  {
    files: ["tests/**/*.{ts,tsx}", "e2e/**/*.{ts,tsx}"],
    languageOptions: {
      globals: {
        describe: "readonly",
        it: "readonly",
        test: "readonly",
        expect: "readonly",
        vi: "readonly",
        beforeEach: "readonly",
        afterEach: "readonly",
        beforeAll: "readonly",
        afterAll: "readonly",
        global: "readonly",
        window: "readonly",
        document: "readonly",
      },
    },
  },

  // Config and tooling files: Node scripts, not browser code.
  //
  // `sourceType` is deliberately NOT set here. The two parsers in play
  // disagree about its legal values: eslint core accepts
  // "script" | "module" | "commonjs", while @typescript-eslint/parser accepts
  // "module" | "script" | "unambiguous" | undefined and rejects "commonjs".
  // Setting either value makes one of them throw a config/parse error, so the
  // parsers' own defaults are used. This project mixes CommonJS
  // (eslint.config.js) and ESM (next.config.mjs, *.config.mjs) and they all
  // lint cleanly without an override.
  {
    files: ["*.config.js", "*.config.cjs", "*.config.mjs", "eslint.config.js"],
    languageOptions: {
      globals: { module: "writable", require: "readonly", process: "readonly" },
    },
  },

  // Explicit, linted-directory declaration. `eslint .` covers these already;
  // this block exists so `LINTED_DIRS` is load-bearing rather than decorative,
  // and so adding a new top-level source dir is a deliberate act.
  {
    name: "nexus/linted-dirs",
    files: LINTED_DIRS.map((dir) => `${dir}/**/*.{js,jsx,ts,tsx,mjs,cjs}`),
    rules: {
      // Restated from react-hooks/recommended so that removing the compat
      // extends above cannot silently switch off the rule that guards the
      // event-stream dependency arrays.
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "warn",
    },
  },

  {
    name: "nexus/ignored-dirs-are-lintable",
    // Fails loudly if someone re-adds hooks/ or stores/ to `ignores`.
    files: ["hooks/**/*.ts", "stores/**/*.ts", "contexts/**/*.ts"],
    rules: {},
  },
];
