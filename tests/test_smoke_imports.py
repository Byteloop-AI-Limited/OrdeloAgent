"""Smoke test: import every in-scope production module under the fake config layer.

If this passes, the global conftest's ``aws_setting`` injection and Google
credentials patch are sufficient for unit tests to import production code
without network or DB access.

Each import is its own test so a failure points at a specific module.

Key Functions:
  - test_import_<module> - importlib.import_module assertion per target module
"""

from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        # config layer
        "config",
        "config.project_setting",
        "config.pg_setting",
        "config.waba_setting",
        "config.llm_setting",
        "config.microservices_setting",
        "config.google_setting",
        "config.params",
        "config.logger_setting",
        # utils_common
        "utils_common.tz_utils",
        "utils_common.params",
        "utils_common.thread_handlers",
        "utils_common.lg_utils",
        "utils_common.wa_utils",
        "utils_common.thread_management",
        "utils_common.thread_management.thread_handler",
        "utils_common.db_utils.sbase_rest_ops",
        "utils_common.db_utils.sbase_pool_ops",
        # checkpointer_setup is a one-off DDL script (runs at import); excluded.
        "utils_common.order_management",
        "utils_common.order_management.food_order_pymodel",
        "utils_common.order_management.food_order_reciept",
        "utils_common.order_management.order_db_ops_new",
        "utils_common.order_management.order_service",
        "utils_common.order_management.order_num_gen",
        "utils_common.order_management.delivery_pymodels",
        "utils_common.waba_utils.wa_senders",
        "utils_common.maps_service.address_resolver",
        "utils_common.payment_ms.payment",
        # ordelo_datamodels
        "ordelo_datamodels.delivery_pymodels",
        "ordelo_datamodels.location_pymodels",
        "ordelo_datamodels.restaurant_master_pymodel",
        "ordelo_datamodels.customer_master_pymodel",
        "ordelo_datamodels.cust_rest_map_pymodel",
        # ordelo agents + handlers
        "ordelo.agent_app_handlers",
        "ordelo.agents.rider_agent",
        "ordelo.agents.agent_runner",
        # watomation routers + handlers
        "watomation.on_message_wa_handler",
        "watomation.on_callback_wa_handler",
        "watomation.on_flow_request_wa_handler",
        "watomation.on_flow_request_postcode_search",
        "watomation.routers.delivery_hooks",
        "watomation.routers.takeaway_hooks",
        "watomation.routers.order_hooks",
        "watomation.routers.payment_hooks",
        "watomation.routers.thread_hooks",
        "watomation.routers.location_hooks",
        "watomation.routers.customer_hooks",
    ],
)
def test_import(module_name: str) -> None:
    """Each in-scope module imports without contacting the network."""
    importlib.import_module(module_name)
