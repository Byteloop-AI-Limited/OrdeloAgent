# %% 
from config import pg_settings
import httpx
import re

HEADERS = pg_settings.headers

# %% sbase_call_function
async def sbase_call_function(function_name: str, input_args: dict):
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{pg_settings.rest_url}/rest/v1/rpc/{function_name}", 
                headers=HEADERS,
                json=input_args
            )
        except httpx.RequestError as e:
            raise RuntimeError(f"Network error occurred: {str(e)}")
    
    return response.json()

# await sbase_call_function('dispatch_complete', {'p_dispatch_id': 11})


# %% SQL to Supabase REST condition

def sql_to_supabase_rest(**kwargs):
    """
    Convert keyword arguments to Supabase REST API query format.

    Args:
        **kwargs: Keyword arguments representing column conditions.
                 Supported operators: =, >, <, !=, LIKE
                 Example: column1='value1', column2__gt=10, column3__neq='value3'

    Returns:
        str: A formatted Supabase REST API query string.
    """
    rest_conditions = []

    for key, value in kwargs.items():
        if '__' in key:
            # Handle special operators
            column, operator = key.split('__')
            if operator == 'gt':
                rest_conditions.append(f"{column}=gt.{value}")
            elif operator == 'lt':
                rest_conditions.append(f"{column}=lt.{value}")
            elif operator == 'neq':
                rest_conditions.append(f"{column}=neq.{value}")
            elif operator == 'like':
                rest_conditions.append(f"{column}=ilike.{value}")
        else:
            # Handle equality
            rest_conditions.append(f"{key}=eq.{value}")

    return '&'.join(rest_conditions)


rest_query = sql_to_supabase_rest(reservation_id='RES-UOYH-23')


# %%

def get_sql_condition_new(**kwargs) -> str:
    """
    Creates a SQL condition string from various types of filters, including:
    - String equality and LIKE queries (with '%')
    - Numeric equality (int, float)
    - Comparison operators (e.g., '>10', '<=20') provided as strings
    - Lists of values resulting in OR conditions
    
    Args:
        **kwargs: 
            Key-value pairs of columns and their filtering values.
            Supported types:
              - str: If contains '%', will use LIKE. If starts with comparison operators 
                     ('>', '<', '>=', '<=', '=') followed by a number, it will use that operator.
                     Otherwise, uses equality.
              - int or float: Uses equality (e.g., `key = 10`).
              - list: Creates an OR condition. Each element in the list is treated similarly to
                      the single value case (str with/without '%', numeric, etc.).
    
    Returns:
        str: A SQL WHERE condition string (without the WHERE keyword), 
             with conditions joined by AND.
    """

    conditions = []
    comparison_pattern = re.compile(r'^(>=|<=|>|<|=)(\d+(\.\d+)?)$')

    def process_value(key, value):
        # Handle string values
        if isinstance(value, str):
            if '%' in value:
                # LIKE condition
                return f"{key} LIKE '{value}'"
            else:
                # Check if it matches a comparison operator pattern
                match = comparison_pattern.match(value)
                if match:
                    operator, numeric_str, _ = match.groups()
                    return f"{key} {operator} {numeric_str}"
                else:
                    # Simple equality
                    return f"{key} = '{value}'"

        # Handle numeric values (int, float)
        elif isinstance(value, (int, float)):
            return f"{key} = {value}"

        # Handle lists
        elif isinstance(value, list):
            # Build an OR condition
            or_parts = []
            for v in value:
                if isinstance(v, (int, float)):
                    or_parts.append(f"{key} = {v}")
                elif isinstance(v, str):
                    if '%' in v:
                        or_parts.append(f"{key} LIKE '{v}'")
                    else:
                        # Check for comparison
                        match = comparison_pattern.match(v)
                        if match:
                            operator, numeric_str, _ = match.groups()
                            or_parts.append(f"{key} {operator} {numeric_str}")
                        else:
                            or_parts.append(f"{key} = '{v}'")
                else:
                    raise TypeError(f"Invalid data type in list for {key}. Expected string, int, or float.")
            return "(" + " OR ".join(or_parts) + ")"
        else:
            raise TypeError(f"Invalid data type for {key}. Expected string, int, float, or list.")

    for key, value in kwargs.items():
        conditions.append(process_value(key, value))

    return ' AND '.join(conditions)



