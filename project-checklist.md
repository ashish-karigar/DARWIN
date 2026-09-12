# DARWIN UI Project Checklist

## Project goal

Build the first usable DARWIN desktop shell: an OS-like interface that runs on top of the host operating system, launches native DARWIN apps and sandboxed web apps, connects to the existing Python assistant, and routes human input through a shared input system that can later accept gestures, voice, gamepads, and remotes.

The first release is a vertical slice, not a complete operating system. It must prove that the shell, application runtime, assistant, and input architecture work together before Netflix/Prime DRM support or gesture recognition is added.

## What “complete” means

Milestone 1 is complete only when all of the following are true:

- [ ] One command starts the DARWIN UI and Python service in development.
- [ ] DARWIN displays a full-screen-capable desktop, status bar, dock, and app launcher.
- [ ] The user can open a native Settings app and a sandboxed YouTube web app.
- [ ] App windows can be focused, moved, minimized, maximized, restored, and closed.
- [ ] The active app and window stacking order behave predictably.
- [ ] The user can send a text message to the existing Python supervisor and see its response in the Assistant app.
- [ ] Assistant connection, listening, thinking, speaking, error, and confirmation states can be represented in the UI.
- [ ] Mouse and keyboard actions pass through a typed input-routing boundary.
- [ ] Web apps run in isolated persistent sessions without Node.js access.
- [ ] App manifests are validated before an app can launch.
- [ ] UI, backend, and application-runtime errors are visible and recoverable.
- [ ] Automated tests cover the critical window, app-runtime, protocol, and backend behavior.
- [ ] A clean setup can be installed and run by following the README.
- [ ] No tokens, cookies, passwords, or private assistant data are committed to the repository or printed in normal logs.

## Scope for Milestone 1

### Included

- Electron desktop runtime
- React and TypeScript UI
- DARWIN desktop, status bar, dock, launcher, and window chrome
- Native DARWIN application runtime
- Sandboxed web application runtime
- Settings app
- YouTube proof-of-concept app
- FastAPI/WebSocket bridge to the existing Python assistant
- Text assistant interaction
- UI representation of voice and safety states
- Mouse and keyboard input routing
- SQLite-backed local preferences where persistence is needed
- Development scripts, tests, documentation, and basic packaging preparation

### Explicitly deferred

- Building a new operating-system kernel or device drivers
- Netflix and Prime Video production support
- DRM/Widevine guarantees
- Hand tracking and gesture recognition
- Autonomous clicking inside third-party websites
- Public app store or third-party app SDK
- Multi-user accounts and cloud synchronization
- Final visual polish, code signing, and production auto-update

## Architecture decisions

- **Desktop runtime:** Electron with TypeScript.
- **UI:** React, Vite, and Tailwind CSS.
- **UI state:** Zustand.
- **Assistant runtime:** Existing Python 3.11 code.
- **Local API:** FastAPI with WebSockets and a small health endpoint.
- **Persistence:** SQLite for DARWIN-owned state; Electron persistent session partitions for web logins.
- **Web content:** `WebContentsView`, not an iframe or Electron `<webview>`.
- **Security:** Context isolation and sandboxing enabled; Node integration disabled for remote content.
- **Input:** All devices emit normalized `DarwinInputEvent` messages through one router.
- **Process ownership:** Electron starts, monitors, and cleanly stops the local Python service in packaged operation.

## Working rules

- Complete tasks in checklist order unless a task explicitly says it can run in parallel.
- Do not mark a task complete until its acceptance checks pass.
- Add or update tests in the same task as the behavior they verify.
- Record material architecture changes in the Decision Log at the bottom of this file.
- Keep third-party web-app logic out of the core window manager.
- Never expose Electron or Node APIs directly to remote web content.
- Preserve the current terminal assistant until the UI path reaches feature parity for basic text interaction.

---

## Phase 0 — Baseline and project foundation

### UI-001 — Record and verify the current backend baseline ✅

**Depends on:** Nothing

- [x] Run the existing Python test suite and record any pre-existing failures.
- [x] Verify text mode can send one prompt through `run_supervisor`.
- [x] Document the supported Python version and current setup command.
- [x] Confirm `.env` and generated voice/model data are ignored appropriately.

**Done when:** Existing behavior is documented, tests have a known baseline, and UI work can be distinguished from pre-existing failures.

