import base64

from app.services.vision import Detection, VisionModel, handle_request


class StubModel(VisionModel):
    def detect(self, encoded_image: str) -> list[Detection]:
        assert base64.b64decode(encoded_image) == b"image"
        return [Detection("person", 0.92, 0.1, 0.2, 0.3, 0.4)]


def test_vision_worker_returns_normalized_detections() -> None:
    result = handle_request(
        StubModel(),
        {
            "protocolVersion": "1.0",
            "requestId": "frame-1",
            "type": "vision.detect",
            "image": base64.b64encode(b"image").decode(),
        },
    )

    assert result == {
        "protocolVersion": "1.0",
        "requestId": "frame-1",
        "ok": True,
        "detections": [
            {
                "label": "person",
                "confidence": 0.92,
                "x": 0.1,
                "y": 0.2,
                "width": 0.3,
                "height": 0.4,
            }
        ],
    }


def test_vision_worker_rejects_invalid_messages() -> None:
    result = handle_request(StubModel(), {"requestId": "frame-2", "type": "wrong"})
    assert result["ok"] is False
    assert result["error"] == "Unsupported vision request"
