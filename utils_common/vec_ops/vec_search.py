# %%
import httpx
from config import pg_settings
from utils_common.lg_utils import generate_embedding


# %%

def menu_search(
    food_item: str, 
    match_threshold: float = 0.30, 
    match_count: int = 10,
    item_type: str = None
    ):
    """
    Search for documents using vector similarity.
    
    Args:
        food_item: The food item to search for
        match_threshold: Minimum similarity threshold for matches
        match_count: Maximum number of matches to return
    """
    metadata_filter = {} if item_type is None else {"item_type": item_type}
    response = httpx.post(
        url=pg_settings.rest_endpoint_function,
        headers=pg_settings.headers,
        json={
            "query_embedding": generate_embedding(food_item),
            "match_threshold": match_threshold,
            "match_count": match_count,
            "metadata_filter": metadata_filter
        }
    )
    return response.json()
