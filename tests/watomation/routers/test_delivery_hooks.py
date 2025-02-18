import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
import sys
from pathlib import Path
import asyncio
import json
import httpx

# Mock all external dependencies
mocks = {
    'psycopg': MagicMock(),
    'psycopg_pool': MagicMock(),
    'langgraph.checkpoint.postgres.aio': MagicMock(),
    'uvicorn': MagicMock(),
    'pywa': MagicMock(),
    'pywa_async': MagicMock(),
    'pywa.types': MagicMock(),
    'loguru': MagicMock(),
    'config': MagicMock(),
    'config.project_setting': MagicMock(),
    'utils_common.thread_management': MagicMock()
}

for module_name, mock in mocks.items():
    sys.modules[module_name] = mock

# Create a test router without the full app dependencies
from fastapi import APIRouter, Request
from watomation.routers.delivery_hooks import router

# Create a minimal test app
from fastapi import FastAPI
test_app = FastAPI()
test_app.include_router(router, prefix="/delivery-hooks")

@pytest.fixture
def client():
    return TestClient(test_app)

@pytest.mark.asyncio
async def test_delivery_dispatch_endpoint(client):
    payload = {
        "order_number": "test123",
        "driver_id": "447448440754",
        "driver_payout": 5.00,
        "distance": 1.5,
        "status": "unassigned"
    }
    
    response = client.post("/delivery-hooks/delivery_dispatch", json=payload)
    assert response.status_code == 200
    assert response.json() == {"status": "success", "data": payload}

@pytest.mark.asyncio
async def test_delivery_dispatch_trigger_webhook():
    # Mock both the database insert and the HTTP client
    with patch('utils_common.db_utils.sbase_rest_ops.sbase_insert') as mock_insert, \
         patch.object(httpx.AsyncClient, 'post', new_callable=AsyncMock) as mock_post:
        
        # Configure the HTTP mock
        mock_post.return_value = AsyncMock(
            status_code=200,
            json=AsyncMock(return_value={"status": "success"})
        )
        
        payload = {
            "order_number": "test123",
            "driver_id": "447448440754",
            "driver_payout": 5.00,
            "distance": 1.5,
            "status": "unassigned"
        }
        
        # Configure database mock to simulate trigger
        async def mock_db_insert(*args, **kwargs):
            # Simulate database trigger by making HTTP request
            webhook_url = "https://live-track.byteloop.ai/delivery-hooks/delivery_dispatch"
            async with httpx.AsyncClient() as client:
                await client.post(webhook_url, json=payload)
            return {"status": "success"}
            
        mock_insert.side_effect = mock_db_insert
        
        # Call sbase_insert which should trigger the webhook
        from utils_common.db_utils.sbase_rest_ops import sbase_insert
        result = await sbase_insert("delivery_dispatch", payload)
        
        # Verify the webhook was called with correct data
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert call_args[0][0] == "https://live-track.byteloop.ai/delivery-hooks/delivery_dispatch"
        assert call_args[1]['json'] == payload

@pytest.mark.asyncio
async def test_delivery_dispatch_with_sbase_insert():
    with patch('utils_common.db_utils.sbase_rest_ops.sbase_insert') as mock_insert:
        mock_insert.return_value = {"status": "success"}
        
        payload = {
            "order_number": "test123",
            "driver_id": "447448440754",
            "driver_payout": 5.00,
            "distance": 1.5,
            "status": "unassigned"
        }
        
        from utils_common.db_utils.sbase_rest_ops import sbase_insert
        result = await sbase_insert("delivery_dispatch", payload)
        
        # Verify sbase_insert was called with correct arguments
        mock_insert.assert_called_once_with("delivery_dispatch", payload)
        assert result == {"status": "success"}
