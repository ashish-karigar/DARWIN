# DARWIN visual checkpoints

## overlay-v1 — 2026-09-10

This is the approved recovery baseline for DARWIN's internal application overlay.
It is intentionally recorded independently of the pointer-clear interaction.

- Scope: every app whose manifest uses `edgeEffect: "flow"`; document apps such as
  Reminders may opt out with `edgeEffect: "none"`.
- Containment: the effect is clipped inside the application window. Nothing may
  glow, shade, or spill outside its bounds.
- Theme: `#0c0c0d` in Dark and `#000000` in Projector Black.
- Gradient depth: solid edge at `0%`, the intermediate fade at `11%`, and fully
  transparent by `22%`.
- Shadow: inset only, `0 0 7.5rem 2.75rem`, at an 82% theme-color mix.
- Shape: four inward linear edge gradients plus the shell's centered radial
  vignette for native windows.
- Pointer-clear layer: a seven-rem soft radial mask. At rest its center is parked
  at `-999px`, which reproduces this checkpoint exactly.

If a later overlay experiment fails, restore the values above and disable only its
mask or pointer tracking. Do not reconstruct the baseline by eye.
