# DARWIN UI Protocol

DARWIN UI messages use protocol version `1.0`. TypeScript contracts and runtime validators live in `darwin-ui/shared/contracts.ts`; matching Python/Pydantic models live in `src/app/protocol/schemas.py`.

Every WebSocket message contains:

- `protocolVersion`
- `messageId`
- `timestamp`
- a discriminating `type`

Client messages cover session negotiation, assistant requests, cancellation, and confirmation responses. Server messages cover session readiness, assistant state, responses, confirmation requests, and structured errors.

App and window contracts define manifests, running instances, bounds, focus, stacking, and window modes. Input contracts normalize pointer, navigation, text, media, and command events with a source and timestamp.

Unknown fields, malformed payloads, and unsupported protocol versions are rejected at runtime. Python models must be serialized with aliases, for example `model_dump(by_alias=True, mode="json")`, to produce the camelCase wire format used by TypeScript.
