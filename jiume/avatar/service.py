"""Avatar providers and manifest management for the JiuMe desktop twin."""

from __future__ import annotations

import base64
import io
import json
import os
import re
import secrets
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from jiume.audit.logger import append_audit_event
from jiume.config import get_image_provider_config
from jiume.paths import get_twin_root
from jiume.twins.appearance import normalize_twin_appearance
from jiume.twins.store import TwinStore, ensure_safe_twin_id

MAX_UPLOAD_BYTES = 8 * 1024 * 1024
SUPPORTED_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}

CODEX_PET_FRAME_COUNTS = {
    "idle": 6,
    "running-right": 8,
    "running-left": 8,
    "waving": 4,
    "jumping": 5,
    "failed": 8,
    "waiting": 6,
    "running": 6,
    "review": 6,
}
CODEX_PET_STATE_PURPOSES = {
    "idle": "calm resting, breathing, and blinking loop",
    "running-right": "rightward drag movement loop",
    "running-left": "leftward drag movement loop",
    "waving": "greeting or attention gesture",
    "jumping": "hover or playful jump",
    "failed": "blocked, failed, or cancelled reaction",
    "waiting": "waiting for approval, help, or user input",
    "running": "active task work or processing",
    "review": "ready or completed output review",
}
CODEX_PET_STATE_ALIASES = {
    "thinking": "running",
    "speaking": "waving",
    "working": "running",
    "waiting_approval": "waiting",
    "success": "review",
    "error": "failed",
    "sleep": "idle",
}

DESKTOP_STATES = tuple(CODEX_PET_FRAME_COUNTS.keys())
CODEX_CELL = (192, 208)
CODEX_GRID = (8, 9)
ANIMATION_FRAMES_PER_STATE = CODEX_PET_FRAME_COUNTS["idle"]
AVATAR_VIEW_NAMES = ("front", "left", "right", "back")
AVATAR_PACK_FILENAME = "avatar_pack.json"
COMPAT_SPRITE_PACK_FILENAME = "pet.json"
OPENAI_IMAGE_TIMEOUT_SECONDS = 180.0
OPENAI_IMAGE_SIZE = "1024x1024"
PRIMARY_SPRITE_CHROMA_KEY = (255, 0, 255)
LEGACY_GREEN_CHROMA_KEY = (0, 255, 0)
SPRITE_CHROMA_KEYS = (PRIMARY_SPRITE_CHROMA_KEY, LEGACY_GREEN_CHROMA_KEY)


