# tools/

Local oxlint JS plugins and their tests.

## css-vars/no-unknown-css-var

Catches references to undefined CSS custom properties in string literals and template literals. Prevents stale variable names from silently breaking styles (e.g. after a Tailwind version migration).

### What it detects

Both standard `var()` syntax and Tailwind v4 shorthand:

```tsx
// var() syntax
<div style={{ color: 'var(--color-text-primary)' }} />
//                          ^^^^^^^^^^^^^^^^^^^^^ unknown

// Tailwind shorthand
<div className="bg-(--color-background-action)" />
//                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^ unknown
```

### Error messages

```
Unknown CSS custom property "--color-text-primary".
Unknown CSS custom property "--color-text-primry". Did you mean "--text-color-primary"?
```

The rule uses Levenshtein distance to suggest close matches when available.

### Configuration

In `.oxlintrc.json`:

```jsonc
{
  "jsPlugins": ["./tools/oxlint-plugin-css-vars.ts"],
  "settings": {
    "cssVars": {
      "cssFile": "src/index.css",           // path to CSS file with custom property definitions
      "ignorePrefixes": ["--radix-", "--tw-"] // prefixes to skip (third-party/framework vars)
    }
  },
  "rules": {
    "css-vars/no-unknown-css-var": "error"
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `cssFile` | `src/index.css` | CSS file to parse for `--custom-property: value` definitions |
| `ignorePrefixes` | `["--radix-", "--assistant-", "--tw-"]` | Variable prefixes to ignore (not defined in our CSS) |

### Requirements

Node 22.6+ (native TypeScript type stripping) so oxlint can load the `.ts` plugin directly. CI uses Node 24.

### Tests

```sh
npx vitest run tools/
```