### UI-002 — Scaffold the frontend workspace ✅

**Depends on:** UI-001

- [x] Create `darwin-ui/` with React, TypeScript, and Vite.
- [x] Add Electron main and preload entry points.
- [x] Add Tailwind CSS and the initial global theme tokens.
- [x] Add linting, formatting, type-checking, and unit-test commands.
- [x] Add scripts for UI-only and Electron development.
- [x] Confirm hot reload works without weakening production security settings.

**Done when:** A minimal Electron window renders a React screen, type-checking passes, and the development process exits cleanly.

### UI-003 — Define shared contracts ✅

**Depends on:** UI-002

- [x] Define `AppManifest`, `AppInstance`, `WindowState`, and `WindowBounds` types.
- [x] Define `DarwinInputEvent` as a discriminated union.
- [x] Define assistant request, response, state, confirmation, and error messages.
- [x] Add runtime validation for data crossing Electron IPC and WebSockets.
- [x] Add protocol version fields and an unsupported-version error.
- [x] Write unit tests for valid and invalid messages.

**Done when:** Electron, React, and Python have an explicit, versioned communication contract and malformed messages are rejected safely.

---

## Phase 1 — Desktop shell

### UI-010 — Create the DARWIN visual foundation ✅

**Depends on:** UI-002

- [x] Define colors, typography, spacing, elevation, radii, animation timing, and focus styles.
- [x] Implement light/dark-ready design tokens, even if only one theme ships initially.
- [x] Create reusable button, icon-button, tooltip, menu, and panel components.
- [x] Add keyboard-visible focus indicators.
- [x] Confirm the base layout works at 1280×720, 1920×1080, and a resizable desktop window.

**Done when:** Shell components use shared tokens and remain readable and operable at all target sizes.

### UI-011 — Build the desktop surface ✅

**Depends on:** UI-010

- [x] Implement desktop background and workspace area.
- [x] Implement status bar with time and assistant connection state.
- [x] Implement dock with pinned and running-app indicators.
- [x] Implement app launcher with search and keyboard navigation.
- [x] Add empty, loading, and error states.

**Done when:** The user can navigate the shell with mouse and keyboard, open/close the launcher, and select a placeholder app.

### UI-012 — Implement the window-state store ✅

**Depends on:** UI-003, UI-011

- [x] Store open windows by stable instance ID.
- [x] Track focused window and deterministic z-order.
- [x] Support open, focus, move, resize, minimize, maximize, restore, and close actions.
- [x] Constrain title bars to the visible workspace.
- [x] Define behavior for single-instance and multi-instance apps.
- [x] Unit-test every state transition and edge case.

**Done when:** Window behavior is deterministic under tests and no operation can leave an unreachable focused window.

### UI-013 — Build window chrome and pointer behavior ✅

**Depends on:** UI-012

- [x] Render title bar, icon, title, and window controls.
- [x] Implement dragging and edge/corner resizing.
- [x] Implement minimize, maximize, restore, and close.
- [x] Bring a clicked window to the front.
- [x] Add sensible minimum window dimensions.
- [x] Prevent pointer actions from leaking into content while dragging/resizing.

**Done when:** Two placeholder apps can be independently manipulated without focus, stacking, or pointer errors.

### UI-014 — Add shell keyboard behavior ✅

**Depends on:** UI-012

- [x] Add a shortcut to open/close the launcher.
- [x] Add task switching between open windows.
- [x] Add Escape/back behavior with a documented priority order.
- [x] Add a shortcut to summon the Assistant app.
- [x] Ensure shortcuts do not capture text intended for the focused app.

**Done when:** Core shell navigation is usable without a mouse and does not interfere with normal text entry.

---

## Phase 2 — Application runtime

### UI-020 — Implement app manifests and registry ✅

**Depends on:** UI-003

- [x] Define the manifest schema and supported app types: `native`, `web`, and reserved `external`.
- [x] Add ID, name, icon, entry/URL, permissions, session, and instance-policy fields.
- [x] Validate manifests at startup and skip invalid apps with a useful error.
- [x] Implement registry lookup, listing, and launcher ordering.
- [x] Add registry and validation tests.

**Done when:** The launcher is populated from validated manifests rather than hard-coded components.

### UI-021 — Implement native DARWIN app hosting ✅

