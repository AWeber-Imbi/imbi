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

## overflow/no-clipped-max-height

Catches an element that caps its height and hides what does not fit. Content past the cap is then cut off with no way to scroll to it, which is easy to miss in review because short content looks fine.

### What it detects

A class string, in a literal or a template literal, that has a `max-h-*` class and `overflow-hidden`, `overflow-y-hidden`, `overflow-clip` or `overflow-y-clip`, with no scrolling or clamping class. Variant prefixes (`sm:`, `data-[state=open]:`) are ignored when matching.

```tsx
<div className="max-h-65 overflow-hidden px-6 py-4">
//              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ flagged

<div className="max-h-65 overflow-y-auto px-6 py-4" />   // scrolls: allowed
<p className="max-h-20 overflow-hidden line-clamp-3" />  // clamped on purpose: allowed
```

The rule reads one string at a time, so classes split across several `cn()` arguments are not combined.

### When a child scrolls instead

Some containers clip on purpose because a child is the scroll container, such as a dialog whose form scrolls or a Radix select whose viewport scrolls. Disable the rule on that line and name the child:

```tsx
// oxlint-disable-next-line overflow/no-clipped-max-height -- SelectPrimitive.Viewport below scrolls the options
```

### Tests

```sh
npx vitest run tools/
```
