"""Services for the E87 Smart Digital Badge integration."""

from __future__ import annotations

import base64
import binascii
import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service import async_extract_referenced_entity_ids

from .const import (
    ATTR_BG,
    ATTR_COLOUR,
    ATTR_FG,
    ATTR_FONT,
    ATTR_FONT_SIZE,
    ATTR_FPS,
    ATTR_FRAME_MS,
    ATTR_IMAGE,
    ATTR_IMAGES,
    ATTR_MAX_FPS,
    ATTR_SIZE,
    ATTR_SPEED,
    ATTR_TEXT,
    DOMAIN,
    SERVICE_SEND_DANMAKU,
    SERVICE_SEND_GIF,
    SERVICE_SEND_IMAGE,
    SERVICE_SEND_SLIDESHOW,
    SERVICE_SEND_TEXT,
)
from .coordinator import E87ConfigEntry, E87Coordinator

_LOGGER = logging.getLogger(__name__)


# Services use a `target:` selector in services.yaml, so HA's service framework
# passes target info (entity_id, device_id, area_id, etc.) separately from data.
# We resolve the target to a list of entity IDs in the handler via
# async_extract_referenced_entity_ids. Our schemas therefore only validate the
# data fields and ALLOW_EXTRA so HA can include its target keys without error.

SCHEMA_SEND_IMAGE = cv.make_entity_service_schema(
    {vol.Required(ATTR_IMAGE): cv.string}
)

SCHEMA_SEND_TEXT = cv.make_entity_service_schema(
    {
        vol.Required(ATTR_TEXT): cv.string,
        vol.Optional(ATTR_FONT): cv.string,
        vol.Optional(ATTR_SIZE, default=72): vol.All(int, vol.Range(min=8, max=512)),
        vol.Optional(ATTR_COLOUR, default="white"): cv.string,
        vol.Optional(ATTR_BG, default="black"): cv.string,
    }
)

SCHEMA_SEND_SLIDESHOW = cv.make_entity_service_schema(
    {
        vol.Required(ATTR_IMAGES): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_FRAME_MS, default=500): vol.All(
            int, vol.Range(min=50, max=5000)
        ),
    }
)

SCHEMA_SEND_GIF = cv.make_entity_service_schema(
    {
        vol.Required(ATTR_IMAGE): cv.string,
        vol.Optional(ATTR_MAX_FPS, default=24): vol.All(
            int, vol.Range(min=1, max=30)
        ),
    }
)

SCHEMA_SEND_DANMAKU = cv.make_entity_service_schema(
    {
        vol.Required(ATTR_TEXT): cv.string,
        vol.Optional(ATTR_FG, default="white"): cv.string,
        vol.Optional(ATTR_BG, default="black"): cv.string,
        vol.Optional(ATTR_FONT): cv.string,
        vol.Optional(ATTR_FONT_SIZE, default=64): vol.All(
            int, vol.Range(min=8, max=512)
        ),
        vol.Optional(ATTR_SPEED, default=4): vol.All(int, vol.Range(min=1, max=20)),
        vol.Optional(ATTR_FPS, default=20): vol.All(int, vol.Range(min=5, max=30)),
    }
)


def _looks_like_base64(value: str) -> bool:
    """Return True if value looks like a base64-encoded binary blob."""
    stripped = value.strip()
    if len(stripped) < 32 or "/" in stripped and "." in stripped:
        # Paths with slashes + dots (e.g. /config/foo.png) are not base64.
        return False
    # Base64 alphabet + padding only.
    alphabet = set(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n\r"
    )
    return all(ch in alphabet for ch in stripped)


async def _load_image(hass: HomeAssistant, value: str) -> bytes | Path:
    """Resolve an image reference to bytes or a filesystem Path.

    Accepts:
        - A local path (must be under hass.config.allowlist_external_dirs).
        - An http(s):// URL (fetched via the shared aiohttp session).
        - A data: URI (data:image/png;base64,...).
        - A bare base64 string.
    """
    if value.startswith(("http://", "https://")):
        session = async_get_clientsession(hass)
        async with session.get(value) as resp:
            if resp.status != 200:
                raise HomeAssistantError(
                    f"Failed to fetch image from {value}: HTTP {resp.status}"
                )
            return await resp.read()

    if value.startswith("data:"):
        try:
            _, _, b64 = value.partition(",")
            return base64.b64decode(b64, validate=False)
        except (binascii.Error, ValueError) as exc:
            raise HomeAssistantError(f"Invalid data URI: {exc}") from exc

    # Try filesystem path first.
    path = Path(value)
    if path.is_absolute() and path.exists():
        if not hass.config.is_allowed_path(str(path)):
            raise HomeAssistantError(
                f"Path {path} is not in allowlist_external_dirs"
            )
        return path

    # Fall back to bare base64.
    if _looks_like_base64(value):
        try:
            return base64.b64decode(value, validate=False)
        except (binascii.Error, ValueError) as exc:
            raise HomeAssistantError(f"Invalid base64 image: {exc}") from exc

    raise HomeAssistantError(
        f"Could not interpret image reference {value!r}: "
        "not a URL, data URI, allowed path, or base64 string"
    )