**Depends on:** UI-013, UI-020

- [x] Map native manifest entries to React app components.
- [x] Provide each app with instance, window, command, and permission context.
- [x] Add app-level error boundaries.
- [x] Render a recovery screen when an app crashes.
- [x] Confirm closing one app does not affect another.

**Done when:** Multiple native apps can run inside separate DARWIN windows with isolated errors.

### UI-022 — Build the Settings app ✅

**Depends on:** UI-021

- [x] Add General, Appearance, Input, Assistant, Privacy, and About sections.
- [x] Present Settings as a full-screen system surface instead of a desktop window.
- [x] Add first-start service setup for Groq, Ollama, Fish Audio, and Spotify.
- [x] Store API credentials through Electron's encrypted credential bridge without exposing retrieval to the renderer.
- [x] Persist window behavior, input, assistant, service-state, and appearance preferences locally.
- [x] Show backend, UI, and protocol version information.
- [x] Provide a reset-to-defaults action with confirmation.
- [x] Add tests for preference validation, persistence, onboarding, credential submission, and full-screen behavior.

**Done when:** Settings and first-start setup run full screen, preferences survive a restart, credentials are stored securely, automated checks pass, and the visual result is approved.

### UI-023 — Implement sandboxed web-app hosting ✅

**Depends on:** UI-013, UI-020

- [x] Create and destroy `WebContentsView` instances from the Electron main process.
- [x] Synchronize native view bounds with its DARWIN window.
- [x] Use a separate persistent session partition per app.
- [x] Disable Node integration and enable context isolation and sandboxing.
- [x] Deny web permission requests and downloads by default.
- [x] Allow navigation only to approved origins and handle external links safely.
- [x] Handle loading, offline, certificate, renderer-crash, and unsupported-page states.
- [x] Ensure unfocused, moving, hidden, and minimized web apps do not intercept pointer input.
- [x] Hide hosted web content behind full-screen system surfaces such as Settings.
- [x] Add security-focused tests for manifest URL and IPC validation.

**Done when:** A remote page can run in a managed window without gaining access to DARWIN or Node privileges.

### UI-024 — Add the YouTube proof-of-concept app ⚠️ Glitchy

**Depends on:** UI-023

- [x] Create a YouTube web-app manifest.
- [x] Confirm navigation and sign-in state persist across restarts.
- [x] Verify video playback, audio, fullscreen transitions, and back navigation.
- [x] Verify minimize/restore does not break playback or view bounds.
- [x] Document known limitations discovered during testing.

**Current status:** Usable, but still glitchy. Fullscreen corner resizing and some
embedded-view transitions are not reliable enough to call polished. Defer further
YouTube-specific work while the rest of the shell progresses.

**Done when:** YouTube can be opened and operated by the human using the normal mouse and keyboard inside DARWIN.

### UI-025 — Add the OS neural activity core

**Depends on:** UI-021

- [x] Render a projected 3D neuron-and-connection sphere on the main OS workspace.
- [x] Keep the Assistant app out of scope until its runtime and interaction design begin.
- [x] Animate slow depth-aware rotation in the muted idle state.
- [x] Illuminate only the region associated with an activity event.
- [x] Expose a `darwin:activity` event interface for future command and skill signals.
- [x] Respect the operating system's reduced-motion preference.
- [ ] Visually approve the animation language.

**Done when:** DARWIN has an approved idle/thinking/skill visual that can be driven by runtime events in UI-030 and UI-031.

### UI-026 — Build the macOS Reminders app

**Depends on:** UI-021

- [x] Add a minimal native Reminders app manifest and shell window.
- [ ] Build a small signed Swift/EventKit bridge for macOS Reminders access.
- [ ] Add `NSRemindersFullAccessUsageDescription` and request permission only when the user connects Reminders.
- [ ] List reminder calendars and reminders through validated Electron IPC.
- [ ] Create, edit, complete, and delete reminders in EventKit.
- [ ] Support titles, notes, due dates, priorities, lists, and recurrence where EventKit permits.
- [ ] Observe EventKit store changes and refresh DARWIN without creating duplicates.
- [ ] Handle unavailable, denied, restricted, and revoked permission states.
- [x] Store EventKit identifiers instead of maintaining a second reminder source of truth.
- [ ] Add Swift bridge, IPC validation, and UI behavior tests.

