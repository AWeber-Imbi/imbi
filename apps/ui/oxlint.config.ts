import perfectionist from 'eslint-plugin-perfectionist'
import { defineConfig } from 'oxlint'

const perfectionistRecommendedNatural =
  perfectionist.configs['recommended-natural'].rules

export default defineConfig({
  categories: {
    correctness: 'error',
  },
  env: {
    browser: true,
    builtin: true,
    es2020: true,
  },
  ignorePatterns: ['dist', 'src/types/api-generated.ts'],
  jsPlugins: ['eslint-plugin-react-refresh', 'eslint-plugin-perfectionist'],
  overrides: [
    {
      files: ['src/test/**/*.{ts,tsx}'],
      rules: {
        'react-refresh/only-export-components': 'off',
      },
    },
  ],
  plugins: ['typescript', 'react', 'oxc'],
  rules: {
    'no-unused-vars': [
      'error',
      {
        argsIgnorePattern: '^_',
        caughtErrorsIgnorePattern: '^_',
        varsIgnorePattern: '^_',
      },
    ],
    'react-refresh/only-export-components': [
      'warn',
      {
        allowConstantExport: true,
      },
    ],
    'react/exhaustive-deps': 'warn',
    'react/rules-of-hooks': 'error',
    'typescript/no-explicit-any': 'warn',
    ...perfectionistRecommendedNatural,
    'perfectionist/sort-imports': [
      'error',
      {
        customGroups: [
          {
            elementNamePattern: '^react$',
            groupName: 'react',
          },
          {
            elementNamePattern: '^react-router-dom$',
            groupName: 'react-router',
          },
        ],
        groups: [
          'react',
          'react-router',
          ['builtin', 'external'],
          'internal',
          ['parent', 'sibling', 'index'],
        ],
        ignoreCase: false,
        internalPattern: ['^@/'],
        newlinesBetween: 1,
        order: 'asc',
        sortSideEffects: false,
        type: 'natural',
      },
    ],
  },
})