# %% Select data
async def sbase_get(table_name: str, **kwargs):
    """
    Async function to fetch data from Supabase REST API.

    Args:
        table_name (str): Name of the Supabase table
        **kwargs: Filtering conditions for the query

    Returns:
        dict: JSON response from Supabase

    Raises:
        ValueError: If the Supabase response contains an error code
        RuntimeError: For other unexpected errors during the API call
    """

    # Convert kwargs to Supabase REST filter
    rest_filter = sql_to_supabase_rest(**kwargs)

    # Use AsyncClient for async HTTP requests
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{pg_settings.rest_url}/rest/v1/{table_name}?{rest_filter}", 
                headers=HEADERS
            )
            
            # Parse the response
            response_data = response.json()
            
            # Check for error codes in the response
            if isinstance(response_data, dict) and 'code' in response_data:
                # Raise a specific error with detailed message
                error_message = f"Supabase API Error: {response_data.get('message', 'Unknown error')} " \
                                f"(Code: {response_data.get('code', 'N/A')})"
                raise ValueError(error_message)
            
            return response_data
        
        except httpx.RequestError as e:
            # Handle network-related errors
            raise RuntimeError(f"Network error occurred: {str(e)}")
        except ValueError as ve:
            # Re-raise ValueError from Supabase response
            raise
        except Exception as e:
            # Catch any other unexpected errors
            raise RuntimeError(f"Unexpected error: {str(e)}")


def sbase_sync_get(table_name: str, **kwargs):
    """
    Synchronous function to fetch data from Supabase REST API.

    Args:
        table_name (str): Name of the Supabase table
        **kwargs: Filtering conditions for the query

    Returns:
        dict: JSON response from Supabase

    Raises:
        ValueError: If the Supabase response contains an error code
        RuntimeError: For other unexpected errors during the API call
    """
    # Convert kwargs to Supabase REST filter
    rest_filter = sql_to_supabase_rest(**kwargs)

    # Use Client for sync HTTP requests
    with httpx.Client() as client:
        try:
            response = client.get(
                f"{pg_settings.rest_url}/rest/v1/{table_name}?{rest_filter}", 
                headers=HEADERS
            )
            
            # Check for error status codes
            if response.status_code >= 400:
                error_msg = response.json().get('error', 'Unknown error')
                raise ValueError(f"Supabase error: {error_msg}")
            
            return response.json()
            
        except httpx.HTTPError as e:
            raise RuntimeError(f"HTTP error occurred: {str(e)}")
        except Exception as e:
            raise RuntimeError(f"Unexpected error: {str(e)}")


# %% Insert data
async def sbase_insert(table_name: str, payload: dict):
    """
    Async function to insert data into Supabase REST API.

    Args:
        table_name (str): Name of the Supabase table
        payload (dict): Data fields to insert

    Returns:
        dict: JSON response from Supabase

    Raises:
        ValueError: If the Supabase response contains an error
        RuntimeError: For other unexpected errors during the API call
    """
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{pg_settings.rest_url}/rest/v1/{table_name}",
                headers=HEADERS,
                json=payload,
            )
            if response.status_code == 201:
                return True
            error_context = {
                'status_code': response.status_code,
                'error_response': response.text,
                'request_url': f"{pg_settings.rest_url}/rest/v1/{table_name}",
                'request_data': payload
            }
            raise RuntimeError(f"Supabase insert failed: {error_context}")
            
        except httpx.HTTPError as e:
            error_context = {
                'error_type': type(e).__name__,
                'error_message': str(e),
                'request_url': f"{pg_settings.rest_url}/rest/v1/{table_name}",
                'request_data': payload
            }
            raise RuntimeError(f"HTTP error during Supabase insert: {error_context}")
        except Exception as e:
            error_context = {
                'error_type': type(e).__name__,
                'error_message': str(e),
                'traceback': getattr(e, '__traceback__', None)
            }
            raise RuntimeError(f"Unexpected error during Supabase insert: {error_context}")


# %% Update data
async def sbase_update(update_fields: dict, table_name: str, **kwargs):
    """
    Async function to update data in Supabase REST API.

    Args:
        update_fields (dict): Dictionary of fields to update
        table_name (str): Name of the Supabase table
        **kwargs: Filtering conditions for the update query

    Returns:
        bool: True if update was successful

    Raises:
        ValueError: If the Supabase response contains an error
        RuntimeError: For other unexpected errors during the API call
    """
    # Convert kwargs to Supabase REST filter
    rest_filter = sql_to_supabase_rest(**kwargs)

    # Use AsyncClient for async HTTP requests
    async with httpx.AsyncClient() as client:
        try:
            response = await client.patch(
                f"{pg_settings.rest_url}/rest/v1/{table_name}?{rest_filter}", 
                headers=HEADERS,
                json=update_fields
            )
            
            # Check for successful update (No Content)
            if response.status_code == 204:
                return True
            
            # Parse response for potential error details
            try:
                response_data = response.json()
            except ValueError:
                response_data = {}
            
            # Raise error with status code and any available error details
            error_message = f"Update failed with status code {response.status_code}"
            if 'message' in response_data:
                error_message += f": {response_data['message']}"
            
            raise ValueError(error_message)
        
        except httpx.RequestError as e:
            # Handle network-related errors
            raise RuntimeError(f"Network error occurred: {str(e)}")
        except ValueError as ve:
            # Re-raise ValueError from Supabase response
            raise
        except Exception as e:
            # Catch any other unexpected errors
            raise RuntimeError(f"Unexpected error: {str(e)}")


