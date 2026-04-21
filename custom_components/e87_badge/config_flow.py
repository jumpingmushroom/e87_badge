"""Config flow for the E87 Smart Digital Badge integration."""

from __future__ import annotations

import re
from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from e87_badge import AE_SERVICE_UUID, LOCAL_NAME
from e87_badge.const import ADVERT_MANUFACTURER_ID, ADVERT_SERVICE_UUID_16

from .const import DOMAIN

MAC_REGEX = re.compile(r"^[0-9a-f]{2}([:-])(?:[0-9a-f]{2}\1){4}[0-9a-f]{2}$", re.IGNORECASE)
MANUAL_ENTRY_SENTINEL = "__manual__"


def _is_e87(discovery_info: BluetoothServiceInfoBleak) -> bool:
    """Return True if this advertisement looks like an E87 badge.

    Matches on any of:
    - `local_name == "E87"` (scan response, needs active scan)
    - Advertised 16-bit service UUID 0xFD00 (primary advert, passive-safe)
    - Advertised primary service UUID 0xAE00 (some firmware variants)
    - Manufacturer data with company ID 28083 (passive-safe fingerprint)
    """
    if discovery_info.name == LOCAL_NAME:
        return True
    service_uuids = {u.lower() for u in (discovery_info.service_uuids or ())}
    if ADVERT_SERVICE_UUID_16.lower() in service_uuids:
        return True
    if AE_SERVICE_UUID.lower() in service_uuids:
        return True
    if discovery_info.manufacturer_data and ADVERT_MANUFACTURER_ID in discovery_info.manufacturer_data:
        return True
    return False


def _short_mac(address: str) -> str:
    """Return the last 6 hex characters of a MAC address, uppercase."""
    return address.replace(":", "").replace("-", "")[-6:].upper()


def _title_for(address: str) -> str:
    """Human title for a discovered badge."""
    return f"E87 Badge ({_short_mac(address)})"


def _normalise_mac(value: str) -> str:
    """Normalise a user-entered MAC to uppercase `AA:BB:CC:DD:EE:FF`."""
    cleaned = value.strip().replace("-", ":")
    return cleaned.upper()


class E87BadgeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for E87 Smart Digital Badge."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle the bluetooth discovery step."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        if not _is_e87(discovery_info):
            return self.async_abort(reason="not_supported")
        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {
            "name": _title_for(discovery_info.address)
        }
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the discovered badge."""
        assert self._discovery_info is not None
        discovery_info = self._discovery_info
        title = _title_for(discovery_info.address)

        if user_input is not None:
            return self.async_create_entry(
                title=title,
                data={CONF_ADDRESS: discovery_info.address},
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": title},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user pick a discovered badge or enter a MAC manually."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            if address == MANUAL_ENTRY_SENTINEL:
                return await self.async_step_manual()
            return await self._create_entry_for(address)

        current_addresses = self._async_current_ids(include_ignore=False)
        for discovery_info in async_discovered_service_info(self.hass, False):
            address = discovery_info.address
            if address in current_addresses or address in self._discovered_devices:
                continue
            if not _is_e87(discovery_info):
                continue
            self._discovered_devices[address] = _title_for(address)

        # When nothing was discovered, skip straight to manual entry rather
        # than dead-ending with "no_devices_found". The badge shows its MAC
        # on screen alongside a QR code when unpaired.
        if not self._discovered_devices:
            return await self.async_step_manual()

        choices = dict(self._discovered_devices)
        choices[MANUAL_ENTRY_SENTINEL] = "Enter MAC address manually…"
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(choices)}
            ),
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Accept a MAC address typed in by the user (read from the badge's
        on-screen QR code / MAC display when unpaired)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            raw = user_input[CONF_ADDRESS]
            if not MAC_REGEX.match(raw.strip()):
                errors[CONF_ADDRESS] = "invalid_mac"
            else:
                return await self._create_entry_for(_normalise_mac(raw))

        return self.async_show_form(
            step_id="manual",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): str}),
            errors=errors,
        )

    async def _create_entry_for(self, address: str) -> ConfigFlowResult:
        await self.async_set_unique_id(address, raise_on_progress=False)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=_title_for(address),
            data={CONF_ADDRESS: address},
        )
