"""
This is no longer required, as we have moved to supabase
"""
# %%
from langchain_postgres import PGVector
from langchain_postgres.vectorstores import PGVector
from langchain_openai import OpenAIEmbeddings
from config import pg_settings
from langchain_core.documents import Document
from config import g_client
import pandas as pd 
import duckdb as ddb
import json
from config import cat_con_settings, cat_conn
from config import pg_settings

# %%
_vec_store = pg_settings.vector_store

# _vec_store.delete_collection()

# %%
# elai_catalog_pdf.columns
dietary_requirements_sql = """
SELECT 
    key AS diet_code,
    value AS dietary_requirement 
FROM 
    (VALUES 
        ('C', 'Crustacean'),
        ('D', 'Dairy'),
        ('E', 'Eggs'),
        ('F', 'Fish'),
        ('G', 'Gluten present'),
        ('N', 'Nuts present'),
        ('V', 'Vegetarian'),
        ('VE', 'Vegan')
    ) AS food_categories(key, value)
"""
# ddb.execute(dietary_requirements_sql).df()

# %%
dietary_requirement_stmnt = """
CREATE OR REPLACE TABLE elai_dietary_requirements AS 
WITH DietMapping AS (
    SELECT 
        key AS diet_code,
        value AS dietary_requirement 
    FROM 
        (VALUES 
            ('C', 'Is Crustacean'),
            ('D', 'Contains Dairy'),
            ('E', 'Contains Eggs'),
            ('F', 'Contains Fish'),
            ('G', 'Gluten present'),
            ('N', 'Nuts present'),
            ('V', 'Is Vegetarian'),
            ('VE', 'Is Vegan')
        ) AS food_categories(key, value)
), elaiDiet AS (
    SELECT
        id,
        UNNEST(SPLIT(custom_label_0,' ')) AS diet_code
    FROM elai_cat 
    WHERE LENGTH(custom_label_0) !=0
), elaiDietWValues AS (
    SELECT 
    * 
    FROM elaiDiet INNER JOIN DietMapping
    ON elaiDiet.diet_code = DietMapping.diet_code
), elaiDietValueList AS (
    SELECT 
        id,
        LIST(dietary_requirement) AS dietary_requirement_list
    FROM elaiDietWValues
    GROUP BY 1
)
select 
    id, 
    array_to_string(dietary_requirement_list, ', ') AS dietary_requirement
from elaiDietValueList
"""
cat_conn.execute(dietary_requirement_stmnt).df()
# %%

formatted_rows = cat_conn.execute("""
WITH contentRaw AS (
    SELECT 
        EC.id, 
        DR.id as dr_id, 
        DR.dietary_requirement,
        CONCAT(
        'title:', title, 
        ', description: ', description, 
        ', item_category: ', google_product_category,
        ', price: ', price
        ) AS content_wo_dietary_requirement,
        JSON_OBJECT('item_type', google_product_category, 'id', EC.id) as metadata
    FROM elai_cat EC LEFT OUTER JOIN elai_dietary_requirements DR
    ON EC.id = DR.id
)
SELECT
    id,
    metadata,
    CASE 
        WHEN dr_id IS NULL THEN content_wo_dietary_requirement
        ELSE CONCAT(content_wo_dietary_requirement, ', dietary_requirement: ', dietary_requirement)
        END AS content
FROM
contentRaw
""").df().to_dict('records')

document_list = []
ids = []
for row in formatted_rows:
    _metadata = json.loads(row['metadata'])
    document_list.append(Document(page_content=row['content'], metadata=_metadata))
    ids.append(row['id'])
document_list

# %% Load embeds
# _vec_store.add_documents(documents=document_list,ids=ids)

# %% Local runs Commentout

# %% Similarity search
metadata_filter = {"id": {"$eq": "sweet_lassi"}}
results = _vec_store.similarity_search_with_score(
    query="mutton", 
    k=7,
    )
for doc, score in results:
    print(f"* [SIM={score:3f}] {doc.page_content} [{doc.metadata}]")


# # %%  -  AS retriever

# retriever = _vec_store.as_retriever(
#     search_type="mmr",
#     search_kwargs={"k": 30, "fetch_k": 7, "lambda_mult": 0.5}
# )
# retriever.invoke("mutton starters")


# deleete