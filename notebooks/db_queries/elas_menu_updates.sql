-- table backedup in elas_menu_before_march


select * from elas_menu;



-- Thudakam items removed
-- DELETE FROM elas_menu WHERE title = 'Thattukada Meen Varuthathu';
-- DELETE FROM elas_menu WHERE title = 'Irachi Peralan';
-- DELETE FROM elas_menu WHERE title = 'Sheekh Kebab';
-- DELETE FROM elas_menu WHERE title = 'Gobi Manchurian';
-- DELETE FROM elas_menu WHERE title = 'Sea Bass';
-- DELETE FROM elas_menu WHERE title = 'Chicken Lollipop';
-- DELETE FROM elas_menu WHERE title = 'Kalan Milagu Varuval';

-- -- Main course items removed
-- DELETE FROM elas_menu WHERE title = 'Meen Mulakittathu Curry';
-- DELETE FROM elas_menu WHERE title = 'Chicken Makhani';
-- DELETE FROM elas_menu WHERE title = 'Karaikudi Lamb Curry on Bone';

-- -- Veg removed
-- DELETE FROM elas_menu WHERE title = 'Vendakkai Puli Kulambu';

-- -- Southern Favourites removed
-- DELETE FROM elas_menu WHERE title = 'Onion Dosa';
-- DELETE FROM elas_menu WHERE title = 'Chicken Kothu Parotta';
-- DELETE FROM elas_menu WHERE title = 'Lamb Kothu Parotta';
-- DELETE FROM elas_menu WHERE title = 'Egg Kothu Parotta';
-- DELETE FROM elas_menu WHERE title = 'Veg Kothu Parotta';

-- Name updates
-- UPDATE elas_menu SET title = 'Pakoda' WHERE title = 'Onion Pakoda';
-- UPDATE elas_menu SET title = 'Chicken Tikka' WHERE title = 'Tandoori Chicken Tikka';
-- UPDATE elas_menu SET title = 'Kerala Mango Curry (Prawn)', price = '16.95' WHERE title = 'Kerala Prawn Mango Curry';
-- UPDATE elas_menu SET title = 'Malabar Varutharacha Curry (Chicken)', price = '13.95' WHERE title = 'Kozhi Varutharacha Curry';
-- UPDATE elas_menu SET title = 'Nilgiri Green Curry (Chicken)', price = '13.95' WHERE title = 'Chicken Nilgiri Green Curry';
UPDATE elas_menu SET title = 'Chicken Biryani on Bone', price = '13.95' WHERE title = 'Chicken Biryani';

UPDATE elas_menu SET title = 'Chicken Biryani on Bone', price = '13.95' WHERE title = 'Chicken Biryani';

-- Price updates
-- UPDATE elas_menu SET price = '10.50' WHERE title = 'Chilli Chicken';
-- UPDATE elas_menu SET price = '13.50' WHERE title = 'Beef Ularthiyathu';
-- UPDATE elas_menu SET price = '14.50' WHERE title = 'Chicken Tikka';
-- UPDATE elas_menu SET price = '20.95' WHERE title = 'Kuttanadan Duck Curry';
-- UPDATE elas_menu SET price = '15.95' WHERE title = 'Kerala Beef Curry';

-- UPDATE elas_menu SET price = '14.95' WHERE title = 'Zafrani Paneer Tikka';
-- UPDATE elas_menu SET price = '4.5' WHERE title = 'Zafran Pilav Rice';
-- UPDATE elas_menu SET price = '4.5' WHERE title = 'Coconut Rice';
-- UPDATE elas_menu SET price = '4.75' WHERE title = 'Mushroom Rice';
-- UPDATE elas_menu SET price = '4.00' WHERE title = 'Lemon Rice';
-- UPDATE elas_menu SET price = '5.25' WHERE title = 'Keema Rice';
-- UPDATE elas_menu SET price = '14.95' WHERE title = 'Nilgiri Green Curry (Lamb)';


