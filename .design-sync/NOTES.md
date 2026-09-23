# design-sync notes (Imbi UI)

## Setup
- [GENERAL] `ui/` is an app, not a library: no `dist/` entry. `.design-sync/lib-build/build.sh` builds `ui/src/components/ui/**` (plus `ImbiProvider`) as an ES library into `.design-sync/.cache/lib-dist/` (vite lib mode + `tsc` declarations). `cfg.entry` points at it; `cfg.buildCmd` runs it. `.design-sync/rebuild.sh` = lib build + converter + validate.
- [GENERAL] Package shape, not storybook: the storybook shape only lists storied components (6 of 65). The 6 stories are ported as authored previews.
- [GENERAL] `@/` alias in emitted `.d.ts` -> `fix-dts.mjs` rewrites to relative paths (ts-morph has no path mapping). `lib-dist/node_modules` symlinks `ui/node_modules` so `@types/react` resolves (else `[DTS_REACT]`).
- [GENERAL] Bundle was 32 MB (12 MB upload cap): the lazy icon sets (aws, devicon, simple-icons, phosphor, tabler) inline into one file. `vite.config.ts` stubs them to empty sets; Lucide stays. EntityIcon / IconPicker only show Lucide icons in designs.
- [GENERAL] Every card failed `IMBI_API_URL (or VITE_API_URL) is required`: `api/client.ts` throws at import. build.sh sets `VITE_API_URL=/api`.
- [GENERAL] shadcn-style flat exports (`DialogContent`, `SelectItem`, ...) are sub-parts, excluded from cards via `componentSrcMap: null`; they stay on `window.ImbiUI` and appear inside the root component's preview.
- [GENERAL] `ImbiProvider` (lib-build/ImbiProvider.tsx) = QueryClient + MemoryRouter + ThemeProvider + Toaster; `cfg.provider`. Excluded from cards.
- [GENERAL] Fonts: since #332 the app self-hosts `@fontsource-variable/inter` and `@fontsource-variable/jetbrains-mono` (imported in index.css). Vite lib mode inlines them as data URIs in `style.css`, so they ship inside `_ds_bundle.css` (no `fonts/` dir). The plain `Inter` / `JetBrains Mono` / `Fira Code` names are never-reached fallbacks in the font stacks -> `runtimeFontPrefixes`. Risk: the `Inter` prefix also matches `Inter Variable`, so a `[FONT_MISSING]` for it would be hidden if the import is ever removed.
- [GENERAL] The converter flattens props but leaves referenced named types undeclared (`ProjectSchemaSectionProperty`, `DynamicSchema`, `ReleaseTrainStop`, option types). `cfg.dtsPropsFor` holds the 9 affected props bodies with those types inlined (generated from the emitted body + source types). If the source types change, regenerate them - they do not update on their own.

