# FA Foundry UI spacing and reading polish

The five reported defects are the acceptance criteria: crowded spacing, overemphasized gold borders, poor result/draft reading hierarchy, inconsistent native/renderer typography, and a crude task sidebar.

## Concrete layout contract

- Keep the bundled Noto Sans SC font in both renderers. Navigation and controls use 14px/22px; labels 13px/20px; metadata 12px/18px; conversation and document prose 16px/28px. Never shrink document type at narrow widths.
- Use 8px label/control spacing, 12px related actions, 20px form rows and section content, 32px between reading sections. Workspace and conversation gutters are 24px; narrow panes retain at least 20px. Scroll content has 24px top and 32px bottom breathing room.
- Neutral borders for idle/hover controls. Focus uses one 1px contrasting stroke, with no ring/outline/border stacking. Selection uses a quiet neutral surface; gold is limited to a short active-tab underline and restrained focus indication.
- Results lead with question/title and scope, then output; controls, history, and evidence remain available without dominating reading. Draft prose uses a maximum measure of 42em (roughly 42 Chinese characters), 16px/28px body, 24px title, 20px section headings, and 16–20px paragraph gaps. Tables use neutral hairlines, no tinted headers or vertical grids, and at least 10px vertical cell padding.
- Sidebar uses a 256px dock / 288px drawer, a titled top row, an integrated search control, 14px task titles with up to two lines, aligned period metadata, and a separated bottom library action. Preserve keyboard navigation, focus return, Escape, inert background, native-view hiding, resizing and task selection.

## Ordered cleanup

1. Capture baseline screenshots and a visual verdict; inspect current regression coverage before editing.
2. Repair shared tokens, control focus and spacing. Remove conflicting duplicate declarations instead of adding unlayered overrides.
3. Apply the contract to native conversation, result/draft reading, and sidebar in bounded file scopes. Fix actual details-content spacing rather than relying on flex gap through a details anonymous content box.
4. Run component and native adapter regression tests, TypeScript checks and build. Preserve all financial values, original draft body, exports, quality warnings, task history, and source workbooks.
5. Render the same real task in dark/light, split/results focus and expanded sidebar states. Inspect focus, dropdowns, expanded forms, long document and wide tables. Record a verdict before each further visual edit.
6. Package the verified source, replace the installed app atomically, launch it and verify both renderers and the existing task. Remove only the temporary old bundle after successful verification.

## Scope boundaries

No new dependencies, backend computation changes, financial quality-rule changes, workbook edits, or model reruns. Kami supplies reading principles, not a replacement app theme or font. Existing root-level untracked package files remain outside this change.

## Evidence

Build and visual evidence: `build/ui-reading-polish-20260908/`.
Visual verdict: `.omx/state/ui-reading-polish-20260908/ralph-progress.json`.
