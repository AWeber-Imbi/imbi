# Imbi UI — how to build with it

Imbi UI is the component layer of Imbi, a DevOps service-management app
(projects, environments, deployments, teams). It is shadcn/ui-style React on
Radix primitives, styled with **Tailwind CSS v4 utility classes** that map to
Imbi design tokens.

## Setup

Wrap the whole tree in `ImbiProvider` once. It supplies react-query, a router,
the theme context, and the toast host. Without it, API-backed pickers, links,
and theme-aware parts throw.

```jsx
const { ImbiProvider, Card, CardHeader, CardTitle, CardContent, Badge, Button } = window.ImbiUI

<ImbiProvider>
  <App />
</ImbiProvider>
```

- Dark mode: add the `dark` class to `<html>`. Tokens switch on their own.
- Fonts: Inter (UI) and JetBrains Mono (`font-mono`) ship in `fonts/`.
- Compound components are flat exports: `Dialog` + `DialogContent`,
  `DialogHeader`, `DialogTitle`, `DialogFooter`; `Select` + `SelectTrigger`,
  `SelectValue`, `SelectContent`, `SelectItem`; `Table` + `TableHeader`,
  `TableRow`, `TableHead`, `TableBody`, `TableCell`; `Card` + `CardHeader`,
  `CardTitle`, `CardDescription`, `CardContent`, `CardFooter`. All live on
  `window.ImbiUI`.
- Icons: import from `lucide-react` (the icon set the components use).
  `EntityIcon` resolves `lucide-<name>` values only.

## Styling idiom — use these token classes, not raw colors

The compiled stylesheet holds only the utilities the Imbi app uses. An
arbitrary value such as `w-[36rem]` or `bg-[#123456]` does not exist and does
nothing. Stay with this vocabulary:

| Purpose | Classes |
|---|---|
| Surfaces | `bg-background`, `bg-card`, `bg-secondary`, `bg-tertiary` |
| Text | `text-primary`, `text-secondary`, `text-tertiary`, `text-foreground`, `text-muted-foreground` |
| Status | `text-/bg-/border-` + `danger`, `success`, `warning`, `info`, `accent` |
| Borders | `border`, `border-border`, `border-primary`, `border-secondary`, `border-tertiary`, `divide-y divide-tertiary` |
| Type scale | `text-h1`, `text-h2`, `text-card-title`, `text-badge`, `text-chip`, `text-overline`, plus `text-sm`, `text-xs` |
| Brand action | `bg-action`, `bg-primary` (amber) — or just `<Button>` |
| Layout | `flex`, `grid`, `grid-cols-2/3`, `gap-2`, `gap-4`, `p-4`, `p-6`, `w-80`, `w-96`, `max-w-xl`, `rounded-md`, `rounded-lg` |

Token source: `styles.css` → `_ds_bundle.css` (the `@theme` block defines
`--color-*`, `--background-color-*`, `--text-color-*`, `--border-color-*`).
Before you use a class that is not in the table, search `_ds_bundle.css`
for it. Per-component APIs are in `components/<group>/<Name>/<Name>.d.ts`
and `<Name>.prompt.md`.

## Composition rules

- Dialog: `DialogHeader` and `DialogFooter` have their own `p-6` and borders.
  Put the body in its own `<div className="p-6">` between them.
  `AlertDialogContent` is already padded, so it needs no body wrapper.
- Status and environment labels use `Badge` (variants) or `EnvironmentBadge`.
  Do not make custom pills.
- Forms: `Label` + control pairs, or `FormField`. Mark required fields with
  `RequiredAsterisk`.
- Example code may wrap a component in `PreviewOnlyAutoOpen`. That wrapper
  only opens the component for the preview screenshot. It is not part of the
  library. Do not copy it; render the component directly.

## Example

```jsx
<ImbiProvider>
  <Card className="w-96">
    <CardHeader>
      <CardTitle>imbi-api</CardTitle>
    </CardHeader>
    <CardContent className="flex items-center gap-2">
      <Badge variant="success">production</Badge>
      <span className="text-sm text-secondary">v2.35.1</span>
      <Button className="ml-auto" size="sm" variant="outline">Deploy</Button>
    </CardContent>
  </Card>
</ImbiProvider>
```