def _chroma_key_hex(key: tuple[int, int, int] = PRIMARY_SPRITE_CHROMA_KEY) -> str:
    return f"#{key[0]:02X}{key[1]:02X}{key[2]:02X}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _avatar_dir(twin_id: str) -> Path:
    path = get_twin_root(ensure_safe_twin_id(twin_id)) / "avatar"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _load_font(size: int) -> ImageFont.ImageFont:
    for name in ("Arial Unicode.ttf", "Arial.ttf", "Helvetica.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _center_text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font: ImageFont.ImageFont, fill: str) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    x = xy[0] - (bbox[2] - bbox[0]) // 2
    y = xy[1] - (bbox[3] - bbox[1]) // 2
    draw.text((x, y), text, fill=fill, font=font)


def _openai_avatar_prompt(twin: dict[str, Any]) -> str:
    name = str(twin.get("displayName") or "JiuMe").strip() or "JiuMe"
    purpose = str(twin.get("purpose") or "personal desktop twin").strip() or "personal desktop twin"
    chroma_key = _chroma_key_hex()
    return (
        "Create the canonical base reference for a Codex-pet-style animated sprite sheet. "
        "Transform the reference image into a polished Q-version 2D person-shaped human desktop twin sticker character, "
        "with the same recognizable hair, face cues, outfit cues, and overall identity. "
        f"The twin's name is {name}; its role is {purpose}. "
        "Use clean chibi proportions, compact whole body, strong readable silhouette, crisp outline, "
        "and production-quality sprite art suitable for 192x208 Codex pet cells. "
        "This is not a pet, animal, robot, mascot, or generic icon: no animal ears, paws, tails, or mascot body. "
        f"Use a perfectly flat {chroma_key} chroma-key background and do not use {chroma_key} in the character. "
        "Do not draw white backgrounds, grey backgrounds, checkerboard transparency previews, text, watermarks, "
        "scenery, shadows, or detached effects."
    )


def _openai_animation_row_prompt(twin: dict[str, Any], state: str) -> str:
    name = str(twin.get("displayName") or "JiuMe").strip() or "JiuMe"
    frame_count = CODEX_PET_FRAME_COUNTS[state]
    chroma_key = _chroma_key_hex()
    state_guidance = {
        "idle": "calm breathing and blinking only; subtle loop, no large gesture",
        "running-right": "directional movement facing and travelling right; clear alternating gait",
        "running-left": "directional movement facing and travelling left; clear alternating gait",
        "waving": "greeting wave through hand and arm pose only; no wave marks or motion lines",
        "jumping": "anticipation, lift, peak, descent, settle through body position only",
        "failed": "blocked or failed reaction, deflated but readable; no floating symbols",
        "waiting": "expectant asking pose for user input or approval, distinct from idle",
        "running": "active task work or focused processing; not literal jogging or sprinting",
        "review": "focused inspection or review loop through eyes, head tilt, and posture",
    }
    return (
        "Create one hatch-pet-style Codex animation row strip from the provided canonical base character. "
        f"Character identity: {name}, a Q-version human desktop twin. "
        f"Animation row state: {state}. Exactly {frame_count} separate full-body frames, arranged left to right "
        "in one horizontal strip with even spacing and generous padding. "
        "Every frame must depict the same character, same hairstyle, same face, same outfit, same palette, "
        "same proportions, and same sticker-like outline. "
        f"Motion guidance: {state_guidance[state]}. "
        "Use sprite-production framing: no labels, no frame numbers, no visible grid, no UI, no text, "
        "no scenery, no floor, no cast shadow, no contact shadow, no glow, no detached effects. "
        f"Use a perfectly flat {chroma_key} chroma-key background and do not use {chroma_key} anywhere in the character. "
        "Do not draw white backgrounds, grey backgrounds, black backgrounds, checkerboard transparency previews, "
        "transparent-preview tiles, or any visible background texture. "
        "Keep each full body readable when extracted into a 192x208 Codex pet cell."
    )


def _provider_rejected_optional_image_param(exc: Exception, param: str) -> bool:
    message = str(exc).lower()
    return param in message and ("not supported" in message or "invalid_value" in message)


def _openai_avatar_image_payload(response: Any) -> bytes:
    item = response.data[0]
    b64_data = getattr(item, "b64_json", None)
    if b64_data:
        return base64.b64decode(b64_data)
    url = getattr(item, "url", None)
    if not url:
        raise ValueError("image provider returned no image payload")
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read()


def _request_openai_edit_payload(
    client: Any,
    image_path: Path,
    *,
    prompt: str,
    model: str,
    twin_id: str,
    transparent_background: bool = True,
) -> bytes:
    edit_kwargs: dict[str, Any] = {
        "model": model,
        "prompt": prompt,
        "size": OPENAI_IMAGE_SIZE,
        "output_format": "png",
    }
    if transparent_background:
        edit_kwargs["background"] = "transparent"
    while True:
        with image_path.open("rb") as image_file:
            try:
                response = client.images.edit(image=image_file, **edit_kwargs)
                return _openai_avatar_image_payload(response)
            except Exception as exc:  # noqa: BLE001
                for param in ("background", "output_format"):
                    if param in edit_kwargs and _provider_rejected_optional_image_param(exc, param):
                        edit_kwargs.pop(param, None)
                        append_audit_event(
                            twin_id,
                            "avatar.provider_optional_param_retried",
                            {"provider": "openai", "param": param, "model": edit_kwargs.get("model")},
                        )
                        break
                else:
                    raise


def _color_distance(pixel: tuple[int, int, int], key: tuple[int, int, int]) -> float:
    return ((pixel[0] - key[0]) ** 2 + (pixel[1] - key[1]) ** 2 + (pixel[2] - key[2]) ** 2) ** 0.5


def _is_light_preview_background(red: int, green: int, blue: int) -> bool:
    spread = max(red, green, blue) - min(red, green, blue)
    return min(red, green, blue) >= 185 and spread <= 16


def _is_sprite_chroma_pixel(red: int, green: int, blue: int, threshold: float) -> bool:
    if any(_color_distance((red, green, blue), key) <= threshold for key in SPRITE_CHROMA_KEYS):
        return True
    if red >= 185 and blue >= 185 and green <= 132 and min(red, blue) - green >= 64:
        return True
    if green < 50 or green <= red or green <= blue:
        return False
    green_advantage = green - max(red, blue)
    blue_near_red = blue <= red + 52
    if green_advantage >= 64 and blue_near_red:
        return True
    if green >= 185 and green >= red * 1.75 and green >= blue * 1.35 and blue <= 132:
        return True
    if green <= 150 and green_advantage >= 42 and blue <= red + 28:
        return True
    return False


def _neutralize_light_chroma_tint(red: int, green: int, blue: int) -> tuple[int, int, int]:
    if min(red, green, blue) >= 180 and green - max(red, blue) >= 18:
        neutral = max(red, green, blue)
        return neutral, neutral, neutral
    if min(red, green, blue) >= 180 and min(red, blue) - green >= 18 and abs(red - blue) <= 30:
        neutral = max(red, green, blue)
        return neutral, neutral, neutral
    return red, green, blue


def _sprite_background_mask(image: Image.Image, threshold: float) -> bytearray:
    rgba = image.convert("RGBA")
    width, height = rgba.size
    candidates = bytearray(width * height)
    foreground = Image.new("L", rgba.size, 0)
    foreground_pixels = foreground.load()

    for index, (red, green, blue, alpha) in enumerate(rgba.getdata()):
        is_chroma = _is_sprite_chroma_pixel(red, green, blue, threshold)
        is_light_preview = alpha > 16 and _is_light_preview_background(red, green, blue)
        if alpha <= 16 or is_chroma:
            candidates[index] = 1
        elif is_light_preview:
            candidates[index] = 2
        else:
            x = index % width
            y = index // width
            foreground_pixels[x, y] = 255

    protected = foreground.filter(ImageFilter.MaxFilter(5)).tobytes()
    removable = bytearray(width * height)
    visited = bytearray(width * height)
    stack: list[int] = []
    for x in range(width):
        stack.append(x)
        stack.append((height - 1) * width + x)
    for y in range(height):
        stack.append(y * width)
        stack.append(y * width + width - 1)

    while stack:
        current = stack.pop()
        if visited[current]:
            continue
        visited[current] = 1
        candidate = candidates[current]
        if not candidate:
            continue
        if candidate == 2 and protected[current]:
            continue
        removable[current] = 1
        x = current % width
        y = current // width
        if x > 0:
            stack.append(current - 1)
        if x + 1 < width:
            stack.append(current + 1)
        if y > 0:
            stack.append(current - width)
        if y + 1 < height:
            stack.append(current + width)
    return removable


def _remove_sprite_chroma_key(image: Image.Image, threshold: float = 96.0) -> Image.Image:
    rgba = image.convert("RGBA")
    background_mask = _sprite_background_mask(rgba, threshold)
    pixels = []
    for index, (red, green, blue, alpha) in enumerate(rgba.getdata()):
        if background_mask[index] or _is_sprite_chroma_pixel(red, green, blue, threshold):
            pixels.append((0, 0, 0, 0))
        else:
            red, green, blue = _neutralize_light_chroma_tint(red, green, blue)
            pixels.append((red, green, blue, alpha))
    rgba.putdata(pixels)
    return _normalize_transparent_pixels(rgba)


def _mock_png_for_state(
    state: str,
    display_name: str,
    appearance: dict[str, Any] | None = None,
) -> Image.Image:
    _ = (state, display_name)
    outfit = normalize_twin_appearance(appearance).get("outfitColor") or "#5B8DEF"
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    cx, cy = 128, 122
    skin = "#FFD9C7"
    hair = "#2F241D"
    blush = "#FF9AAE"
    shirt = outfit

    draw.rounded_rectangle((76, 148, 180, 226), radius=34, fill=shirt)
    draw.rounded_rectangle((82, 170, 112, 226), radius=15, fill=skin)
    draw.rounded_rectangle((144, 170, 174, 226), radius=15, fill=skin)
    draw.rounded_rectangle((62, 159, 96, 210), radius=15, fill=skin)
    draw.rounded_rectangle((160, 159, 194, 210), radius=15, fill=skin)

    draw.ellipse((cx - 66, cy - 83, cx + 66, cy + 49), fill=skin)
    draw.pieslice((cx - 69, cy - 90, cx + 69, cy + 34), 180, 360, fill=hair)
    draw.ellipse((cx - 66, cy - 72, cx - 12, cy - 18), fill=hair)
    draw.ellipse((cx + 8, cy - 72, cx + 66, cy - 18), fill=hair)
    draw.ellipse((cx - 73, cy - 18, cx - 55, cy + 12), fill=skin)
    draw.ellipse((cx + 55, cy - 18, cx + 73, cy + 12), fill=skin)

    eye_y = cy - 16
    draw.ellipse((cx - 37, eye_y - 7, cx - 22, eye_y + 8), fill=hair)
    draw.ellipse((cx + 22, eye_y - 7, cx + 37, eye_y + 8), fill=hair)
    draw.ellipse((cx - 33, eye_y - 3, cx - 29, eye_y + 1), fill="white")
    draw.ellipse((cx + 26, eye_y - 3, cx + 30, eye_y + 1), fill="white")
    draw.arc((cx - 37, cy + 22, cx + 37, cy + 62), start=20, end=160, fill=hair, width=5)
    draw.ellipse((cx - 51, cy + 9, cx - 30, cy + 25), fill=blush)
    draw.ellipse((cx + 30, cy + 9, cx + 51, cy + 25), fill=blush)
    return image


def _fit_icon(image: Image.Image, size: tuple[int, int] = (256, 256)) -> Image.Image:
    source = image.convert("RGBA")
    source.thumbnail((210, 210), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    canvas.alpha_composite(source, ((size[0] - source.width) // 2, (size[1] - source.height) // 2))
    return canvas


def _normalize_transparent_pixels(image: Image.Image) -> Image.Image:
    normalized = image.convert("RGBA")
    normalized.putdata([(0, 0, 0, 0) if pixel[3] == 0 else pixel for pixel in normalized.getdata()])
    return normalized


def _fit_sprite_to_codex_cell(image: Image.Image) -> Image.Image:
    rgba = _normalize_transparent_pixels(image)
    bbox = rgba.getchannel("A").getbbox()
    target = Image.new("RGBA", CODEX_CELL, (0, 0, 0, 0))
    if bbox is None:
        return target
    sprite = rgba.crop(bbox)
    max_width = CODEX_CELL[0] - 10
    max_height = CODEX_CELL[1] - 10
    scale = min(max_width / sprite.width, max_height / sprite.height, 1.0)
    if scale != 1.0:
        sprite = sprite.resize(
            (max(1, round(sprite.width * scale)), max(1, round(sprite.height * scale))),
            Image.Resampling.LANCZOS,
        )
    target.alpha_composite(sprite, ((CODEX_CELL[0] - sprite.width) // 2, (CODEX_CELL[1] - sprite.height) // 2))
    return _normalize_transparent_pixels(target)


def _connected_sprite_components(image: Image.Image) -> list[dict[str, Any]]:
    alpha = image.getchannel("A")
    width, height = image.size
    data = alpha.tobytes()
    visited = bytearray(width * height)
    components: list[dict[str, Any]] = []

    for start, alpha_value in enumerate(data):
        if alpha_value <= 16 or visited[start]:
            continue
        stack = [start]
        visited[start] = 1
        pixels: list[int] = []
        min_x = width
        min_y = height
        max_x = 0
        max_y = 0
        while stack:
            current = stack.pop()
            pixels.append(current)
            x = current % width
            y = current // width
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
            if x > 0:
                neighbor = current - 1
                if not visited[neighbor] and data[neighbor] > 16:
                    visited[neighbor] = 1
                    stack.append(neighbor)
            if x + 1 < width:
                neighbor = current + 1
                if not visited[neighbor] and data[neighbor] > 16:
                    visited[neighbor] = 1
                    stack.append(neighbor)
            if y > 0:
                neighbor = current - width
                if not visited[neighbor] and data[neighbor] > 16:
                    visited[neighbor] = 1
                    stack.append(neighbor)
            if y + 1 < height:
                neighbor = current + width
                if not visited[neighbor] and data[neighbor] > 16:
                    visited[neighbor] = 1
                    stack.append(neighbor)
        components.append(
            {
                "pixels": pixels,
                "area": len(pixels),
                "bbox": (min_x, min_y, max_x + 1, max_y + 1),
                "center_x": (min_x + max_x + 1) / 2,
            }
        )
    return components


def _component_group_image(source: Image.Image, components: list[dict[str, Any]], padding: int = 4) -> Image.Image:
    width, height = source.size
    min_x = max(0, min(component["bbox"][0] for component in components) - padding)
    min_y = max(0, min(component["bbox"][1] for component in components) - padding)
    max_x = min(width, max(component["bbox"][2] for component in components) + padding)
    max_y = min(height, max(component["bbox"][3] for component in components) + padding)
    output = Image.new("RGBA", (max_x - min_x, max_y - min_y), (0, 0, 0, 0))
    source_pixels = source.load()
    output_pixels = output.load()
    for component in components:
        for pixel_index in component["pixels"]:
            x = pixel_index % width
            y = pixel_index // width
            output_pixels[x - min_x, y - min_y] = source_pixels[x, y]
    return output


def _component_frame_groups(strip: Image.Image, frame_count: int) -> list[list[dict[str, Any]]] | None:
    components = _connected_sprite_components(strip)
    if not components:
        return None
    largest_area = max(component["area"] for component in components)
    seed_threshold = max(120, largest_area * 0.20)
    seeds = [component for component in components if component["area"] >= seed_threshold]
    if len(seeds) < frame_count:
        seeds = sorted(components, key=lambda component: component["area"], reverse=True)[:frame_count]
    if len(seeds) < frame_count:
        return None
    seeds = sorted(
        sorted(seeds, key=lambda component: component["area"], reverse=True)[:frame_count],
        key=lambda component: component["center_x"],
    )
    seed_ids = {id(seed) for seed in seeds}
    groups: list[list[dict[str, Any]]] = [[seed] for seed in seeds]
    noise_threshold = max(12, largest_area * 0.002)
    for component in components:
        if id(component) in seed_ids or component["area"] < noise_threshold:
            continue
        nearest_index = min(
            range(len(seeds)),
            key=lambda index: abs(seeds[index]["center_x"] - component["center_x"]),
        )
        groups[nearest_index].append(component)
    return groups


def _extract_component_frames(strip: Image.Image, frame_count: int) -> list[Image.Image] | None:
    groups = _component_frame_groups(strip, frame_count)
    if groups is None:
        return None
    return [_fit_sprite_to_codex_cell(_component_group_image(strip, group)) for group in groups]


def _extract_codex_row_frames(strip: Image.Image, state: str) -> list[Image.Image]:
    frame_count = CODEX_PET_FRAME_COUNTS[state]
    clean_strip = _remove_sprite_chroma_key(strip)
    component_frames = _extract_component_frames(clean_strip, frame_count)
    if component_frames is not None:
        return component_frames
    slot_width = clean_strip.width / frame_count
    frames: list[Image.Image] = []
    for index in range(frame_count):
        left = round(index * slot_width)
        right = round((index + 1) * slot_width)
        frames.append(_fit_sprite_to_codex_cell(clean_strip.crop((left, 0, right, clean_strip.height))))
    return frames


def _save_image_atomic(image: Image.Image, path: Path, image_format: str | None = None, **save_kwargs: Any) -> None:
    tmp = path.with_name(f".{path.name}.{secrets.token_hex(4)}.tmp")
    try:
        _normalize_transparent_pixels(image).save(tmp, format=image_format, **save_kwargs)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _latest_source_image(avatar_dir: Path) -> Path | None:
    sources = sorted(avatar_dir.glob("source_*"), key=lambda path: path.stat().st_mtime, reverse=True)
    return sources[0] if sources else None


def _decode_source_upload(payload: dict[str, Any]) -> tuple[bytes, str]:
    consent = bool(payload.get("consent") or payload.get("consentAccepted"))
    if not consent:
        raise ValueError("avatar consent is required")

    raw = str(payload.get("content_base64") or payload.get("contentBase64") or "")
    mime = str(payload.get("mime_type") or payload.get("mimeType") or "").strip().lower()
    if raw.startswith("data:"):
        header, _, body = raw.partition(",")
        raw = body
        if not mime:
            mime = header.removeprefix("data:").split(";", 1)[0].lower()
    if mime not in SUPPORTED_MIME:
        raise ValueError("unsupported image type")
    try:
        data = base64.b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("invalid base64 image") from exc
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("image exceeds 8MB")
    return data, mime


def _ellipse_mask(size: tuple[int, int]) -> Image.Image:
    scale = 4
    mask = Image.new("L", (size[0] * scale, size[1] * scale), 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, mask.width - 1, mask.height - 1), fill=255)
    return mask.resize(size, Image.Resampling.LANCZOS)


def _rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    scale = 4
    mask = Image.new("L", (size[0] * scale, size[1] * scale), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle((0, 0, mask.width - 1, mask.height - 1), radius=radius * scale, fill=255)
    return mask.resize(size, Image.Resampling.LANCZOS)


def _mix_rgb(
    first: tuple[int, int, int],
    second: tuple[int, int, int],
    amount: float,
) -> tuple[int, int, int]:
    ratio = max(0.0, min(1.0, amount))
    return tuple(
        max(0, min(255, int(round(first[index] * (1.0 - ratio) + second[index] * ratio))))
        for index in range(3)
    )


def _average_visible_color(
    image: Image.Image,
    fallback: tuple[int, int, int],
    *,
    min_alpha: int = 24,
) -> tuple[int, int, int]:
    source = image.convert("RGBA")
    pixels = [pixel[:3] for pixel in source.getdata() if pixel[3] >= min_alpha]
    if not pixels:
        return fallback
    count = len(pixels)
    return (
        sum(pixel[0] for pixel in pixels) // count,
        sum(pixel[1] for pixel in pixels) // count,
        sum(pixel[2] for pixel in pixels) // count,
    )


def _has_alpha_cutout(image: Image.Image) -> bool:
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return False
    min_alpha, _ = alpha.getextrema()
    if min_alpha >= 250:
        return False
    bbox_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    return bbox_area < image.width * image.height * 0.98


def _crop_to_alpha(image: Image.Image, padding: int = 8) -> Image.Image:
    bbox = image.getchannel("A").getbbox()
    if bbox is None:
        return image
    left = max(0, bbox[0] - padding)
    top = max(0, bbox[1] - padding)
    right = min(image.width, bbox[2] + padding)
    bottom = min(image.height, bbox[3] + padding)
    return image.crop((left, top, right, bottom))


def _corner_background_color(image: Image.Image) -> tuple[int, int, int]:
    rgb = image.convert("RGB")
    sample = max(8, min(28, min(rgb.size) // 9))
    patches = (
        (0, 0, sample, sample),
        (rgb.width - sample, 0, rgb.width, sample),
        (0, rgb.height - sample, sample, rgb.height),
        (rgb.width - sample, rgb.height - sample, rgb.width, rgb.height),
    )
    values: list[tuple[int, int, int]] = []
    for patch in patches:
        values.extend(rgb.crop(patch).getdata())
    count = max(1, len(values))
    return (
        sum(pixel[0] for pixel in values) // count,
        sum(pixel[1] for pixel in values) // count,
        sum(pixel[2] for pixel in values) // count,
    )


def _source_background_cutout(source: Image.Image) -> Image.Image | None:
    rgb = source.convert("RGB")
    bg = _corner_background_color(source)
    threshold = 58
    mask = Image.new("L", source.size, 0)
    data = []
    foreground = 0
    for pixel in rgb.getdata():
        distance = abs(pixel[0] - bg[0]) + abs(pixel[1] - bg[1]) + abs(pixel[2] - bg[2])
        value = 255 if distance >= threshold else 0
        foreground += 1 if value else 0
        data.append(value)
    total = max(1, source.width * source.height)
    foreground_ratio = foreground / total
    if foreground_ratio < 0.08 or foreground_ratio > 0.86:
        return None
    mask.putdata(data)
    bbox = mask.getbbox()
    if bbox is None:
        return None
    bbox_area = (bbox[2] - bbox[0]) * (bbox[3] - bbox[1])
    if bbox_area > total * 0.94:
        return None
    mask = mask.filter(ImageFilter.MedianFilter(5)).filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(1.4))
    cutout = source.copy()
    original_alpha = source.getchannel("A")
    cutout.putalpha(ImageChops.multiply(original_alpha, mask))
    return cutout if _has_alpha_cutout(cutout) else None


def _source_cutout_avatar_base(source: Image.Image) -> Image.Image:
    source = _crop_to_alpha(source)
    source = _fit_icon(source, (190, 222))
    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    alpha = source.getchannel("A")
    x = (image.width - source.width) // 2
    y = 18 + max(0, 222 - source.height) // 2

    outline_alpha = alpha.filter(ImageFilter.MaxFilter(13)).filter(ImageFilter.GaussianBlur(1))
    outline = Image.new("RGBA", source.size, (255, 255, 255, 235))
    outline.putalpha(outline_alpha)
    image.alpha_composite(outline, (x, y))
    image.alpha_composite(source, (x, y))
    return image


def _source_person_photo_mask(size: tuple[int, int]) -> Image.Image:
    width, height = size
    scale = 4
    mask = Image.new("L", (width * scale, height * scale), 0)
    draw = ImageDraw.Draw(mask)
    head = (
        int(width * 0.21 * scale),
        int(height * 0.01 * scale),
        int(width * 0.79 * scale),
        int(height * 0.58 * scale),
    )
    torso = (
        int(width * 0.34 * scale),
        int(height * 0.42 * scale),
        int(width * 0.66 * scale),
        int(height * 0.99 * scale),
    )
    shoulder_left = (
        int(width * 0.33 * scale),
        int(height * 0.70 * scale),
        int(width * 0.47 * scale),
        int(height * 0.93 * scale),
    )
    shoulder_right = (
        int(width * 0.53 * scale),
        int(height * 0.70 * scale),
        int(width * 0.67 * scale),
        int(height * 0.93 * scale),
    )
    draw.rounded_rectangle(torso, radius=int(width * 0.18 * scale), fill=255)
    draw.ellipse(shoulder_left, fill=255)
    draw.ellipse(shoulder_right, fill=255)
    draw.ellipse(head, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(0.6 * scale)).resize(size, Image.Resampling.LANCZOS)


def _source_masked_photo_avatar_base(source: Image.Image) -> Image.Image:
    photo = ImageOps.fit(source, (190, 222), Image.Resampling.LANCZOS, centering=(0.5, 0.32)).convert("RGBA")
    mask = _source_person_photo_mask(photo.size)
    photo.putalpha(ImageChops.multiply(photo.getchannel("A"), mask))

    image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    alpha = photo.getchannel("A")
    x = (image.width - photo.width) // 2
    y = 17

    outline_alpha = alpha.filter(ImageFilter.MaxFilter(11)).filter(ImageFilter.GaussianBlur(1))
    outline = Image.new("RGBA", photo.size, (255, 255, 255, 232))
    outline.putalpha(outline_alpha)
    image.alpha_composite(outline, (x, y))
    image.alpha_composite(photo, (x, y))
    return image


def _source_photo_avatar_base(source_path: Path, twin: dict[str, Any]) -> Image.Image:
    source = ImageOps.exif_transpose(Image.open(source_path)).convert("RGBA")
    if _has_alpha_cutout(source):
        return _source_cutout_avatar_base(source)
    background_cutout = _source_background_cutout(source)
    if background_cutout is not None:
        return _source_cutout_avatar_base(background_cutout)
    return _source_masked_photo_avatar_base(source)


def _shift_transparent(image: Image.Image, dx: int = 0, dy: int = 0) -> Image.Image:
    shifted = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shifted.alpha_composite(image, (dx, dy))
    return shifted


def _scale_transparent(image: Image.Image, sx: float = 1.0, sy: float = 1.0) -> Image.Image:
    width = max(1, int(image.width * sx))
    height = max(1, int(image.height * sy))
    resized = image.resize((width, height), Image.Resampling.LANCZOS)
    if resized.width > image.width or resized.height > image.height:
        return ImageOps.fit(resized, image.size, Image.Resampling.LANCZOS, centering=(0.5, 0.5))
    canvas = Image.new("RGBA", image.size, (0, 0, 0, 0))
    canvas.alpha_composite(resized, ((image.width - resized.width) // 2, (image.height - resized.height) // 2))
    return canvas


def _codex_state_for_avatar(state: str) -> str:
    key = str(state or "idle").strip()
    key = CODEX_PET_STATE_ALIASES.get(key, key)
    return key if key in CODEX_PET_FRAME_COUNTS else "idle"


def _pose_base_for_state(base: Image.Image, state: str) -> Image.Image:
    key = _codex_state_for_avatar(state)
    if key == "running-right":
        return _view_from_base(base, "right")
    if key == "running-left":
        return _view_from_base(base, "left")
    return _fit_icon(base)


def _state_from_base(base: Image.Image, state: str, frame_index: int = 0) -> Image.Image:
    state = _codex_state_for_avatar(state)
    image = _pose_base_for_state(base, state)
    if state == "waving":
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        hand_positions = ((190, 116), (200, 94), (192, 104), (178, 126))
        hand_x, hand_y = hand_positions[frame_index % len(hand_positions)]
        skin = (255, 217, 199, 246)
        draw.line((162, 166, hand_x, hand_y), fill=skin, width=11)
        draw.ellipse((hand_x - 10, hand_y - 10, hand_x + 10, hand_y + 10), fill=skin)
        image.alpha_composite(overlay)
    elif state == "failed":
        image = ImageEnhance.Color(image).enhance(0.72)
        image = ImageEnhance.Brightness(image).enhance(0.82)
    elif state == "waiting":
        image = ImageEnhance.Contrast(image).enhance(1.04)
    elif state == "review":
        image = ImageEnhance.Sharpness(image).enhance(1.1)
    return image


def _animation_frame_from_base(base: Image.Image, state: str, frame_index: int) -> Image.Image:
    codex_state = _codex_state_for_avatar(state)
    return _motion_frame_for_state(_state_from_base(base, codex_state, frame_index), codex_state, frame_index)


def _motion_frame_for_state(image: Image.Image, state: str, frame_index: int) -> Image.Image:
    state = _codex_state_for_avatar(state)
    plans = {
        "idle": ((0, 0, 0, 1.0), (0, -1, 0, 1.0), (0, -2, 0, 1.005), (0, -1, 0, 1.0), (0, 0, 0, 1.0), (0, 1, 0, 0.997)),
        "running-right": ((-4, 1, -4, 1.0), (0, -1, -2, 1.015), (4, 0, 1, 1.0), (7, 1, 3, 0.995), (4, -1, 2, 1.01), (0, 0, -1, 1.0), (-3, 1, -3, 1.0), (1, 0, 1, 1.005)),
        "running-left": ((4, 1, 4, 1.0), (0, -1, 2, 1.015), (-4, 0, -1, 1.0), (-7, 1, -3, 0.995), (-4, -1, -2, 1.01), (0, 0, 1, 1.0), (3, 1, 3, 1.0), (-1, 0, -1, 1.005)),
        "waving": ((0, 0, -1, 1.0), (0, -1, 2, 1.01), (0, -1, -2, 1.0), (0, 0, 1, 1.005)),
        "jumping": ((0, 0, 0, 1.0), (0, -9, -2, 1.02), (0, -18, 0, 1.035), (0, -9, 2, 1.02), (0, 0, 0, 1.0)),
        "failed": ((0, 2, 3, 1.0), (2, 2, -3, 1.0), (-2, 3, 3, 0.995), (0, 3, -2, 0.99), (1, 4, 1, 0.99), (-1, 3, -1, 0.995), (0, 2, 0, 1.0), (0, 3, 0, 0.995)),
        "waiting": ((0, 0, 2, 1.0), (-1, -1, 3, 1.01), (0, -2, 4, 1.018), (1, -1, 3, 1.01), (0, 0, 2, 1.0), (0, 1, 1, 0.998)),
        "running": ((0, 0, -2, 1.0), (2, -2, -3, 1.012), (3, -1, -1, 1.005), (1, 1, 1, 1.0), (-1, 0, 2, 1.008), (0, -1, -1, 1.0)),
        "review": ((0, 0, -1, 1.0), (-1, -1, -2, 1.006), (0, 0, 0, 1.0), (1, -1, 2, 1.006), (0, 0, 1, 1.0), (0, 1, 0, 0.998)),
    }
    plan = plans.get(state, plans["idle"])
    dx, dy, rotation, scale = plan[frame_index % len(plan)]
    if scale != 1.0:
        image = _scale_transparent(image, scale, scale)
    if rotation:
        image = image.rotate(rotation, resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0, 0))
    if dx or dy:
        image = _shift_transparent(image, dx, dy)
    return image


def _write_mock_avatar_frames(
    avatar_dir: Path,
    display_name: str,
    appearance: dict[str, Any],
) -> tuple[dict[str, str], dict[str, list[str]], dict[str, str]]:
    base_image = _mock_png_for_state("idle", display_name, appearance)
    return _write_avatar_frames(avatar_dir, base_image)


def _side_view_from_base(front: Image.Image, view: str) -> Image.Image:
    source = _fit_icon(front)
    sign = -1 if view == "left" else 1
    side = Image.new("RGBA", source.size, (0, 0, 0, 0))
    narrowed = source.resize((176, source.height), Image.Resampling.LANCZOS)
    if view == "right":
        narrowed = ImageOps.mirror(narrowed)
    side.alpha_composite(narrowed, (40 + sign * 10, 0))

    draw = ImageDraw.Draw(side)
    head_color = _average_visible_color(source.crop((48, 24, 208, 158)), (47, 36, 29))
    shirt_color = _average_visible_color(source.crop((70, 160, 186, 234)), (37, 99, 235))
    hair = (*_mix_rgb(head_color, (24, 24, 27), 0.5), 136)
    skin = (255, 217, 199, 226)
    cheek = (255, 154, 174, 150)
    if sign < 0:
        draw.rounded_rectangle((57, 44, 87, 148), radius=16, fill=hair)
        draw.polygon(((58, 92), (35, 102), (58, 113)), fill=skin)
        draw.ellipse((48, 104, 65, 119), fill=cheek)
        draw.line((70, 189, 52, 222), fill=(*_mix_rgb(shirt_color, (255, 255, 255), 0.42), 122), width=4)
    else:
        draw.rounded_rectangle((169, 44, 199, 148), radius=16, fill=hair)
        draw.polygon(((198, 92), (221, 102), (198, 113)), fill=skin)
        draw.ellipse((191, 104, 208, 119), fill=cheek)
        draw.line((186, 189, 204, 222), fill=(*_mix_rgb(shirt_color, (255, 255, 255), 0.42), 122), width=4)
    return side


def _view_from_base(base: Image.Image, view: str) -> Image.Image:
    front = _fit_icon(base)
    if view == "left":
        return _side_view_from_base(front, "left")
    if view == "right":
        return _side_view_from_base(front, "right")
    if view == "back":
        shirt = front.getpixel((128, 184))
        if len(shirt) < 4 or shirt[3] < 80:
            shirt = (37, 99, 235, 255)
        head_color = _average_visible_color(front.crop((48, 24, 208, 158)), (47, 36, 29))
        back = Image.new("RGBA", front.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(back)
        hair = (*_mix_rgb(head_color, (24, 24, 27), 0.5), 255)
        skin = (255, 217, 199, 255)
        draw.rounded_rectangle((77, 148, 179, 232), radius=30, fill=shirt)
        draw.rounded_rectangle((66, 165, 98, 224), radius=15, fill=skin)
        draw.rounded_rectangle((158, 165, 190, 224), radius=15, fill=skin)
        draw.rounded_rectangle((109, 125, 147, 164), radius=16, fill=skin)
        draw.ellipse((63, 31, 193, 165), fill=hair)
        draw.pieslice((69, 83, 187, 188), 0, 180, fill=hair)
        draw.line((128, 162, 128, 218), fill=(255, 255, 255, 90), width=3)
        return back
    return front


def _write_avatar_frames(
    avatar_dir: Path,
    base_image: Image.Image,
) -> tuple[dict[str, str], dict[str, list[str]], dict[str, str]]:
    state_files: dict[str, str] = {}
    state_frame_files: dict[str, list[str]] = {}
    for state in DESKTOP_STATES:
        frames: list[str] = []
        for frame_index in range(CODEX_PET_FRAME_COUNTS[state]):
            image = _animation_frame_from_base(base_image, state, frame_index)
            filename = f"{state}.png" if frame_index == 0 else f"{state}_{frame_index}.png"
            _save_image_atomic(image, avatar_dir / filename, "PNG")
            frames.append(filename)
        state_files[state] = frames[0]
        state_frame_files[state] = frames

    view_files: dict[str, str] = {}
    for view in AVATAR_VIEW_NAMES:
        filename = f"view_{view}.png"
        _save_image_atomic(_view_from_base(base_image, view), avatar_dir / filename, "PNG")
        view_files[view] = filename
    return state_files, state_frame_files, view_files


def _write_openai_sprite_row_frames(
    avatar_dir: Path,
    row_images: dict[str, Image.Image],
    base_image: Image.Image,
) -> tuple[dict[str, str], dict[str, list[str]], dict[str, str]]:
    state_files: dict[str, str] = {}
    state_frame_files: dict[str, list[str]] = {}
    for state in DESKTOP_STATES:
        row = row_images.get(state)
        if row is None:
            raise ValueError(f"missing generated sprite row for {state}")
        frames: list[str] = []
        for frame_index, image in enumerate(_extract_codex_row_frames(row, state)):
            filename = f"{state}.png" if frame_index == 0 else f"{state}_{frame_index}.png"
            _save_image_atomic(image, avatar_dir / filename, "PNG")
            frames.append(filename)
        state_files[state] = frames[0]
        state_frame_files[state] = frames

    view_files: dict[str, str] = {}
    for view in AVATAR_VIEW_NAMES:
        filename = f"view_{view}.png"
        _save_image_atomic(_view_from_base(base_image, view), avatar_dir / filename, "PNG")
        view_files[view] = filename
    return state_files, state_frame_files, view_files


def _write_codex_pack(
    avatar_dir: Path,
    twin: dict[str, Any],
    state_frame_files: dict[str, list[str]],
) -> dict[str, Any]:
    sheet = Image.new("RGBA", (CODEX_CELL[0] * CODEX_GRID[0], CODEX_CELL[1] * CODEX_GRID[1]), (0, 0, 0, 0))
    frame_cells: dict[str, list[int]] = {state: [] for state in DESKTOP_STATES}
    for row, state in enumerate(DESKTOP_STATES):
        frames = state_frame_files.get(state) or []
        expected_count = CODEX_PET_FRAME_COUNTS[state]
        if len(frames) != expected_count:
            raise ValueError(f"{state} requires {expected_count} frames")
        for col, filename in enumerate(frames):
            cell_index = row * CODEX_GRID[0] + col
            frame_cells[state].append(cell_index)
            frame = Image.open(avatar_dir / filename).convert("RGBA")
            frame = ImageOps.contain(frame, CODEX_CELL, Image.Resampling.LANCZOS)
            cell = Image.new("RGBA", CODEX_CELL, (0, 0, 0, 0))
            cell.alpha_composite(frame, ((CODEX_CELL[0] - frame.width) // 2, CODEX_CELL[1] - frame.height))
            sheet.alpha_composite(cell, (col * CODEX_CELL[0], row * CODEX_CELL[1]))
    spritesheet = avatar_dir / "spritesheet.webp"
    _save_image_atomic(sheet, spritesheet, "WEBP", lossless=True, quality=100, method=6, exact=True)
    display_name = str(twin.get("displayName") or "JiuMe")
    description = str(twin.get("purpose") or "JiuMe human desktop twin")
    sprite_pack = {
        "id": twin["id"],
        "displayName": display_name,
        "description": description,
        "spritesheet": "spritesheet.webp",
        "cell": {"width": CODEX_CELL[0], "height": CODEX_CELL[1]},
        "grid": {"columns": CODEX_GRID[0], "rows": CODEX_GRID[1]},
        "rows": [
            {
                "state": state,
                "row": row,
                "frames": CODEX_PET_FRAME_COUNTS[state],
                "purpose": CODEX_PET_STATE_PURPOSES[state],
            }
            for row, state in enumerate(DESKTOP_STATES)
        ],
        "animations": {
            state: {
                "frames": frame_cells[state],
                "fps": 6,
                "loop": True,
            }
            for state in DESKTOP_STATES
        },
        "format": "codex-pet-atlas",
    }
    (avatar_dir / AVATAR_PACK_FILENAME).write_text(json.dumps(sprite_pack, ensure_ascii=False, indent=2), encoding="utf-8")
    pet_json = {
        "id": twin["id"],
        "displayName": display_name,
        "description": description,
        "spritesheetPath": "spritesheet.webp",
    }
    (avatar_dir / COMPAT_SPRITE_PACK_FILENAME).write_text(json.dumps(pet_json, ensure_ascii=False, indent=2), encoding="utf-8")
    return sprite_pack


def _manifest_has_desktop_assets(manifest: dict[str, Any], avatar_dir: Path) -> bool:
    states = manifest.get("states")
    if not isinstance(states, dict):
        return False
    for state in DESKTOP_STATES:
        item = states.get(state)
        if not isinstance(item, dict):
            return False
        file_path = item.get("file")
        path = Path(file_path) if isinstance(file_path, str) and file_path else None
        if path is None:
            src = str(item.get("src") or "")
            path = avatar_dir / Path(src).name if src else None
        if path is None or not path.exists() or path.suffix.lower() not in {".png", ".webp", ".jpg", ".jpeg"}:
            return False
        frames = item.get("frames")
        if isinstance(frames, list) and frames:
            for frame in frames:
                if not isinstance(frame, dict):
                    return False
                frame_path = frame.get("file")
                frame_target = Path(frame_path) if isinstance(frame_path, str) and frame_path else None
                if frame_target is None:
                    frame_src = str(frame.get("src") or "")
                    frame_target = avatar_dir / Path(frame_src).name if frame_src else None
                if frame_target is None or not frame_target.exists():
                    return False
    views = manifest.get("views")
    if isinstance(views, dict):
        for view in AVATAR_VIEW_NAMES:
            item = views.get(view)
            if not isinstance(item, dict):
                return False
            file_path = item.get("file")
            path = Path(file_path) if isinstance(file_path, str) and file_path else None
            if path is None:
                src = str(item.get("src") or "")
                path = avatar_dir / Path(src).name if src else None
            if path is None or not path.exists():
                return False
    has_pack = (avatar_dir / AVATAR_PACK_FILENAME).exists() or (avatar_dir / COMPAT_SPRITE_PACK_FILENAME).exists()
    return has_pack and (avatar_dir / "spritesheet.webp").exists()


class AvatarService:
    def __init__(self, store: TwinStore | None = None) -> None:
        self.store = store or TwinStore()

    def upload_source(self, twin_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        twin = self.store.get_twin(twin_id)
        data, mime = _decode_source_upload(payload)
        avatar_dir = _avatar_dir(twin["id"])
        filename = f"source_{secrets.token_hex(4)}{SUPPORTED_MIME[mime]}"
        path = avatar_dir / filename
        path.write_bytes(data)
        event = append_audit_event(twin["id"], "avatar.source_uploaded", {"filename": filename, "mime": mime})
        return {"source": filename, "consent_id": event["created_at"], "mime_type": mime}

    def _write_manifest(
        self,
        twin: dict[str, Any],
        avatar_dir: Path,
        provider: str,
        state_files: dict[str, str],
        state_frame_files: dict[str, list[str]],
        view_files: dict[str, str],
        base_file: str | None = None,
        source_file: str | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        states = {
            state: {
                "src": f"/_jiume/assets/{twin['id']}/{filename}",
                "file": str(avatar_dir / filename),
                "frames": [
                    {
                        "src": f"/_jiume/assets/{twin['id']}/{frame_filename}",
                        "file": str(avatar_dir / frame_filename),
                        "index": index,
                    }
                    for index, frame_filename in enumerate(state_frame_files.get(state) or [filename])
                ],
                "fps": 6,
                "view": "front",
                "loop": True,
            }
            for state, filename in state_files.items()
        }
        views = {
            view: {
                "src": f"/_jiume/assets/{twin['id']}/{filename}",
                "file": str(avatar_dir / filename),
            }
            for view, filename in view_files.items()
        }
        sprite_pack = _write_codex_pack(avatar_dir, twin, state_frame_files)
        manifest = {
            "version": "1.0",
            "style": "q-version-2d-human-desktop-twin",
            "appearance": normalize_twin_appearance(twin.get("appearance")),
            "identity": {
                "form": "person-shaped",
                "role": "personal desktop twin",
                "agentEntryPoint": True,
            },
            "provider": provider,
            "states": states,
            "views": views,
            "desktop": {
                "defaultState": "idle",
                "size": 128,
                "alwaysOnTop": True,
                "dragAcrossScreens": True,
            },
            "spritePack": {
                "manifest": str(avatar_dir / AVATAR_PACK_FILENAME),
                "compatFile": str(avatar_dir / COMPAT_SPRITE_PACK_FILENAME),
                "spritesheet": str(avatar_dir / "spritesheet.webp"),
                "cell": sprite_pack["cell"],
                "grid": sprite_pack["grid"],
                "animations": sprite_pack["animations"],
            },
            "base": str(avatar_dir / base_file) if base_file else None,
            "generated_at": _utc_now(),
        }
        if source_file:
            manifest["sourceImage"] = {
                "src": f"/_jiume/assets/{twin['id']}/{source_file}",
                "file": str(avatar_dir / source_file),
                "role": "avatar-reference",
            }
        manifest_path = avatar_dir / "avatar_manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        if persist:
            self.store.update_twin(twin["id"], {"avatarManifestPath": f"twins/{twin['id']}/avatar/avatar_manifest.json"})
            append_audit_event(twin["id"], "avatar.generated", {"provider": provider})
        return manifest

    def _write_job(self, avatar_dir: Path, twin_id: str, provider: str, manifest: dict[str, Any]) -> dict[str, Any]:
        job = {
            "id": f"avatar_job_{secrets.token_hex(4)}",
            "twin_id": twin_id,
            "status": "completed",
            "provider": provider,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "manifest": manifest,
        }
        jobs_dir = avatar_dir / "jobs"
        jobs_dir.mkdir(parents=True, exist_ok=True)
        (jobs_dir / f"{job['id']}.json").write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        return job

    def generate_mock_avatar(self, twin_id: str) -> dict[str, Any]:
        twin = self.store.get_twin(twin_id)
        avatar_dir = _avatar_dir(twin["id"])
        state_files: dict[str, str] = {}
        appearance = normalize_twin_appearance(twin.get("appearance"))
        source_path = _latest_source_image(avatar_dir)
        base_file = None
        if source_path is not None:
            base_image = _source_photo_avatar_base(source_path, twin)
            base_file = "base_source.png"
            _save_image_atomic(base_image, avatar_dir / base_file, "PNG")
            state_files, state_frame_files, view_files = _write_avatar_frames(avatar_dir, base_image)
            manifest = self._write_manifest(
                twin,
                avatar_dir,
                "source-local",
                state_files,
                state_frame_files,
                view_files,
                base_file=base_file,
                source_file=source_path.name,
            )
            return self._write_job(avatar_dir, twin["id"], "source-local", manifest)

        state_files, state_frame_files, view_files = _write_mock_avatar_frames(
            avatar_dir,
            str(twin.get("displayName") or "JiuMe"),
            appearance,
        )
        manifest = self._write_manifest(twin, avatar_dir, "mock", state_files, state_frame_files, view_files)
        return self._write_job(avatar_dir, twin["id"], "mock", manifest)

    def generate_openai_avatar(self, twin_id: str, *, model: str | None = None) -> dict[str, Any]:
        twin = self.store.get_twin(twin_id)
        avatar_dir = _avatar_dir(twin["id"])
        source_path = _latest_source_image(avatar_dir)
        if source_path is None:
            raise ValueError("source image is required for OpenAI avatar generation")
        config = get_image_provider_config()
        api_key = config.api_key
        if not api_key:
            raise ValueError(
                "OpenAI image generation requires JIUME_OPENAI_API_KEY or OPENAI_API_KEY. "
                f"Configure it in {config.config_path}"
            )

        try:
            from openai import OpenAI

            client_kwargs = {"api_key": api_key, "timeout": OPENAI_IMAGE_TIMEOUT_SECONDS}
            if config.base_url:
                client_kwargs["base_url"] = config.base_url
            client = OpenAI(**client_kwargs)
            selected_model = model or config.model
            base_bytes = _request_openai_edit_payload(
                client,
                source_path,
                prompt=_openai_avatar_prompt(twin),
                model=selected_model,
                twin_id=twin["id"],
            )
        except Exception as exc:  # noqa: BLE001
            append_audit_event(twin["id"], "avatar.provider_failed", {"provider": "openai", "error": str(exc)})
            raise

        base_path = avatar_dir / "base_openai.png"
        base_image = _remove_sprite_chroma_key(Image.open(io.BytesIO(base_bytes)).convert("RGBA"))
        if not _has_alpha_cutout(base_image):
            base_image = _source_photo_avatar_base(source_path, twin)
        _save_image_atomic(base_image, base_path, "PNG")

        row_images: dict[str, Image.Image] = {}
        try:
            for state in DESKTOP_STATES:
                row_bytes = _request_openai_edit_payload(
                    client,
                    base_path,
                    prompt=_openai_animation_row_prompt(twin, state),
                    model=selected_model,
                    twin_id=twin["id"],
                    transparent_background=False,
                )
                row_image = _remove_sprite_chroma_key(Image.open(io.BytesIO(row_bytes)).convert("RGBA"))
                row_images[state] = row_image
                _save_image_atomic(row_image, avatar_dir / f"row_{state}.png", "PNG")
        except Exception as exc:  # noqa: BLE001
            append_audit_event(twin["id"], "avatar.provider_failed", {"provider": "openai", "error": str(exc)})
            raise

        state_files, state_frame_files, view_files = _write_openai_sprite_row_frames(avatar_dir, row_images, base_image)
        manifest = self._write_manifest(
            twin,
            avatar_dir,
            "openai",
            state_files,
            state_frame_files,
            view_files,
            base_file=base_path.name,
            source_file=source_path.name,
        )
        return self._write_job(avatar_dir, twin["id"], "openai", manifest)

    def generate_model_avatar(self, twin_id: str) -> dict[str, Any]:
        """Strict setup-time avatar generation through the configured image model."""
        return self.generate_openai_avatar(twin_id)

    def generate_avatar(self, twin_id: str, provider: str = "auto") -> dict[str, Any]:
        provider = (provider or "auto").strip().lower()
        if provider in {"openai", "gpt-image", "gpt-image-1", "gpt-image-2"}:
            return self.generate_openai_avatar(twin_id)
        config = get_image_provider_config()
        if provider == "auto" and config.has_api_key:
            try:
                return self.generate_openai_avatar(twin_id)
            except Exception:
                return self.generate_mock_avatar(twin_id)
        return self.generate_mock_avatar(twin_id)

    def generate_source_preview(self, payload: dict[str, Any], display_name: str = "JiuMe") -> dict[str, Any]:
        data, mime = _decode_source_upload(payload)
        preview_id = f"preview_{secrets.token_hex(8)}"
        twin = {
            "id": preview_id,
            "displayName": str(display_name or "JiuMe").strip() or "JiuMe",
            "purpose": "JiuMe setup avatar preview",
            "appearance": normalize_twin_appearance(None),
        }
        avatar_dir = _avatar_dir(preview_id)
        source_file = f"source_{secrets.token_hex(4)}{SUPPORTED_MIME[mime]}"
        source_path = avatar_dir / source_file
        source_path.write_bytes(data)

        base_image = _source_photo_avatar_base(source_path, twin)
        base_file = "base_source.png"
        _save_image_atomic(base_image, avatar_dir / base_file, "PNG")
        state_files, state_frame_files, view_files = _write_avatar_frames(avatar_dir, base_image)
        manifest = self._write_manifest(
            twin,
            avatar_dir,
            "source-local-preview",
            state_files,
            state_frame_files,
            view_files,
            base_file=base_file,
            source_file=source_file,
            persist=False,
        )
        return self._write_job(avatar_dir, preview_id, "source-local-preview", manifest)

    def get_manifest(self, twin_id: str) -> dict[str, Any]:
        twin = self.store.get_twin(twin_id)
        avatar_dir = _avatar_dir(twin["id"])
        path = avatar_dir / "avatar_manifest.json"
        if not path.exists():
            return self.generate_mock_avatar(twin["id"])["manifest"]
        manifest = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or not _manifest_has_desktop_assets(manifest, avatar_dir):
            return self.generate_mock_avatar(twin["id"])["manifest"]
        return manifest

    def get_job(self, twin_id: str, job_id: str) -> dict[str, Any]:
        safe_id = ensure_safe_twin_id(twin_id)
        safe_job = str(job_id or "").strip()
        if not re.match(r"^[a-zA-Z0-9_-]+$", safe_job):
            raise ValueError("invalid job_id")
        path = _avatar_dir(safe_id) / "jobs" / f"{safe_job}.json"
        if not path.exists():
            raise FileNotFoundError("avatar job not found")
        return json.loads(path.read_text(encoding="utf-8"))
