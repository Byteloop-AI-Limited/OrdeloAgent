"""Global pytest configuration and autouse fakes for OrdeloAgent.

This conftest must run before any production module is imported because the
real `aws_setting.agent_env` triggers a live boto3 SecretsManager call
at module import time, and many `config/*.py` modules instantiate clients
(supabase, pywa, langchain) directly off that env dict.

The strategy:
  - Inject a fake `aws_setting` module into ``sys.modules`` exposing a stub
    ``agent_env`` dict with every key the production ``BaseSettings``
    classes look for.
  - Patch ``google.oauth2.service_account.Credentials.from_service_account_info``
    so ``config.google_setting`` does not need a real PEM key.
  - Provide reusable fakes (Supabase client, async pg pool, WhatsApp client,
    LLM, builders) via fixtures defined in ``tests.fixtures``.

Key Functions:
  - _install_fake_aws_setting - Inject stub aws_setting into sys.modules
  - _install_google_credentials_patch - Stub Google service-account loader
  - _ensure_project_root_on_path - Guarantee imports resolve from repo root
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Step 1: project root on sys.path so `import config`, `import watomation` work
# ---------------------------------------------------------------------------


def _ensure_project_root_on_path() -> Path:
    project_root = Path(__file__).resolve().parent.parent
    root_str = str(project_root)
    if root_str not in sys.path:
        sys.path.insert(0, root_str)
    return project_root


PROJECT_ROOT = _ensure_project_root_on_path()


# ---------------------------------------------------------------------------
# Step 2: stub `aws_setting` BEFORE any production module imports it
# ---------------------------------------------------------------------------

#: Every key any production ``BaseSettings`` class reads off ``agent_env``.
#: Discovered from the ``Field(..., alias=...)`` declarations in ``config/*.py``.
_STUB_AGENT_ENV: dict = {
    # Project
    "project_settings_salt": "test-salt",
    "project_settings_rest_ref": "TEST",
    # Postgres / Supabase
    "sbase_ordelo_db_uri": "postgresql://test:test@localhost:5432/test",
    "sbase_ordelo_vec_db_uri": "postgresql://test:test@localhost:5432/test",
    "sbase_ordelo_rest_url": "https://test.supabase.co",
    "sbase_ordelo_rest_key": "test-rest-key",
    "sbase_ordelo_service_key": "test-service-key",
    # WhatsApp Business Account (NAMESPACE=bloop)
    "bloop_waa_account_id": "test-account-id",
    "bloop_waa_token": "test-token",
    "bloop_waa_phone_id": 1234567890,
    "bloop_waa_callback_url": "https://test.example.com/",
    "bloop_waa_verify_token": "test-verify-token",
    "bloop_waa_app_id": "test-app-id",
    "bloop_waa_app_secret": "test-app-secret",
    "bloop_waa_private_key_password": "test-private-key-password",
    # Empty base64 -> private_key getter returns "" gracefully
    "bloop_waa_private_key_base64": "",
    # WhatsApp Provider
    "waba_provider_app_id": "test-provider-app-id",
    "waba_provider_app_secret": "test-provider-app-secret",
    "waba_provider_configuration_id": "test-config-id",
    "waba_provider_graph_api_version": "v18.0",
    "waba_provider_pin": "000000",
    "waba_provider_token": "test-provider-token",
    "waba_provider_business_protfolio_id": "test-portfolio-id",
    # LLM
    "llm_model": "gpt-4o-mini",
    "llm_openai_api_key": "test-openai-key",
    # Microservices
    "ms_stripe_url": "https://test.example.com/stripe",
    "ms_stripe_url_test": "https://test.example.com/stripe-test",
    "ms_stripe_token": "test-stripe-token",
    "ms_pricing_url": "https://test.example.com/pricing",
    # Google
    "google_service_account_email": "test@test.iam.gserviceaccount.com",
    # Real-looking base64 (decoded to "{}") is enough because we patch the
    # credentials loader below; google_setting.get_client only reaches the
    # base64.b64decode/json.loads pair before our patched class kicks in.
    "google_service_account_encoded_credentials": "e30=",  # base64 of "{}"
    "google_service_account_maps_api_key": "test-maps-api-key",
    # Telegram (restaurant-admin bot)
    "tgram_rest_admin_bot_token": "123456:TEST-token",
    "tgram_rest_admin_bot_username": "test_rest_admin_bot",
    "tgram_rest_admin_webhook_secret": "test-tgram-secret",
    "tgram_rest_admin_webhook_base_url": "https://test.example.com",
}


def _install_fake_aws_setting() -> None:
    """Pre-populate ``sys.modules['aws_setting']`` so production imports skip boto3."""
    if "aws_setting" in sys.modules:
        # Already imported (e.g. user's editor pre-imported). Replace its env.
        sys.modules["aws_setting"].agent_env = dict(_STUB_AGENT_ENV)
        return

    fake = types.ModuleType("aws_setting")
    fake.__doc__ = "Pytest stub for aws_setting; bypasses boto3 at import time."
    fake.agent_env = dict(_STUB_AGENT_ENV)
    fake.is_running_on_lambda = lambda: False
    fake.get_secrets_client = lambda: MagicMock(name="FakeSecretsClient")
    fake.get_agent_env = lambda *_a, **_kw: dict(_STUB_AGENT_ENV)

    # Minimal AwsSettings stub so ``from aws_setting import AwsSettings`` works.
    class _AwsSettings:
        key_id = "test"
        access_key = "test"
        region = "eu-west-2"
        secret_name = "ordelo-agent-env"

        @property
        def secrets_client(self):
            return MagicMock(name="FakeSecretsClient")

        def get_secret(self):
            return "{}"

    fake.AwsSettings = _AwsSettings
    sys.modules["aws_setting"] = fake


_install_fake_aws_setting()


# ---------------------------------------------------------------------------
# Step 3: patch Google service-account loader so config.google_setting imports cleanly
# ---------------------------------------------------------------------------


def _install_google_credentials_patch() -> None:
    """Replace ``Credentials.from_service_account_info`` with a no-op."""
    try:
        from google.oauth2 import service_account
    except ImportError:
        # google package not installed; nothing to patch.
        return

    def _stub_from_service_account_info(info, *args, **kwargs):  # noqa: ARG001
        return MagicMock(name="FakeGoogleCredentials")

    service_account.Credentials.from_service_account_info = staticmethod(  # type: ignore[assignment]
        _stub_from_service_account_info
    )


_install_google_credentials_patch()


# ---------------------------------------------------------------------------
# Step 4: expose shared fixtures from tests.fixtures
# ---------------------------------------------------------------------------

# Import after the stubs above are in place. ``tests.fixtures`` itself never
# imports production modules at module load; it only defines fixtures.
pytest_plugins = ("tests.fixtures.fixtures_pkg",)


# ---------------------------------------------------------------------------
# Step 5: ordelo_config feature flags are off unless a test turns them on
# ---------------------------------------------------------------------------

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def feature_flags(monkeypatch):
    """Set of enabled ``ordelo_config`` flag keys; empty (all off) by default.

    Tests turn a flag on with ``feature_flags.add("ELAS_WEB_ORDERING_PAUSED")``.
    """
    from config import feature_flags as flags_module

    enabled: set[str] = set()
    monkeypatch.setattr(flags_module, "_read_flag", lambda key: key in enabled)
    flags_module.reset_feature_flag_cache()
    yield enabled
    flags_module.reset_feature_flag_cache()


@pytest.fixture(autouse=True)
def quiet_telegram_notices(monkeypatch):
    """The Telegram side of restaurant_notifier does nothing in tests (it would reach the bot and the database).

    A test that wants to see Telegram notices uses ``restaurant_notifier.use_adapters(telegram=...)``."""
    from utils_common.notify import restaurant_notifier

    class _Nothing:
        async def send(self, notice):
            return None

    monkeypatch.setattr(restaurant_notifier, "_telegram", _Nothing())


@pytest.fixture(autouse=True)
def config_values(monkeypatch):
    """ordelo_config string values; empty (all unset) by default.

    Tests set one with ``config_values["RESTAURANT_MENU_APP_URL"] = "https://restaurant-test.ordelo.app"``.
    """
    from config import feature_flags as flags_module

    values: dict[str, str] = {}
    monkeypatch.setattr(flags_module, "_read_str", lambda key: values.get(key))
    flags_module.reset_feature_flag_cache()
    yield values
    flags_module.reset_feature_flag_cache()


# ---------------------------------------------------------------------------
# Step 6: customer notifier with persistence faked (R3.1: always on)
# ---------------------------------------------------------------------------


@pytest.fixture
def inline_notifier(monkeypatch):
    """publish() records in memory and dispatches at once through the real adapters.

    Set ``inline_notifier.webhook`` to the restaurant-app URL lookup a test needs;
    ``inline_notifier.finished`` collects (outbox_id, status, error).
    """
    from types import SimpleNamespace
    from utils_common.notify import customer_notifier as notifier
    from utils_common.order_management.customer_keys import is_web_customer_key

    state = SimpleNamespace(events=[], finished=[], recipient="447400000000", webhook=None)

    async def record(order_number, event):
        state.events.append((order_number, event.data()))
        return [len(state.events)]

    async def claim(outbox_id):
        order_number, data = state.events[outbox_id - 1]
        web = is_web_customer_key(state.recipient)
        return {
            "order_number": order_number,
            "data": data,
            "channel": "web_page" if web else "whatsapp_restaurant",
            "active": True,
            "origin_channel": "web" if web else "whatsapp",
            "recipient": state.recipient,
            "destination": None if web else state.recipient,
            "detail_level": "full",
        }

    async def finish(outbox_id, status, error=None):
        state.finished.append((outbox_id, status, error))

    async def webhook(rest_ref, webhook_type):
        return await state.webhook(rest_ref, webhook_type)

    monkeypatch.setattr(notifier, "_record", record)
    monkeypatch.setattr(notifier, "_claim", claim)
    monkeypatch.setattr(notifier, "_finish", finish)
    monkeypatch.setattr(notifier, "get_restaurant_webhook_url_async", webhook)
    return state
