"""Constants for the E87 Smart Digital Badge integration."""

from __future__ import annotations

DOMAIN = "e87_badge"

PLATFORMS = ["sensor"]

SERVICE_SEND_IMAGE = "send_image"
SERVICE_SEND_TEXT = "send_text"
SERVICE_SEND_SLIDESHOW = "send_slideshow"
SERVICE_SEND_GIF = "send_gif"
SERVICE_SEND_DANMAKU = "send_danmaku"

ATTR_IMAGE = "image"
ATTR_IMAGES = "images"
ATTR_TEXT = "text"
ATTR_FG = "fg"
ATTR_BG = "bg"
ATTR_COLOUR = "colour"
ATTR_FONT = "font"
ATTR_SIZE = "size"
ATTR_FONT_SIZE = "font_size"
ATTR_FRAME_MS = "frame_ms"
ATTR_SPEED = "speed"
ATTR_FPS = "fps"
ATTR_MAX_FPS = "max_fps"
