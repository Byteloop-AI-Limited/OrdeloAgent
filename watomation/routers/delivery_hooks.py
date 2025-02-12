from fastapi import APIRouter, Request

# https://live-track.byteloop.ai/delivery-hooks
router = APIRouter(tags=["delivery_hooks"])

@router.get("/")
async def root():
    return {"message": "Delivery Hooks Router"}

@router.post("/delivery_dispatch")
async def delivery_dispatch_hook(request: Request):
    payload = await request.json()
    print(f"Received delivery dispatch webhook: {payload}")
    return {"status": "success", "data": payload}