**Done when:** Changes flow both ways between DARWIN and Apple Reminders with explicit user permission.

---

## Phase 3 — Python service and assistant UI

### UI-029 — Connect the initial Python-owned activity states ✅

**Depends on:** UI-003, UI-025

- [x] Start a minimal Python state service with the Electron shell.
- [x] Authenticate commands sent to the child service with an ephemeral secret.
- [x] Validate Python state messages before exposing them to the renderer.
- [x] Keep the intelligence surface at OS level rather than opening an Assistant app.
- [x] Keep a validated state-preview bridge for diagnostics without exposing test controls in the OS UI.
- [x] Render a soft listening glow on the neural core.
- [x] Make the core grow and contract organically while speaking.
- [x] Publish listening and transcribing states from real microphone/Whisper work.
- [x] Analyze microphone amplitude directly in the trusted shell so the inner orb reacts immediately without waiting for backend state.
- [x] Publish thinking around the current supervisor execution path.
- [x] Publish speaking for the complete TTS playback lifecycle, animate a stronger irregular expansion, and return to idle.
- [x] Stop the state-service child when the DARWIN window closes.

**Scope boundary:** This slice observes the existing voice and reasoning lifecycle.
It does not yet add OS-level voice activation, conversation submission, response
streaming, or the transcript rail.

**Done when:** Python can publish idle, listening, or speaking state through the
desktop boundary and the neural core renders each state without a separate app.

### UI-030 — Extract a reusable assistant runtime

**Depends on:** UI-001, UI-003

- [ ] Separate terminal input/output concerns from assistant orchestration in `main.py`.
- [ ] Expose a reusable method for submitting messages to the single OS-level DARWIN session.
- [ ] Preserve the existing action context and safety policy.
- [ ] Make thinking, skill, response, and error states observable without relying on `print`.
- [ ] Route runtime activity events to the desktop neural core.
- [ ] Keep terminal text mode working.
- [ ] Add regression tests for terminal and reusable-runtime paths.

**Done when:** The same single-session DARWIN runtime can serve terminal and OS clients without duplicated agent logic.

### UI-030A — Add the OS transcript surface

**Depends on:** UI-030, UI-031

- [ ] Add a restrained transcript rail to the right side of the main OS workspace.
- [ ] Show human and DARWIN messages in one continuous generalized session.
- [ ] Keep the transcript available across app launches without turning it into an app window.
- [ ] Stream partial DARWIN responses and display runtime status without chat-style visual clutter.
- [ ] Provide keyboard and voice entry points into the same session.
- [ ] Persist and restore the session according to the memory policy.

**Done when:** The user can converse with DARWIN from the OS itself and see both sides of the active session in the right-side transcript.

### UI-031 — Add the local FastAPI service

**Depends on:** UI-030

- [ ] Add a loopback-only FastAPI server.
- [ ] Add `/health` with protocol and backend version information.
- [ ] Add a WebSocket endpoint for versioned DARWIN messages.
- [ ] Validate all incoming messages and cap message sizes.
- [ ] Support session IDs and request correlation IDs.
- [ ] Return structured errors rather than raw tracebacks.
- [ ] Add API and WebSocket tests.

**Done when:** A test client can connect, submit a message, observe states, receive the correlated answer, and recover from a malformed request.

### UI-032 — Model assistant state events

**Depends on:** UI-031

- [ ] Emit connected, idle, listening, transcribing, thinking, speaking, and error states.
- [ ] Emit partial/final response events if supported by the current runtime.
- [ ] Convert safety confirmation requests into structured UI events.
- [ ] Accept confirmation or rejection responses from the authorized client.
- [ ] Define cancellation and timeout behavior.
- [ ] Test success, failure, cancellation, and confirmation flows.

**Done when:** The UI never needs to infer assistant state by parsing natural-language output.

### UI-033 — Build the Assistant app

**Depends on:** UI-021, UI-032

- [ ] Add conversation history and text composer.
- [ ] Display connection and assistant activity states.
- [ ] Correlate pending user messages with responses.
- [ ] Render structured errors and retry controls.
- [ ] Render safety confirmations with clear action and risk information.
- [ ] Support confirmation, rejection, and timeout.
- [ ] Preserve a local conversation view across app minimize/restore.

**Done when:** The user can complete a text conversation and safely approve/reject an action entirely through the DARWIN UI.

