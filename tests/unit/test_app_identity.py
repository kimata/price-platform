from __future__ import annotations

from pathlib import Path

import price_platform.application
import price_platform.config
import price_platform.webapp
from price_platform.identity import AppIdentity


def test_app_identity_derives_extension_key_and_default_flask_name() -> None:
    identity = AppIdentity(
        app_slug="demo-app",
        python_package="demo_app",
        url_prefix="/demo",
        config_env_var="DEMO_APP_CONFIG",
        default_liveness_file=Path("/dev/shm/demo-app/healthz"),
    )

    assert identity.extension_key == "demo_app.webapi.dependencies"
    assert identity.resolved_flask_app_name == "demo_app_webui"


def test_create_profiled_app_config_binds_identity_spec() -> None:
    identity = AppIdentity(
        app_slug="demo-app",
        python_package="demo_app",
        url_prefix="/demo",
        config_env_var="DEMO_APP_CONFIG",
        default_liveness_file=Path("/dev/shm/demo-app/healthz"),
    )

    config_cls = price_platform.config.create_profiled_app_config(identity)

    assert config_cls.PROFILE.env_var_name == "DEMO_APP_CONFIG"
    assert config_cls.PROFILE.default_liveness_file == Path("/dev/shm/demo-app/healthz")


def test_build_standard_webapi_context_uses_identity_extension_key() -> None:
    identity = AppIdentity(
        app_slug="demo-app",
        python_package="demo_app",
        url_prefix="/demo",
        config_env_var="DEMO_APP_CONFIG",
        default_liveness_file=Path("/dev/shm/demo-app/healthz"),
    )

    context = price_platform.application.build_standard_webapi_context(
        identity=identity,
        price_store_type=dict,
        price_event_store_type=list,
        service_builder=lambda _config: price_platform.webapp.build_app_services(),
    )

    assert context.spec.extension_key == "demo_app.webapi.dependencies"
