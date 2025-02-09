import subprocess
import duckdb as ddb
import functools
import time
from functools import lru_cache, wraps
from datetime import datetime, timedelta
import os
import regex as re
import json

# %% 
def get_project_root():
    try:
        # Run the git command to get the top-level Git directory
        git_root = subprocess.check_output(['git', 'rev-parse', '--show-toplevel'], stderr=subprocess.STDOUT)
        # Decode the output from bytes to string and strip any newlines
        git_root = git_root.decode().strip()
        return git_root
    except subprocess.CalledProcessError as e:
        # Handle the case where the current directory is not a git repository
        print("Error: Current directory is not a git repository.")
        return None
    except Exception as e:
        # Handle other possible exceptions
        print(f"An error occurred: {e}")
        return None


# %%

# %% filter any list[dict]
def filter_dict(dicts, select_cols=None, **filters):
    """
    Filters a list of dictionaries based on provided keyword arguments and selects/renames specific columns.

    :param dicts: List of dictionaries to filter.
    :param select_cols:
        - If None: All keys are included in the output dictionaries.
        - If list: Only those keys listed are included in the output.
        - If dict: Maps original key names to new key names in the output.
    :param filters: Keyword arguments representing filter conditions.
    :return: A new list of dictionaries that match all filter conditions with selected and/or renamed columns.
    Usage: 
    filter_dict(data, price=9.95)
    filter_dict(data, order_id='OEQT-50', quantity=[1,2])
    filter_dict(result, select_cols=['product_name', 'price', 'quantity'])
    """
    filtered = []
    for d in dicts:
        match = True
        for key, value in filters.items():
            if key.endswith('__gte'):
                field = key[:-5]
                dict_value = d.get(field)
                if dict_value is None or dict_value < value:
                    match = False
                    break
            elif key.endswith('__lte'):
                field = key[:-5]
                dict_value = d.get(field)
                if dict_value is None or dict_value > value:
                    match = False
                    break
            else:
                dict_value = d.get(key)
                if callable(value):
                    if not value(dict_value):
                        match = False
                        break
                elif isinstance(value, list):
                    if dict_value not in value:
                        match = False
                        break
                else:
                    if dict_value != value:
                        match = False
                        break

        if match:
            if select_cols is not None:
                # If select_cols is a dictionary, map old keys to new keys
                if isinstance(select_cols, dict):
                    selected = {new_key: d.get(original_key) for original_key, new_key in select_cols.items()}
                # If select_cols is a list, just select those keys without renaming
                elif isinstance(select_cols, list):
                    selected = {key: d.get(key) for key in select_cols}
                else:
                    raise ValueError("select_cols must be either a list, a dict, or None.")

                filtered.append(selected)
            else:
                # If no select_cols provided, include the entire dict
                filtered.append(d)
    return filtered

# %%
def get_sql_condition(**kwargs) -> str:
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

# %%
def is_json(s: str) -> bool:
    """Check if a string is a valid json or not"""
    try:
        json.loads(s)
        return True
    except json.JSONDecodeError:
        return False

# %% configure sys path
import sys
import os

def configure_pythonpath():
    """
    Configures the Python module search path by adding directories from the
    PYTHONPATH environment variable to sys.path. If PYTHONPATH is not set,
    it adds the current script directory as a fallback.
    """
    python_path = os.environ.get('PYTHONPATH')

    if python_path:
        # Add each directory in PYTHONPATH to sys.path
        for path in python_path.split(os.pathsep):
            if path and os.path.isdir(path):
                sys.path.insert(0, path)
    else:
        # Fallback: Add current script directory if PYTHONPATH is not set
        sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))