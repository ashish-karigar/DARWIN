"""Bounded JSON-lines object-detection worker for the DARWIN Camera app."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MAX_IMAGE_BYTES = 1_500_000
MODEL_NAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]{1,80}$")


@dataclass(frozen=True)
class Detection:
    label: str
    confidence: float
    x: float
    y: float
    width: float
    height: float


class VisionModel:
    def __init__(self) -> None:
        self._model: Any | None = None

    def _load(self) -> Any:
        if self._model is not None:
            return self._model
        from ultralytics import YOLO

        model_name = os.environ.get("DARWIN_VISION_MODEL", "yolo11n.pt")
        if not MODEL_NAME_PATTERN.fullmatch(model_name):
            raise ValueError("DARWIN_VISION_MODEL must be a model filename")
        model_directory = Path("data/models")
        model_directory.mkdir(parents=True, exist_ok=True)
        self._model = YOLO(str(model_directory / model_name))
        return self._model

    def detect(self, encoded_image: str) -> list[Detection]:
        import cv2
        import numpy as np

        try:
            image_bytes = base64.b64decode(encoded_image, validate=True)
        except (binascii.Error, ValueError) as error:
            raise ValueError("invalid image encoding") from error
        if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
            raise ValueError("image exceeds the allowed size")
        image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("image could not be decoded")

        height, width = image.shape[:2]
        results = self._load().predict(
            source=image,
            conf=0.35,
            imgsz=640,
            max_det=50,
            verbose=False,
        )
        detections: list[Detection] = []
        for result in results:
            names = result.names
            for box in result.boxes:
                x1, y1, x2, y2 = (float(value) for value in box.xyxy[0].tolist())
                class_id = int(box.cls[0].item())
                detections.append(
                    Detection(
                        label=str(names.get(class_id, class_id)),
                        confidence=round(float(box.conf[0].item()), 4),
                        x=max(0.0, min(1.0, x1 / width)),
                        y=max(0.0, min(1.0, y1 / height)),
                        width=max(0.0, min(1.0, (x2 - x1) / width)),
                        height=max(0.0, min(1.0, (y2 - y1) / height)),
                    )
                )
        return detections


def response(request_id: str, **payload: Any) -> dict[str, Any]:
    return {"protocolVersion": "1.0", "requestId": request_id, **payload}


def handle_request(model: VisionModel, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return response("unknown", ok=False, error="Invalid vision request")
    request_id = value.get("requestId")
    if not isinstance(request_id, str) or not request_id:
        return response("unknown", ok=False, error="Invalid request ID")
    if value.get("protocolVersion") != "1.0" or value.get("type") != "vision.detect":
        return response(request_id, ok=False, error="Unsupported vision request")
    encoded_image = value.get("image")
    if not isinstance(encoded_image, str):
        return response(request_id, ok=False, error="Missing image")
    try:
        detections = model.detect(encoded_image)
        return response(
            request_id,
            ok=True,
            detections=[asdict(detection) for detection in detections],
        )
    except ModuleNotFoundError:
        return response(
            request_id,
            ok=False,
            error="Vision dependencies are not installed",
            code="dependencies_missing",
        )
    except Exception as error:
        return response(request_id, ok=False, error=str(error)[:300], code="inference_failed")


def main() -> None:
    model = VisionModel()
    for line in sys.stdin:
        try:
            request = json.loads(line)
            result = handle_request(model, request)
        except json.JSONDecodeError:
            result = response("unknown", ok=False, error="Invalid JSON")
        print(json.dumps(result, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    main()
