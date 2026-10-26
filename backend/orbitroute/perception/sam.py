"""Parse sam-3.1 output into full-image boolean masks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from meta_sam_parser import (
    CompletedOutcome,
    SegmentationBoxRecord,
    SegmentationMaskRecord,
    decode_mask_to_raster,
    image_segmentation_format,
)
from PIL import Image


@dataclass
class Instance:
    concept: str
    object_id: str
    confidence: float | None
    box: tuple[float, float, float, float]  # x1, y1, x2, y2 in source pixels
    mask: np.ndarray  # bool, (H, W) of the source image


def response_text(data: dict[str, Any]) -> str:
    """Concatenate the output_text of a non-streaming Responses payload."""
    parts: list[str] = []
    for item in data.get("output", []):
        for c in item.get("content", []):
            if c.get("type") == "output_text":
                parts.append(c.get("text", ""))
    return "".join(parts)


def parse_instances(text: str, concept: str, width: int, height: int) -> list[Instance]:
    parser = image_segmentation_format().create_parser()
    parser.push(text)
    result = parser.finish(CompletedOutcome()).result

    boxes: dict[str, SegmentationBoxRecord] = {}
    masks: dict[str, SegmentationMaskRecord] = {}
    for rec in result.records:
        if isinstance(rec, SegmentationBoxRecord):
            boxes[rec.object_id] = rec
        elif isinstance(rec, SegmentationMaskRecord):
            masks[rec.object_id] = rec

    instances: list[Instance] = []
    for oid, m in masks.items():
        raster = np.frombuffer(decode_mask_to_raster(m.mask), dtype=np.uint8).reshape(m.mask.height, m.mask.width)
        b = m.bounds
        x1, y1 = int(round(b.left)), int(round(b.top))
        x2, y2 = int(round(b.right)), int(round(b.bottom))
        full = np.zeros((height, width), dtype=bool)
        if x2 > x1 and y2 > y1:
            # The mask is box-local and may be stored at a reduced resolution.
            local = Image.fromarray(raster * 255).resize((x2 - x1, y2 - y1), Image.NEAREST)
            full[y1:y2, x1:x2] = np.asarray(local) > 127
        box = boxes.get(oid)
        instances.append(
            Instance(
                concept=concept,
                object_id=oid,
                confidence=m.confidence if m.confidence is not None else (box.confidence if box else None),
                box=(box.left, box.top, box.right, box.bottom) if box else (x1, y1, x2, y2),
                mask=full,
            )
        )
    return instances