async def _load_images(
    hass: HomeAssistant, values: list[str]
) -> list[bytes | Path]:
    """Resolve each entry of a slideshow."""
    return [await _load_image(hass, v) for v in values]


async def _coordinators_for_call(
    hass: HomeAssistant, call: ServiceCall
) -> list[E87Coordinator]:
    """Resolve the target selector into a list of E87 coordinators."""
    referenced = async_extract_referenced_entity_ids(hass, call)
    entity_ids = referenced.referenced | referenced.indirectly_referenced
    if not entity_ids:
        raise HomeAssistantError(
            "No target entity, device, or area selected. Pick the badge's "
            "status sensor as the target."
        )

    ent_reg = er.async_get(hass)
    seen_entries: set[str] = set()
    coordinators: list[E87Coordinator] = []
    for entity_id in entity_ids:
        entry = ent_reg.async_get(entity_id)
        if entry is None or entry.platform != DOMAIN:
            # Target may resolve to entities that aren't ours (e.g. when an
            # area contains mixed integrations) — skip silently.
            continue
        config_entry_id = entry.config_entry_id
        if config_entry_id is None or config_entry_id in seen_entries:
            continue
        seen_entries.add(config_entry_id)
        config_entry: E87ConfigEntry | None = hass.config_entries.async_get_entry(
            config_entry_id
        )
        if config_entry is None or config_entry.state is not ConfigEntryState.LOADED:
            raise HomeAssistantError(
                f"E87 config entry for {entity_id} is not loaded"
            )
        coordinators.append(config_entry.runtime_data)
    if not coordinators:
        raise HomeAssistantError(
            "The selected target does not include any E87 badge entities"
        )
    return coordinators


async def _handle_send_image(call: ServiceCall) -> None:
    hass = call.hass
    image = await _load_image(hass, call.data[ATTR_IMAGE])
    for coord in await _coordinators_for_call(hass, call):
        await coord.send_image(image)


async def _handle_send_text(call: ServiceCall) -> None:
    hass = call.hass
    opts: dict[str, Any] = {
        "size": call.data[ATTR_SIZE],
        "colour": call.data[ATTR_COLOUR],
        "bg": call.data[ATTR_BG],
    }
    if ATTR_FONT in call.data:
        opts["font"] = call.data[ATTR_FONT]
    for coord in await _coordinators_for_call(hass, call):
        await coord.send_text(call.data[ATTR_TEXT], **opts)


async def _handle_send_slideshow(call: ServiceCall) -> None:
    hass = call.hass
    images = await _load_images(hass, call.data[ATTR_IMAGES])
    opts = {"frame_ms": call.data[ATTR_FRAME_MS]}
    for coord in await _coordinators_for_call(hass, call):
        await coord.send_slideshow(images, **opts)


async def _handle_send_gif(call: ServiceCall) -> None:
    hass = call.hass
    src = await _load_image(hass, call.data[ATTR_IMAGE])
    opts = {"max_fps": call.data[ATTR_MAX_FPS]}
    for coord in await _coordinators_for_call(hass, call):
        await coord.send_gif(src, **opts)


async def _handle_send_danmaku(call: ServiceCall) -> None:
    hass = call.hass
    opts: dict[str, Any] = {
        "fg": call.data[ATTR_FG],
        "bg": call.data[ATTR_BG],
        "font_size": call.data[ATTR_FONT_SIZE],
        "speed_px_per_frame": call.data[ATTR_SPEED],
        "fps": call.data[ATTR_FPS],
    }
    if ATTR_FONT in call.data:
        opts["font"] = call.data[ATTR_FONT]
    for coord in await _coordinators_for_call(hass, call):
        await coord.send_danmaku(call.data[ATTR_TEXT], **opts)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the E87 services on the hass instance."""
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_IMAGE, _handle_send_image, schema=SCHEMA_SEND_IMAGE
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_TEXT, _handle_send_text, schema=SCHEMA_SEND_TEXT
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_SLIDESHOW,
        _handle_send_slideshow,
        schema=SCHEMA_SEND_SLIDESHOW,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_GIF, _handle_send_gif, schema=SCHEMA_SEND_GIF
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_DANMAKU,
        _handle_send_danmaku,
        schema=SCHEMA_SEND_DANMAKU,
    )


@callback
def async_unload_services(hass: HomeAssistant) -> None:
    """Remove the E87 services from the hass instance."""
    for service in (
        SERVICE_SEND_IMAGE,
        SERVICE_SEND_TEXT,
        SERVICE_SEND_SLIDESHOW,
        SERVICE_SEND_GIF,
        SERVICE_SEND_DANMAKU,
    ):
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)