### UI-034 — Manage the Python process from Electron

**Depends on:** UI-031, UI-033

- [ ] Start the backend on an available loopback port in development/packaged modes.
- [ ] Authenticate the local UI-to-backend connection with an ephemeral secret.
- [ ] Detect backend readiness before connecting.
- [ ] Display startup failure and reconnect states.
- [ ] Restart after an unexpected backend crash with a bounded retry policy.
- [ ] Shut down the child process when DARWIN exits.
- [ ] Verify no orphan process remains after normal exit or UI crash recovery.

**Done when:** DARWIN owns the complete backend lifecycle and communicates only through an authenticated local connection.

---

## Phase 4 — Unified input system

### UI-040 — Implement the input router

**Depends on:** UI-003, UI-012

- [ ] Define device-independent pointer, navigation, text, media, and command events.
- [ ] Normalize mouse and keyboard input into those events.
- [ ] Route events to the focused app or shell according to documented precedence.
- [ ] Support input capture during drag, resize, menus, and dialogs.
- [ ] Add event source, timestamp, and confidence metadata.
- [ ] Reject stale, malformed, or unauthorized synthetic events.
- [ ] Unit-test focus routing and capture precedence.

**Done when:** Shell behavior is driven through the input router and no component needs to know whether an eligible action originated from a mouse or future gesture source.

### UI-041 — Add an input-debug overlay

**Depends on:** UI-040

- [ ] Show the most recent normalized input event in development mode.
- [ ] Show focused target and current capture owner.
- [ ] Add a toggle in Settings that is unavailable in production builds by default.
- [ ] Redact typed text and sensitive payloads from the overlay and logs.

**Done when:** Developers can diagnose routing without recording private input.

### UI-042 — Add a simulated gesture source

**Depends on:** UI-040

- [ ] Map development shortcuts to representative gesture-generated events.
- [ ] Simulate cursor movement, click, drag, back, and launcher commands.
- [ ] Mark simulated events with `source: "gesture-simulator"`.
- [ ] Verify apps operate identically under mouse and simulated gesture events.

**Done when:** The gesture integration boundary is proven without requiring a camera or recognition model.

---

## Phase 5 — Reliability, security, and accessibility

### UI-050 — Complete the application security review

**Depends on:** UI-023, UI-034, UI-040

- [ ] Verify no remote page has Node integration or unrestricted preload APIs.
- [ ] Audit navigation, popup, download, permission, and protocol handlers.
- [ ] Restrict IPC channels and validate sender identity.
- [ ] Confirm backend binding is loopback-only and locally authenticated.
- [ ] Confirm secrets and session cookies are not written to logs.
- [ ] Add a concise threat model covering malicious web content and synthetic input.
- [ ] Resolve all critical/high findings before release.

**Done when:** The threat model and automated checks demonstrate that a compromised web app cannot invoke privileged DARWIN actions directly.

### UI-051 — Add graceful failure and recovery

**Depends on:** UI-024, UI-034

- [ ] Recover from a crashed native app view.
- [ ] Recover from a crashed web renderer.
- [ ] Recover from backend disconnect/restart.
- [ ] Handle missing or invalid app manifests.
- [ ] Preserve unaffected windows during a single-app failure.
- [ ] Provide actionable user-facing error messages.

**Done when:** Each major process or app can fail independently without forcing the user to restart DARWIN.

### UI-052 — Accessibility and reduced-motion pass

**Depends on:** UI-014, UI-033

- [ ] Verify keyboard reachability and logical focus order.
- [ ] Add accessible names to icon-only controls.
- [ ] Confirm status is not communicated using color alone.
- [ ] Honor reduced-motion preferences.
- [ ] Check common desktop zoom/scaling settings.
- [ ] Run automated accessibility checks on native DARWIN surfaces.

**Done when:** All core native flows work using keyboard-only input and have no critical automated accessibility violations.

### UI-053 — Performance pass

**Depends on:** UI-024, UI-033

- [ ] Measure cold start and time to interactive.
- [ ] Measure idle CPU/memory with no apps and with YouTube open.
- [ ] Confirm dragging/resizing remains responsive during playback.
- [ ] Prevent unnecessary React rerenders during pointer movement.
- [ ] Document baseline measurements and test machine details.

