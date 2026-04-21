"""Config flow for the E87 Smart Digital Badge integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_ADDRESS

from e87_badge import AE_SERVICE_UUID, LOCAL_NAME

from .const import DOMAIN


def _is_e87(discovery_info: BluetoothServiceInfoBleak) -> bool:
    """Return True if this advertisement looks like an E87 badge."""
    if discovery_info.name == LOCAL_NAME:
        return True
    service_uuids = [uuid.lower() for uuid in (discovery_info.service_uuids or ())]
    return AE_SERVICE_UUID.lower() in service_uuids


def _short_mac(address: str) -> str:
    """Return the last 6 hex characters of a MAC address, uppercase."""
    return address.replace(":", "").replace("-", "")[-6:].upper()


def _title_for(address: str) -> str:
    """Human title for a discovered badge."""
    return f"E87 Badge ({_short_mac(address)})"


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
        """Let the user pick a discovered-but-unconfigured E87 badge."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=_title_for(address),
                data={CONF_ADDRESS: address},
            )

        current_addresses = self._async_current_ids(include_ignore=False)
        for discovery_info in async_discovered_service_info(self.hass, False):
            address = discovery_info.address
            if address in current_addresses or address in self._discovered_devices:
                continue
            if not _is_e87(discovery_info):
                continue
            self._discovered_devices[address] = _title_for(address)

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ADDRESS): vol.In(self._discovered_devices)}
            ),
        )
