# %%

from utils_common.db_utils.sbase_rest_ops import sbase_call_function


# %%
response = await sbase_call_function(
    function_name='dispatch_complete_func',
    input_args={'p_dispatch_id': 16}
)
# %%
response