**Done when:** No known performance problem prevents smooth everyday mouse operation, and baseline numbers are recorded for regression comparison.

---

## Phase 6 — Integration and Milestone 1 release gate

### UI-060 — Add unified developer commands

**Depends on:** UI-034

- [ ] Add one command for dependency setup where practical.
- [ ] Add one command to start backend and desktop UI.
- [ ] Add one command for all unit/integration checks.
- [ ] Forward useful logs with clear process prefixes.
- [ ] Ensure Ctrl+C/normal exit stops all child processes.

**Done when:** A developer can set up, run, test, and stop DARWIN using documented commands.

### UI-061 — Add end-to-end smoke tests

**Depends on:** UI-024, UI-033, UI-040, UI-051

- [ ] Start DARWIN and confirm backend connection.
- [ ] Open, manipulate, and close Settings.
- [ ] Change and persist one preference.
- [ ] Open YouTube and verify its managed view appears.
- [ ] Send a deterministic assistant test message and receive a response.
- [ ] Exercise a safe confirmation flow.
- [ ] Verify clean shutdown.

**Done when:** The critical user journey passes repeatedly on the primary development machine.

### UI-062 — Write setup and architecture documentation

**Depends on:** UI-060

- [ ] Document prerequisites and installation.
- [ ] Document development and test commands.
- [ ] Explain the Electron/React/Python process model.
- [ ] Explain native versus web apps and manifest fields.
- [ ] Explain security boundaries and input routing.
- [ ] Add troubleshooting for ports, microphone permissions, and backend startup.
- [ ] List known limitations and deferred features.

**Done when:** A developer unfamiliar with the project can launch it without undocumented steps.

### UI-063 — Milestone 1 acceptance review

**Depends on:** UI-050, UI-052, UI-053, UI-061, UI-062

- [ ] Re-run every item in “What complete means.”
- [ ] Run the complete Python and UI test suites.
- [ ] Perform the smoke test on a clean checkout/environment.
- [ ] Review logs for secrets, tracebacks, and noisy debug output.
- [ ] Record remaining non-blocking limitations.
- [ ] Tag or otherwise record the accepted Milestone 1 revision.

**Done when:** Every completion criterion passes, there are no critical/high security defects, and remaining limitations are explicitly documented.

---

## Milestone 2 — Streaming compatibility spike

Start only after UI-063 is complete.

### UI-100 — Test Netflix compatibility

- [ ] Create a temporary isolated Netflix manifest/session.
- [ ] Test sign-in, profile selection, playback, audio, subtitles, fullscreen, and restart persistence.
- [ ] Record DRM, resolution, HDCP, and user-agent limitations.
- [ ] Decide between embedded `WebContentsView` and supported external-browser mode.

**Done when:** We have an evidence-based integration decision and do not claim unsupported playback capabilities.

### UI-101 — Test Prime Video compatibility

- [ ] Repeat the Netflix compatibility matrix for Prime Video.
- [ ] Record service-specific navigation and DRM limitations.
- [ ] Decide the supported launch mode.

**Done when:** Prime Video has a documented, tested integration mode or is explicitly marked unsupported.

### UI-102 — Add external-browser fallback mode

- [ ] Launch a supported browser or installed app using an allowlisted target.
- [ ] Track and focus the launched application where the host OS permits it.
- [ ] Keep DARWIN assistant controls accessible without attempting unsafe embedding.
- [ ] Clearly communicate when content is hosted by an external application.

**Done when:** DRM-restricted services remain launchable from DARWIN even when safe embedded playback is unavailable.

---

## Milestone 3 — Real gesture input

Start only after UI-042 and Milestone 1 are complete.

### UI-200 — Build the local vision service

- [ ] Capture camera frames locally with explicit permission and visible status.
- [ ] Detect hand landmarks with MediaPipe.
- [ ] Keep raw frames inside the vision process by default.
- [ ] Publish normalized landmark/gesture data at a bounded rate.
- [ ] Add start, stop, unavailable-camera, and permission-denied states.

### UI-201 — Implement stable pointing

- [ ] Map index-finger position to desktop coordinates.
- [ ] Add smoothing, dead zones, calibration, and confidence thresholds.
- [ ] Pause movement when tracking confidence is insufficient.
- [ ] Measure latency and cursor jitter.

### UI-202 — Implement the initial gesture vocabulary