-- UPDATE elas_menu SET price = '11.95' WHERE title = 'Palak Paneer';
-- UPDATE elas_menu SET price = '10.50' WHERE title = 'Parippu Kadanjathu';
-- UPDATE elas_menu SET price = '11.95' WHERE title = 'Paneer Tikka Masala';
-- UPDATE elas_menu SET price = '10.50' WHERE title = 'Palak Aloo';
-- UPDATE elas_menu SET price = '10.50' WHERE title = 'Cauliflower and Green Peas Masala';
-- UPDATE elas_menu SET price = '10.50' WHERE title = 'Aloo Jeera';
-- UPDATE elas_menu SET price = '8.95' WHERE title = 'Chilli Paneer';

-- UPDATE elas_menu SET price = '4.50' WHERE title = 'Cheese Naan';
-- UPDATE elas_menu SET price = '4.75' WHERE title = 'Peshwari Naan';
-- UPDATE elas_menu SET price = '4.95' WHERE title = 'Keema Naan';
-- UPDATE elas_menu SET price = '3.75' WHERE title = 'Chilli Coriander Naan';

-- UPDATE elas_menu SET price = '14.95' WHERE title = 'Chicken Biryani on Bone';
-- UPDATE elas_menu SET price = '15.95' WHERE title = 'Lamb Biryani';
-- UPDATE elas_menu SET price = '13.95' WHERE title = 'Vegetable Biryani';


-- UPDATE elas_menu set price = '8.95' where title = 'Plain Dosa';
-- UPDATE elas_menu set price = '9.95' where title = 'Masala Dosa';
-- UPDATE elas_menu set price = '10.95' where title = 'Paneer Bhurji Dosa';
-- UPDATE elas_menu set price = '9.95' where title = 'Podi Dosa';
-- UPDATE elas_menu set price = '11.95' where title = 'Chicken Chukka Dosa';
-- UPDATE elas_menu set price = '10.95' where title = 'Egg Dosa';
-- UPDATE elas_menu set price = '7.95' where title = 'Plain Uttappam';
-- UPDATE elas_menu set price = '9.95' where title = 'Vegetable Uttappam';
-- UPDATE elas_menu set price = '9.50' where title = 'Onion Uttappam';
select * from elas_menu;


UPDATE elas_menu SET dietary_requirements = 'Gluten, Dairy' WHERE title IN ('Naan', 'Butter Naan', 'Cheese Naan', 'Roti', 'Fig and Coriander Naan', 'Keema Naan', 'Chilli Coriander Naan', 'Garlic Naan');

UPDATE elas_menu SET dietary_requirements = 'Nuts, Gluten, Dairy' WHERE title = 'Peshwari Naan';
UPDATE elas_menu SET dietary_requirements = 'Vegetarian, Vegan' WHERE title IN ('Plain Dosa', 'Masala Dosa');
UPDATE elas_menu SET dietary_requirements = 'Dairy, Vegetarian' WHERE title IN ('Paneer Bhurji Dosa', 'Podi Dosa');

UPDATE elas_menu SET dietary_requirements = 'Gluten' WHERE title = 'Chilli Chicken';

UPDATE elas_menu SET dietary_requirements = 'Dairy' WHERE title = 'Nilgiri Green Curry (Chicken)';
UPDATE elas_menu SET dietary_requirements = 'Dairy' WHERE title = 'Nilgiri Green Curry (Lamb)';

select max(id) from elas_menu;
select * from elas_menu where title='Soya Manchurian';
elas_menu
-- New Items
-- INSERT INTO elas_menu (id, created_at, category, title, description, price, dietary_requirements)
-- VALUES
-- -- THUDAKAM
-- (83, now(), 'Thudakam', 'Meen Porichathu', 'Fish marinaded with God''s Own Country Spices', 9.95, 'Fish'),
-- (84, now(), 'Thudakam', 'Spicy Kerala Prawn Roast', 'Prawn cooked with Keralan spices and coconut', 10.95, 'Crustacean'),
-- (85, now(), 'Thudakam', 'Chicken 65', 'Chicken marinated with spices and fried tossed with green chillie', 9.95, 'Dairy, Gluten'),
-- (86, now(), 'Thudakam', 'Lamb Chukka Varuval', 'A popular slow cooked lamb dish with aromatic herbs and spice', 10.95, NULL),
-- (87, now(), 'Thudakam', 'Soya Manchurian', 'Batter fried soya cooked with fresh ginger, garlic, chillies, coriander, rich flavour of soy', 8.95, 'Vegetarian, Vegan'),
-- (88, now(), 'Thudakam', 'Gobi 65', 'Cauliflower fried with chef''s special spices', 8.95, 'Gluten, Vegetarian, Vegan'),

