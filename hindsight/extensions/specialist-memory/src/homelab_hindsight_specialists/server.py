"""Production ASGI factory using the Hindsight 1.2.1 server construction seam.

Unlike hindsight_api.server, importing this module does not construct an engine.
Uvicorn's factory mode constructs one per worker. The original unified app owns
all initialization, migrations, MCP lifespans, worker pollers and shutdown; the
specialist boundary is outside that entire app, not an inner HTTP middleware.
"""


def create_app():
    """Build the complete upstream server, retaining its normal configuration."""
    from hindsight_api.config import get_config, load_dotenv_for_entrypoint

    load_dotenv_for_entrypoint()

    from hindsight_api.profiling import install

    install()

    import os

    os.environ['TOKENIZERS_PARALLELISM'] = 'false'

    from hindsight_api import MemoryEngine
    from hindsight_api.extensions import (
        OperationValidatorExtension, TenantExtension, load_extension,
    )
    from .ingress import create_guarded_app

    config = get_config()
    config.configure_logging()
    operation_validator = load_extension('OPERATION_VALIDATOR', OperationValidatorExtension)
    tenant_extension = load_extension('TENANT', TenantExtension)
    memory = MemoryEngine(
        operation_validator=operation_validator,
        tenant_extension=tenant_extension,
        run_migrations=config.run_migrations_on_startup,
    )
    return create_guarded_app(
        memory,
        http_api_enabled=True,
        mcp_api_enabled=config.mcp_enabled,
        mcp_mount_path='/mcp',
        initialize_memory=True,
    )


def main():
    """Run foreground workers; configure using the normal HINDSIGHT_API_* env."""
    import argparse
    from importlib.util import find_spec
    import uvicorn

    argparse.ArgumentParser(
        description='Hindsight specialist API server (configure with HINDSIGHT_API_* environment variables)'
    ).parse_args()

    from hindsight_api.config import DEFAULT_HOST, get_config, load_dotenv_for_entrypoint

    load_dotenv_for_entrypoint()
    config = get_config()
    uvicorn.run(
        'homelab_hindsight_specialists.server:create_app',
        factory=True,
        host=config.host or DEFAULT_HOST,
        port=config.port,
        workers=config.workers,
        log_level=config.log_level,
        access_log=config.access_log,
        proxy_headers=False,
        ws='wsproto',
        loop='uvloop' if find_spec('uvloop') else 'asyncio',
        timeout_keep_alive=30,
        timeout_graceful_shutdown=5,
    )


if __name__ == '__main__':
    main()
