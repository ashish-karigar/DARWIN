# DARWIN Keyboard Behavior

## Shortcuts

| Action | Shortcut |
| --- | --- |
| Open or close the app launcher | Command+K on macOS, Ctrl+K elsewhere |
| Switch to the next app window | Ctrl+Tab |
| Switch to the previous app window | Ctrl+Shift+Tab |
| Open or focus Assistant | Command+Shift+A on macOS, Ctrl+Shift+A elsewhere |

## Escape priority

Escape performs at most one action, in this order:

1. Close the app launcher or another active shell overlay.
2. Restore the focused window if it is maximized.
3. Otherwise, leave application state unchanged.

Escape does not close an application window. Destructive or lossy behavior must always use an explicit control.

## Text-entry protection

The shell does not intercept shortcuts when the keyboard event originates from an input, textarea, select, or editable element. An active application therefore owns its text-entry keystrokes. Shell overlays, such as the launcher search field, handle their own local Escape behavior.