-- -- MAIN COURSE (the items in your image are the specific variants)
-- (89, now(), 'Main Course', 'Kerala style Mango Curry (Fish)', 'Inspired by seafood cooks of the backwaters of Kerala, South India, prawns in a tongue-tickling raw mango, ginger and coconut sauce', 13.95, 'Fish'),
-- (90, now(), 'Main Course', 'Venison Rogan Josh', 'An aromatic, slow-cooked curried meat dish from Kashmiri style.', 21.95, NULL),
-- (91, now(), 'Main Course', 'Malabar Varutharacha Curry (Lamb)', 'Cooked in a rich flavour of raw spices containing coconut, black pepper, curry leaves and red chillies', 14.95, NULL),
-- (92, now(), 'Main Course', 'Malabar Varutharacha Curry (Prawn)', 'Cooked in a rich flavour of raw spices containing coconut, black pepper, curry leaves and red chillies', 16.95, 'Crustacean'),
-- (93, now(), 'Main Course', 'Nilgiri Green Curry (Prawn)', 'A traditional dish from Western Ghats Tamilnadu, India– lamb or chicken cooked with leaf spinach, onion tomatoes and spices, flavoured with fenugreek leaves', 16.95, 'Crustacean'),
-- (94, now(), 'Main Course', 'South Indian Style Korma (Chicken)', 'Rich sauce cooked with nuts and species finished with coconut, flavoured with fennel and garam masala', 13.95, 'Nuts'),
-- (95, now(), 'Main Course', 'South Indian Style Korma (Lamb)', 'Rich sauce cooked with nuts and species finished with coconut, flavoured with fennel and garam masala', 14.95, 'Nuts'),
-- (96, now(), 'Main Course', 'South Indian Style Korma (Prawn)', 'Rich sauce cooked with nuts and species finished with coconut, flavoured with fennel and garam masala', 16.95, 'Nuts, Crustacean'),
-- (97, now(), 'Main Course', 'Tikka Masala (Chicken)', 'In a rich nuts, tomato and butter sauce flavoured with fenugreek leaves', 13.95, 'Dairy, Nuts'),
-- (98, now(), 'Main Course', 'Tikka Masala (Lamb)', 'In a rich nuts, tomato and butter sauce flavoured with fenugreek leaves', 14.95, 'Dairy, Nuts'),
-- (99, now(), 'Main Course', 'Tikka Masala (Prawn)', 'In a rich nuts, tomato and butter sauce flavoured with fenugreek leaves', 16.95, 'Dairy, Nuts, Crustacean'),

-- -- TANDOORI
-- (100, now(), 'Tandoori', 'Spring Lamb Tikka', 'Blended with spices then finished in the tandoor oven', 16.95, 'Dairy'),

-- -- VEGETABLES/VEGAN
-- (101, now(), 'Vegetables/Vegan', 'Ennai Kathirikai Kulambu', 'Tangy spicy eggplant curry, coconut, sesame seeds', 10.50, 'Nuts, Vegetarian, Vegan'),
-- (102, now(), 'Vegetables/Vegan', 'Thoran', 'Our traditional Kerala dish of carrot and cabbage tempered with mustard and fresh coconut', 10.50, 'Vegetarian, Vegan'),

-- -- BIRYANI
-- (103, now(), 'Biryani', 'Chicken Tikka Biryani', 'Our biryani is created in the authentic Dum style for maximum flavour and tenderness enhanced by fragrant spices and garnish with nuts, accompanied by homemade raita', 15.50, NULL),

-- -- SOUTHERN FAVOURITES
-- (104, now(), 'Southern Favourites', 'Mysore Masala Dosa', 'Dosa is a crispy pancake lentil dish which is immensely popular in South India, made with urid and rice flour, it is usually served with aromatic sambar and chutney', 10.95, 'Vegetarian, Vegan'),
-- (105, now(), 'Southern Favourites', 'Ghee Roast', NULL, 10.95, 'Dairy, Vegetarian');


select * from elas_menu where availability is not null;

update elas_menu set availability='in stock' where availability is NULL;