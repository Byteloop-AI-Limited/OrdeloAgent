# %% Setup Python Path
import os
import sys
from config import logger

# %%
import pickle
import duckdb
import pandas as pd
from pathlib import Path

root = "/home/basal/PycharmProjects/elai"

def read_pickle_file(file_path):
    """
    Reads a pickle file and returns its contents as a list.

    Args:
        file_path (str): The path to the pickle file.

    Returns:
        list: List of data from the pickle file
    """
    data_list = []
    try:
        with open(file_path, 'rb') as pickle_file:
            while True:
                try:
                    data = pickle.load(pickle_file)
                    data_list.append(data)
                except EOFError:
                    break
    except Exception as e:
        print(f"Error reading pickle file: {e}")
    return data_list

def create_duckdb_table(data_list):
    """
    Creates a DuckDB table from the list of JSON data.

    Args:
        data_list (list): List of JSON data

    Returns:
        duckdb.DuckDBPyConnection: DuckDB connection with loaded data
    """
    # Convert the list to a pandas DataFrame
    df = pd.DataFrame(data_list)
    
    # Create a DuckDB connection
    con = duckdb.connect(database=':memory:')
    
    # Register the DataFrame as a table
    con.register('iot_data', df)
    
    return con

# %%
def query_location_data(con, query_type=None):
    """
    Query the location data with specified filters.

    Args:
        con (duckdb.DuckDBPyConnection): DuckDB connection
        query_type (str, optional): Type of data to filter (_type value)

    Returns:
        dict: Query results as dictionary
    """
    query = """
    WITH parsedData0 AS (
        SELECT 
            JSON_EXTRACT(
                json_str, [
                    '_type', 
                    'batt',
                    'lon',
                    'acc',
                    'bs',
                    'cog',
                    'lat',
                    'rad',
                    't',
                    'p',
                    'c',
                    'C',
                    'b',
                    'r',
                    'u',
                    'v',
                    'tid',
                    'tst',
                    'vac',
                    'vel',
                    'poi',
                    'image',
                    'imagename',
                    'conn',
                    'w',
                    'o',
                    'm',
                    'tag',
                    'topic',
                    'inregions',
                    'inrids',
                    'SSID',
                    'BSSID',
                    'created_at',
                    '_id'
                ]) AS extracted_list,
            from iot_data 
        ),
    parsedData AS (
        SELECT
            EXTRACTED_LIST[1] ->> '$' AS _type,
            EXTRACTED_LIST[2] ->> '$' AS batt,
            EXTRACTED_LIST[3] ->> '$' AS lon,
            EXTRACTED_LIST[4] ->> '$' AS acc,
            EXTRACTED_LIST[5] ->> '$' AS bs,
            EXTRACTED_LIST[6] ->> '$' AS cog,
            EXTRACTED_LIST[7] ->> '$' AS lat,
            EXTRACTED_LIST[8] ->> '$' AS rad,
            EXTRACTED_LIST[9] ->> '$' AS t,
            EXTRACTED_LIST[10] ->> '$' AS p,
            EXTRACTED_LIST[11] ->> '$' AS c,
            EXTRACTED_LIST[12] ->> '$' AS C,
            EXTRACTED_LIST[13] ->> '$' AS b,
            EXTRACTED_LIST[14] ->> '$' AS r,
            EXTRACTED_LIST[15] ->> '$' AS u,
            EXTRACTED_LIST[16] ->> '$' AS v,
            EXTRACTED_LIST[17] ->> '$' AS tid,
            EXTRACTED_LIST[18] ->> '$' AS tst,
            EXTRACTED_LIST[19] ->> '$' AS vac,
            EXTRACTED_LIST[20] ->> '$' AS vel,
            EXTRACTED_LIST[21] ->> '$' AS poi,
            EXTRACTED_LIST[22] ->> '$' AS image,
            EXTRACTED_LIST[23] ->> '$' AS imagename,
            EXTRACTED_LIST[24] ->> '$' AS conn,
            EXTRACTED_LIST[25] ->> '$' AS w,
            EXTRACTED_LIST[26] ->> '$' AS o,
            EXTRACTED_LIST[27] ->> '$' AS m,
            EXTRACTED_LIST[28] ->> '$' AS tag,
            EXTRACTED_LIST[29] ->> '$' AS topic,
            EXTRACTED_LIST[30] ->> '$' AS inregions,
            EXTRACTED_LIST[31] ->> '$' AS inrids,
            EXTRACTED_LIST[32] ->> '$' AS SSID,
            EXTRACTED_LIST[33] ->> '$' AS BSSID,
            EXTRACTED_LIST[34] ->> '$' AS created_at,
            EXTRACTED_LIST[35] ->> '$' AS _id
        from parsedData0
    )
    """
    
    # Add type filter if specified
    if query_type:
        query += f"\nSELECT * FROM parsedData WHERE _type = '{query_type}' ORDER BY tst DESC"
    else:
        query += "\nSELECT * FROM parsedData ORDER BY tst DESC"
    
    return con.execute(query).df().to_dict('records')

# %%
pickle_file_path = f"{root}/data/live_location.pkl"

# Read pickle file
data_list = read_pickle_file(pickle_file_path)
data_list

# %% 
from utils_common.params import filter_dict
# filter_dict(data_list)

# from config import logger
import os 
os.environ.get('PYTHONPATH')
# %%
# Create DuckDB table
con = create_duckdb_table(data_list)

# Query data
results = query_location_data(con)
print(results)