def sbase_sync_update(update_fields: dict, table_name: str, **kwargs):
    """
    Synchronous function to update data in Supabase REST API.

    Args:
        update_fields (dict): Dictionary of fields to update
        table_name (str): Name of the Supabase table
        **kwargs: Filtering conditions for the update query

    Returns:
        bool: True if update was successful

    Raises:
        ValueError: If update_fields is empty or invalid
        HTTPError: If the Supabase API request fails
            - 400: Bad Request (invalid data format)
            - 401: Unauthorized (invalid API key)
            - 403: Forbidden (insufficient permissions)
            - 404: Not Found (table or record not found)
            - 409: Conflict (data integrity violation)
            - 5xx: Server-side errors
        RuntimeError: For other unexpected errors during the API call
    """
    if not update_fields:
        raise ValueError("update_fields cannot be empty")

    # Convert kwargs to Supabase REST filter
    rest_filter = sql_to_supabase_rest(**kwargs)

    # Use Client for sync HTTP requests
    with httpx.Client() as client:
        try:
            response = client.patch(
                f"{pg_settings.rest_url}/rest/v1/{table_name}?{rest_filter}",
                headers=HEADERS,
                json=update_fields
            )
            
            # Check for error status codes
            if response.status_code >= 400:
                error_data = response.json()
                error_msg = error_data.get('error', 'Unknown error')
                error_details = error_data.get('details', '')
                
                error_context = (
                    f"Status: {response.status_code}\n"
                    f"Table: {table_name}\n"
                    f"Error: {error_msg}\n"
                    f"Details: {error_details if error_details else 'No additional details'}"
                )
                
                if response.status_code == 400:
                    raise ValueError(f"Bad Request - Invalid data format:\n{error_context}")
                elif response.status_code == 401:
                    raise httpx.HTTPStatusError("Unauthorized - Invalid API key", request=response.request, response=response)
                elif response.status_code == 403:
                    raise httpx.HTTPStatusError("Forbidden - Insufficient permissions", request=response.request, response=response)
                elif response.status_code == 404:
                    raise httpx.HTTPStatusError("Not Found - Table or record doesn't exist", request=response.request, response=response)
                elif response.status_code == 409:
                    raise ValueError(f"Conflict - Data integrity violation:\n{error_context}")
                elif response.status_code >= 500:
                    raise httpx.HTTPStatusError(f"Server Error:\n{error_context}", request=response.request, response=response)
                else:
                    raise httpx.HTTPStatusError(f"Unexpected Error:\n{error_context}", request=response.request, response=response)
            
            return True
            
        except httpx.HTTPError as e:
            raise RuntimeError(f"HTTP error occurred: {str(e)}\nTable: {table_name}\nFilter: {rest_filter}")
        except ValueError as e:
            raise  # Re-raise ValueError with existing message
        except Exception as e:
            raise RuntimeError(f"Unexpected error while updating {table_name}: {str(e)}")


# %% Delete data
async def sbase_delete(table_name: str, **kwargs):
    """
    Async function to delete data from Supabase REST API.

    Args:
        table_name (str): Name of the Supabase table
        **kwargs: Key-value pairs for filtering records to delete

    Returns:
        bool: True if deletion was successful

    Raises:
        ValueError: If the Supabase response contains an error
        RuntimeError: For other unexpected errors during the API call
    """
    rest_filter = sql_to_supabase_rest(**kwargs)
    async with httpx.AsyncClient() as client:
        try:
            response = await client.delete(
                f"{pg_settings.rest_url}/rest/v1/{table_name}",
                headers=HEADERS,
                params=rest_filter
            )
            if response.status_code == 204:
                return True
            error_context = {
                'status_code': response.status_code,
                'error_response': response.text,
                'request_url': f"{pg_settings.rest_url}/rest/v1/{table_name}",
                'request_params': rest_filter
            }
            raise RuntimeError(f"Supabase delete failed: {error_context}")
            
        except httpx.HTTPError as e:
            error_context = {
                'error_type': type(e).__name__,
                'error_message': str(e),
                'request_url': f"{pg_settings.rest_url}/rest/v1/{table_name}",
                'request_params': rest_filter
            }
            raise RuntimeError(f"HTTP error during Supabase delete: {error_context}")
        except Exception as e:
            error_context = {
                'error_type': type(e).__name__,
                'error_message': str(e),
                'traceback': getattr(e, '__traceback__', None)
            }
            raise RuntimeError(f"Unexpected error during Supabase delete: {error_context}")

# %% SQL condition from KWargs