- [ ] Pinch to click.
- [ ] Pinch-and-hold to drag.
- [ ] Open palm to pause gesture input.
- [ ] Horizontal swipe for back/forward.
- [ ] Deliberate launcher gesture.
- [ ] Add cooldown and hysteresis to prevent accidental activation.

### UI-203 — Gesture safety and usability review

- [ ] Require confirmation before gesture input can authorize risky actions.
- [ ] Provide a persistent visual indicator while camera input is active.
- [ ] Add immediate keyboard/mouse override and emergency disable.
- [ ] Test in varied lighting, distances, backgrounds, and skin tones.
- [ ] Document supported conditions and limitations.

**Milestone 3 is complete when:** A user can reliably launch and operate Settings and YouTube using gestures, while mouse/keyboard override remains immediate and no raw camera video is retained by default.

---

## Decision log

Add entries whenever a material choice changes.

| Date | Decision | Reason | Consequence |
| --- | --- | --- | --- |
| 2026-09-09 | Build an OS-like shell rather than a new OS kernel. | Delivers the intended experience while retaining mature host drivers, browsers, and security. | DARWIN initially runs on top of macOS and later other desktop platforms. |
| 2026-09-09 | Use Electron, React, and TypeScript for the shell. | The project needs desktop window control, embedded browser surfaces, and a mature UI ecosystem. | The desktop distribution includes Chromium/Node and must be hardened carefully. |
| 2026-09-09 | Keep the existing intelligence layer in Python. | Voice, agents, safety, tools, and memory already exist there. | A versioned local protocol is required between Electron and Python. |
| 2026-09-09 | Validate YouTube before Netflix and Prime Video. | It exercises managed web content without making DRM the foundation of the shell. | Streaming DRM work is a separate post-MVP compatibility spike. |
| 2026-09-09 | Normalize input before adding camera gestures. | Future inputs should reuse application behavior instead of creating gesture-specific UI paths. | Mouse, keyboard, voice, and gestures share one routing and permission model. |
| 2026-09-10 | Use a restrained, utility-first visual language. | DARWIN should feel like a precise operating environment rather than a generic AI landing page. | Prefer flat neutral surfaces, typography, spacing, and subtle borders; avoid decorative glow, gradient, glass-card, and promotional treatments. |
| 2026-09-10 | Treat Settings and initial service setup as full-screen system surfaces. | Configuration is a shell-level activity, not another floating app window. | Settings bypasses the window manager; first launch offers optional setup for supported backend services. |
| 2026-09-10 | Host remote apps in main-process-owned sandboxed views. | Remote pages must never receive renderer, preload, Node, or unrestricted navigation access. | Each app gets an isolated persistent session, validated IPC lifecycle, and an explicit origin allowlist. |
| 2026-09-10 | Make DARWIN intelligence an OS-level service, not an Assistant app. | General commands, transcription, reasoning, and responses belong to the shell's single continuous session. | The neural core and right-side transcript are persistent shell surfaces; a future Agent app is reserved for isolated project work. |
| 2026-09-10 | Preserve the current internal edge overlay as visual checkpoint `overlay-v1`. | The current theme-matched, inward-only dissolve is approved as the recovery baseline before reintroducing pointer clearing. | Pointer interaction may alter only the overlay mask; its gradients, color, shadow, clipping, and width baseline remain recoverable from the checkpoint record. |
| 2026-09-10 | Introduce Python integration as a narrow state-only child service before FastAPI and conversation wiring. | Listening and speaking visuals need a real process boundary, but the user explicitly deferred the full assistant stack. | UI-029 uses authenticated structured standard I/O; UI-030 and UI-031 still own reusable orchestration and FastAPI/WebSocket work. |

## Progress summary

- **Current milestone:** Milestone 1 — DARWIN Shell MVP
- **Current phase:** Phase 3 — Python service and assistant UI
- **Completed tasks:** UI-001, UI-002, UI-003, UI-010, UI-011, UI-012, UI-013, UI-014, UI-020, UI-021, UI-022, UI-023
- **Glitchy prototype:** UI-024 (YouTube); usable, with polish deferred
- **Completed state slice:** UI-029; Python-owned idle/listening/speaking events now drive the OS neural core
- **Next task:** Visually approve UI-029, then begin the reusable runtime in UI-030
- **Milestone status:** In progress
