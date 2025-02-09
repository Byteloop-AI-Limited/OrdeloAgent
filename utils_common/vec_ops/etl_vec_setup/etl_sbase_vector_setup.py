# %% Define embedding function
from openai import OpenAI
from config import pg_settings
import psycopg
from config import cat_conn

# %%
client = OpenAI()

def generate_embedding(text):
    response = client.embeddings.create(
        input=text,
        model='text-embedding-3-small'
    )
    return response.data[0].embedding


# %% setup connection

def insert_document(conn, id: str, content: str, metadata: str, embedding):
    with conn.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO documents (id, content, metadata, embedding)
            VALUES (%s, %s, %s, %s)
            """,
            (id, content, metadata, embedding)
        )

# conn.commit()

# %% prepare the data

_content_query = """
SELECT 
    id,
    CONCAT(title, ' - ', description) AS content,
    CAST(JSON_OBJECT(
        'item_type', LOWER(google_product_category), 
        'id', id
        ) AS TEXT) AS metadata,
    
FROM elai_cat
"""
rows = cat_conn.execute(_content_query).df().to_dict('records')

# %% Insert data
conn = psycopg.connect(pg_settings.db_uri)

# for row in rows:
    # embedding = generate_embedding(row['content'])
    # insert_document(conn, row['id'], row['content'], row['metadata'], generate_embedding(row['content']))
# %%
conn.commit()