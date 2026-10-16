SELECT 
    'CREATE TABLE ' || table_name || ' (' || 
    string_agg(column_name || ' ' || 
    CASE 
        WHEN is_nullable = 'NO' THEN 'NOT NULL ' 
        ELSE '' 
    END || 
    udt_name, ', ') || 
    ');' AS ddl
FROM 
    information_schema.columns
WHERE 
    table_name = 'delivery_option'  -- Replace with your actual table name
GROUP BY 
    table_name;