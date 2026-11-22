"""Household control/proposals; no model-accessible approval capability."""
async def async_setup(hass, config):
    from .runtime import setup
    return await setup(hass, config)