## Preview authoring
- [GENERAL] Previews import from `'imbi-ui'` (all ui/ exports incl. sub-parts like `DialogContent`, `SelectItem`) and may import `lucide-react` icons directly. Style layout glue with the app's Tailwind classes (only classes the app already uses exist in the compiled CSS).
- [GENERAL] Dialog: `DialogHeader` and `DialogFooter` carry their own `p-6` + borders; the body between them needs its own `p-6` wrapper (app pattern, e.g. NewOpsLogDialog). Without it, content sits flush with the dialog edge. AlertDialog is different: `AlertDialogContent` has `p-6 gap-4` itself and its Header/Footer have no padding - no body wrapper.
- [GENERAL] `cardMode: "single"` shows the ALPHABETICALLY first export (esbuild sorts the namespace) unless `overrides.<Name>.primaryStory` is set. Every single-mode component sets `primaryStory`.
- HoverCardContent has no default width; give it `w-80`.
- Command: the empty state needs a controlled `CommandInput value` (`defaultValue` does not filter).
- [GENERAL] Overlay components (dialogs, popovers, tooltips, menus, selects) render in the open state (`open` / `defaultOpen`) and use `cardMode: "single"` with `viewport: "720x480"` (preset in config).
- [GENERAL] Storied components (Badge, Card, ScoreBadge, SegmentedControl, MarkdownEditor, Button): port the `ui/src/components/ui/*.stories.tsx` stories as the preview exports.
- [GENERAL] Arbitrary Tailwind classes the app never uses (e.g. `w-[36rem]`) are absent from the compiled CSS and silently do nothing. grep `ds-bundle/_ds_bundle.css` before using a class; prefer `w-64` / `w-80` / `w-96` / `max-w-xl w-full`.
- [GENERAL] The cell root is full width: a `justify-between` row stretches across ~800px. Give such rows a fixed width (`w-64` / `w-80`).
- [GENERAL] Components with no `open` prop (Combobox, FilterPopover) open via a preview-only `PreviewOnlyAutoOpen` helper (use exactly this name: the conventions header tells the design agent to omit it) that clicks the trigger once on mount. It is a capture device, not an app pattern: the conventions header tells the design agent not to copy it.
- EditableKeyValueMap takes `state` from `useEditableKeyValueMap` (now exported from the bundle via build.sh); the preview passes a no-op `onPatch` and module-level `serverMap` constants (a new object each render would re-sync drafts every render).
- IconUpload: uploaded-thumbnail state cannot render (needs `/uploads/<id>` from the API; `data:` URIs fail its check). Only empty states are previewed. IconPicker: open grid opens only from inside; only closed states are previewed.
- [GENERAL] Capture freezes the clock at 2024-05-15T12:00:00Z; product cards use the real clock. Relative dates (RelativeTime, AttributeValue color-age) are offsets from `Date.now()` (an `ago(seconds)` helper), never fixed ISO literals, or the live card reads "2y ago".
- Inline-edit components save via `onCommit` (not `onSave`); editing state is internal (`useInlineEdit`), opened in previews by `PreviewOnlyAutoOpen` clicking the `[role="button"]` display.
- AttributeValue: threshold maps (`color-age`/`color-range`) match in key order, first match wins. `icon-map` omitted: the component calls sync `getIcon()`, which returns the ExternalLink fallback before the Lucide set loads and never re-renders (possible app bug; EntityIcon uses `useIcon`).
- MarkdownPreview: lists render without markers - preflight `list-style:none`, not restored by `.document-markdown` in ui/src/index.css. Same in the app (source issue, preview left faithful).
- UserIdentity: Gravatar does not load in capture; initials fallback is the component's own.
- Inline-edit rows follow the app layout: `flex items-center justify-between border-b border-tertiary py-1.5 last:border-0`, label `text-sm text-tertiary`, in a `w-96`. InlineField shows formatted `display` nodes ("Tier 2", "99.9%"), not raw values. InlineSelect/Date/MultiSelect/Array open popovers when editing -> single mode, `primaryStory: Editing`.
- Keystroke previews set `isMac` so output does not depend on the capture browser. Legacy `Skeleton` is deliberately faint (`bg-tertiary/30`, deprecated); `Sk`/`SkText`/`Swap` are the current primitives.
- EntityIcon / IconPicker: only `lucide-*` values resolve (other sets stubbed, see Setup).

## Known render warns
- none: the final validate printed no warn lines.

## Re-sync risks
- `lib-build/` is a hand-built library pipeline around an app. If `ui/vite.config.ts` gains plugins/defines the components depend on, or `api/client.ts` changes its URL check, mirror it in `lib-build/vite.config.ts` / `build.sh`.
- New files in `ui/src/components/ui/` are picked up automatically; new compound sub-parts appear as extra cards until added to `componentSrcMap: null`.
- `dtsPropsFor` (9 components) is a snapshot of the props with inlined types - it goes stale when those props or `ProjectSchemaSectionProperty`/`DynamicSchema`/`Environment` change. Regenerate from the emitted `.d.ts` + source types.
- Icon sets other than Lucide are stubbed (size cap). Designs cannot show si-/aws/devicon/tabler/phosphor icons.
- Fonts are the app's own variable fonts inlined in the CSS (525 KB stylesheet). `runtimeFontPrefixes` hides FONT_MISSING for `Inter*` / `JetBrains Mono*` - check the families by hand if index.css font imports change.
- Previews tied to internals: EditableKeyValueMap (hook options), `PreviewOnlyAutoOpen` clicks on `[role="button"]` / triggers (inline-edit, Combobox, FilterPopover) - a DOM change in those components silently stops the open state; re-grade after edits there.
- Partial coverage: IconUpload (empty only), IconPicker (closed only), AttributeValue (no icon-map), Slider (no disabled cell).
- Source bugs found (not fixed): MarkdownPreview list markers, AttributeValue icon-map sync `getIcon()`, Slider disabled styling. When fixed upstream, extend those previews.
- Toolchain: node 26, vite 6, tailwind 4.3, storybook 10 (the 6 stories were ported, not compared against Storybook).
