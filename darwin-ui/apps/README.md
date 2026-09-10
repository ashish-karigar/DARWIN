# DARWIN Application Manifests

Each bundled application lives in its own directory and provides a `manifest.json`. The application registry validates every manifest before exposing it to the shell.

Required fields:

- `id`: stable lowercase application identifier
- `name`: user-facing name
- `version`: application version
- `type`: `native`, `web`, or `external`

Native apps require `entry`. Web apps require `url`. Optional metadata includes `description`, `icon`, `allowedOrigins`, `permissions`, `session`, `instancePolicy`, `pinned`, and `launcherOrder`.

Invalid and duplicate manifests are skipped. The registry preserves the first valid app with a given ID and records structured diagnostics for rejected candidates. `launcherOrder` sorts applications numerically, with the app name used as the stable tie-breaker.

## Web-app limitations

- A hosted page may take a few seconds to start because its sandboxed Chromium view is created on demand.
- Login cookies and cache persist per app, but closing an app destroys its live page process.
- Minimized media apps remain alive offscreen so playback can continue; closing them stops playback.
- Navigation is restricted to manifest-approved HTTPS origins, so authentication providers must be explicitly allowlisted.
- Downloads, device access, and web permissions are denied unless DARWIN adds a narrowly scoped manifest permission.
- Cinema-mode title-bar reveal is implemented through the hosted page's top edge and may require per-site compatibility work.
