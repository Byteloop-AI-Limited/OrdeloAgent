"""Route coverage for Ordelo's operational cache reset endpoint."""

from __future__ import annotations


def test_operational_cache_reset_uses_shared_path_and_keeps_legacy_path(
    monkeypatch,
) -> None:
    from config import waba_business_settings

    # The application registers encrypted WhatsApp Flow handlers at import
    # time.  The shared test environment normally leaves this empty because
    # router tests do not need it; a non-empty inert value is sufficient here.
    monkeypatch.setattr(
        waba_business_settings,
        "private_key_base64",
        "dGVzdA==",  # base64 for the inert value "test"
    )

    from watomation.fapp_ordelo_agent import app

    post_paths = {
        route.path
        for route in app.routes
        if "POST" in getattr(route, "methods", set())
    }

    assert "/internal/cache/reset" in post_paths
    assert "/restaurant-base-url-cache/reset" in post_paths
