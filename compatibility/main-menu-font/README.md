# STAR PROGRAM menu font overlay

This directory contains additive generated font backgrounds and a compact glyph
map. It contains no imported item icons. Render the vanilla MiniMessage
`<sprite>` objects listed in `glyph-map.json` directly.

Run `game/tools/main-menu-font-pack.py prepare` with Python and Pillow to refresh
the generated source assets, glyph map, overlay ZIP and preparation report. This
checks the merged archive in memory but does not write a full game pack.

Run the same script with `build` to write a complete staged pack here. Every run
reads `game/config/resource-pack.json` afresh, locates a local archive matching
that pin, and checks its SHA-256, SHA-1 and length. An optional `--base` path must
also match the current pin. The builder never publishes or updates that pin.
Existing ZIP local records, compressed data, central-directory metadata, entry
contents and archive comment are retained. All added entries have deterministic
timestamps, permissions and compression. The final ZIP must stay below 40 MiB.

Generated assets are tracked in `generated-files.json`. Differing unowned files
or manual changes to a tracked asset are preserved by refusing to overwrite them.
The complete staged pack is not written by `prepare`.

## Glyph map contract

- `fonts.panel` and `fonts.space`: `star_program:menu`.
- `fonts.small`: `star_program:menu_small`, height 6, ascent 5. It references the
  client's vanilla ASCII texture and falls back to `minecraft:default`.
- `glyphs.card[role][state][strip]`: 56 GUI pixel painted background.
- `glyphs.panel[role][state][strip]`: 220 GUI pixel painted background.
- Roles: `operator`, `scientist`, `maintenance`, `security`, `raider`.
- States: `normal`, `selected`, `locked`.
- Strips: `top`, `middle`, `bottom`.
- `spaces[String(advance)]`: exact invisible advance, any integer from -256 to
  256, inclusive, in `fonts.space`. No legacy negative-space glyph is modified.
- `metrics.small[character]` and `metrics.default[character]`: ASCII advances for
  unbolded, nonitalic text. Native bitmap rounding is included. Compact
  `Maintenance` measures 50 GUI pixels, fitting a 56 pixel card with 3 pixel
  side padding. Long job ranks need deliberate line breaks.

Each bitmap glyph paints 10 pixels high at ascent 8. Newlines advance 9 pixels,
so adjacent strips overlap by 1 pixel. Twelve rows paint 109 pixels. Reserve an
extra bottom pixel beyond the nominal 108 pixel text layout.

## One cell on one text row

For a background with painted width `W` and raw bitmap advance `A`:

1. Emit the background glyph with the panel font.
2. Emit `spaces[-A]` to return to the cell's left edge.
3. Emit `spaces[floor((W-contentWidth)/2)]`.
4. Emit the content using its own font or native sprite object.
5. Emit `spaces[W-left-contentWidth]`.
6. Between cards emit `spaces[2]`. Omit this after the final card.

The raw bitmap advance includes Minecraft's extra trailing pixel. Cards paint
56 but advance 57. Main panels paint 220 but advance 221. Five cards with four
gaps finish at 288 GUI pixels. During composition the last background briefly
advances to 289 before the negative reset. A native `plain_message` width of
300 avoids premature wrapping. Construct row boundaries explicitly rather than
relying on character wrapping through the negative-space components.

Use white, no bold, no italic and no shadow for the colored backgrounds and
spacing. Actual labels remain styled text. Set the same card click event on all
of that cell's components, including its backgrounds, spacing and text. Choose
`top` for line 0, `bottom` for the final line and `middle` for all intervening
lines. Selected borders are light. Locked strips contain the darkened colors,
so no oversized translucent glyph is needed.

Call the existing `progress bar` helper for progress. Use length 40 in compact
cards and length 100 in wide panels. Keep its returned styled component in
`minecraft:default`. Each default `|` plus existing U+EEFE negative-space glyph
advances 1 pixel. Do not rewrite the helper or let the compact font leak into it.

The font PUA allocation is U+E000 through U+E059 for bitmap strips, and U+E100
through U+E300 for exact spacing. These mappings exist only in the new menu font.
The existing default, image, negative-space and STFR font files stay untouched.
