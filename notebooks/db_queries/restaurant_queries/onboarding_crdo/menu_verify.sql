-- crdo_menu verification after core/menus.sql + menu_seed.sql. READ-ONLY. Run each statement on its own.
-- Query against the table only once it exists (see 00: to_regclass).

-- 1. Expect 146 rows, 2 out of stock, 144 in stock.
SELECT count(*) AS items, count(*) FILTER (WHERE availability = 'out of stock') AS out_of_stock,
       count(*) FILTER (WHERE availability = 'in stock') AS in_stock
FROM public.crdo_menu;

-- 2. Expect 24 categories; per-category counts: Lunch Special 8, Chef Recommended Starters 5, Starters 6, Soup Bowl 5,
--    Any Timers 11, Chef Recommended Dosa 6, Special Dosa 5, Dosa Corner 13, Chaat Corner 7, Curries 13, Wok Special 5,
--    Uthappam 6, Tandoori Breads 6, Breads 4, Salad 1, Kids Starters 3, Kids Main 6, Snacks 4, Simply a Side 3,
--    Dessert 3, Hot Drinks 3, Lassi and Milkshakes 5, Fresh Fruit Juices 6, Soft Drinks 12.
SELECT category, count(*) FROM public.crdo_menu GROUP BY category ORDER BY min(id);

-- 3. Expect 0 rows: blank title/category, non-positive price, non-GBP currency, missing image, duplicate sku/id.
SELECT id, title FROM public.crdo_menu
WHERE coalesce(trim(title), '') = '' OR coalesce(trim(category), '') = ''
   OR price IS NULL OR price <= 0 OR currency <> 'GBP' OR coalesce(image_link, '') = '';
SELECT sku, count(*) FROM public.crdo_menu GROUP BY sku HAVING count(*) > 1;
SELECT id, count(*) FROM public.crdo_menu GROUP BY id HAVING count(*) > 1;

-- 4. Duplicate normalised titles (the price audit takes the minimum price): expect only 'mini idly' x2, both 6.99.
SELECT lower(trim(title)) AS title, count(*), min(price), max(price)
FROM public.crdo_menu GROUP BY lower(trim(title)) HAVING count(*) > 1;

-- 5. Addons: expect 18 items with addons, all objects; steps required/allow_multiple as booleans.
SELECT count(*) AS with_addons, count(*) FILTER (WHERE jsonb_typeof(addons) <> 'object') AS not_objects
FROM public.crdo_menu WHERE addons IS NOT NULL;
SELECT title, addons FROM public.crdo_menu WHERE title IN ('Masala Dosa', 'Telugu Thali');

-- 6. The two unavailable thalis: expect Telugu Thali and Madras Thali.
SELECT id, title, price FROM public.crdo_menu WHERE availability = 'out of stock' ORDER BY id;

-- 7. TEST3100 is not a menu row (same as strk_menu / crms_menu): expect 0.
SELECT count(*) FROM public.crdo_menu WHERE upper(title) = 'TEST3100';
