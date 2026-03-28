from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from astrbot.api import logger

_SEGMENTATION_MODEL = None
_HEAD_IMAGE: np.ndarray | None = None


def _to_rgb(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    elif image.ndim == 3 and image.shape[2] == 1:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
    elif image.ndim == 3 and image.shape[2] == 4:
        image = cv2.cvtColor(image, cv2.COLOR_RGBA2RGB)
    return image


def _to_rgba(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGBA)
    elif image.ndim == 3 and image.shape[2] == 1:
        image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGBA)
    elif image.ndim == 3 and image.shape[2] == 3:
        image = cv2.cvtColor(image, cv2.COLOR_RGB2RGBA)
    return image


def _asset_root() -> Path:
    return Path(__file__).resolve().parent


def _load_segmentation_model():
    global _SEGMENTATION_MODEL
    if _SEGMENTATION_MODEL is None:
        from ultralytics import YOLO

        model_path = _asset_root() / "hajimi_models" / "segmentation_model.pt"
        logger.info(
            "[pixivdirect] Loading Hajimi segmentation model from %s", model_path
        )
        _SEGMENTATION_MODEL = YOLO(str(model_path))
    return _SEGMENTATION_MODEL


def _load_head_image() -> np.ndarray:
    global _HEAD_IMAGE
    if _HEAD_IMAGE is None:
        head_path = _asset_root() / "hajimi_assets" / "head.png"
        head_image = cv2.imread(str(head_path), cv2.IMREAD_UNCHANGED)
        if head_image is None:
            raise FileNotFoundError(f"Missing hajimi head asset: {head_path}")
        logger.info("[pixivdirect] Loading Hajimi head asset from %s", head_path)
        _HEAD_IMAGE = _to_rgba(head_image)
    return _HEAD_IMAGE


def _segment_image(image_bgr: np.ndarray):
    segmentation_model = _load_segmentation_model()
    return segmentation_model(
        image_bgr,
        agnostic_nms=True,
        retina_masks=True,
        verbose=False,
    )


def _apply_mask(
    image: np.ndarray,
    mask: np.ndarray,
    head_image: np.ndarray,
) -> np.ndarray:
    mask_indices = np.argwhere(mask > 0)
    if mask_indices.size == 0:
        return image

    min_y, min_x = mask_indices.min(axis=0)
    max_y, max_x = mask_indices.max(axis=0)

    dst_points = np.array(
        [[min_x, min_y], [max_x, min_y], [max_x, max_y], [min_x, max_y]],
        dtype=np.float32,
    )
    head_height, head_width = head_image.shape[:2]
    src_points = np.array(
        [[0, 0], [head_width, 0], [head_width, head_height], [0, head_height]],
        dtype=np.float32,
    )

    matrix = cv2.getPerspectiveTransform(src_points, dst_points)
    transformed_head = cv2.warpPerspective(head_image, matrix, image.shape[:2][::-1])
    alpha_channel = (transformed_head[:, :, 3] / 255.0)[:, :, np.newaxis]
    blended = alpha_channel * transformed_head[:, :, :3] + (1 - alpha_channel) * image
    return blended.astype(np.uint8)


def apply_hajimi_mosaic_to_pil(image: Image.Image) -> Image.Image:
    logger.info(
        "[pixivdirect] Hajimi mosaic started for image size=%sx%s mode=%s",
        image.width,
        image.height,
        image.mode,
    )
    rgb_image = image.convert("RGB")
    image_np = np.array(rgb_image)
    image_bgr = cv2.cvtColor(_to_rgb(image_np), cv2.COLOR_RGB2BGR)

    segmentation_results = _segment_image(image_bgr)
    result = segmentation_results[0]
    if not hasattr(result, "masks") or result.masks is None:
        logger.info(
            "[pixivdirect] Hajimi mosaic skipped: segmentation returned no masks"
        )
        return image.copy()

    masks = result.masks.data.cpu().numpy()
    if len(masks) == 0:
        logger.info("[pixivdirect] Hajimi mosaic skipped: mask count is 0")
        return image.copy()

    logger.info("[pixivdirect] Hajimi mosaic applying %d masks", len(masks))
    output_bgr = image_bgr.copy()
    head_image = _load_head_image()
    for mask in masks:
        output_bgr = _apply_mask(output_bgr, mask, head_image)

    output_rgb = cv2.cvtColor(output_bgr, cv2.COLOR_BGR2RGB)
    if image.mode == "RGBA":
        alpha = image.getchannel("A")
        mosaiced = Image.fromarray(output_rgb).convert("RGBA")
        mosaiced.putalpha(alpha)
        logger.info("[pixivdirect] Hajimi mosaic finished with RGBA output")
        return mosaiced
    logger.info("[pixivdirect] Hajimi mosaic finished with RGB output")
    return Image.fromarray(output_rgb)
