import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
    rules: {
      // Design-system rule: style props bypass the @theme tokens. Use Tailwind
      // utility classes or the ui primitives (Icon/Text/Card/...). The few
      // genuinely dynamic cases (data-driven colour, computed width) are allowed
      // with an inline `// eslint-disable-next-line no-restricted-syntax` above them.
      'no-restricted-syntax': [
        'warn',
        {
          selector: "JSXAttribute[name.name='style']",
          message:
            'Avoid inline style={{}} — use Tailwind token utilities or a ui primitive. For genuinely dynamic values, add an eslint-disable-next-line with a reason.',
        },
      ],
    },
  },
  {
    // Layered data-flow rule: pages and components read data through hooks/,
    // never by importing the service layer directly. Type-only imports are fine.
    // `warn` for now — two legacy direct imports (wizard repo/user APIs, docs
    // download) are migrated to hooks during the page refactor, after which this
    // can be raised to `error`.
    files: ['src/pages/**/*.{ts,tsx}', 'src/components/**/*.{ts,tsx}'],
    rules: {
      '@typescript-eslint/no-restricted-imports': [
        'warn',
        {
          patterns: [
            {
              group: ['**/services', '**/services/*'],
              allowTypeImports: true,
              message: 'Read data through a hook in src/hooks/, not the service layer directly (type-only imports are fine).',
            },
          ],
        },
      ],
    },
  },
])
