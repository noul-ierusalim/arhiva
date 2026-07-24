-- ===========================================================================
-- extract_samples.sql — pull a few representative WordPress posts out of the
-- noulierusalim.ro database so the Phase-2 generator can be built against the
-- real target shape (posts + postmeta + taxonomy), not guesses.
--
-- HOW TO RUN (cPanel → phpMyAdmin):
--   1. Open phpMyAdmin, select the site's database on the left.
--   2. Click the "SQL" tab. Run each STEP below one at a time (paste, Go).
--   3. For STEPS 4a–4e, after the results appear, scroll down and click
--      "Export" (query results) → format "SQL" → Go. That gives you the
--      INSERT statements to save as a .sql file.
--
-- BEFORE RUNNING: this file assumes the default table prefix `wp_`. If STEP 1
-- shows a different prefix (e.g. wp_a1b2_), do Find & Replace `wp_` → your
-- prefix across this whole file first.
-- ===========================================================================


-- STEP 1 — Discover the table prefix ----------------------------------------
-- The part before "posts" is your prefix.
SHOW TABLES LIKE '%posts';


-- STEP 2 — Find the post IDs you want to export -----------------------------
-- Aim for 3 representative messages: the validated example, one with audio,
-- one with a theme link. Edit 'FRAGMENT' to a slug/title fragment you know.

-- 2a. The validated example (by slug or title)
SELECT ID, post_date, post_status, post_name, post_title
FROM wp_posts
WHERE post_type = 'post'
  AND (post_name LIKE '%FRAGMENT%' OR post_title LIKE '%FRAGMENT%')
ORDER BY post_date
LIMIT 20;

-- 2b. A post that carries an [audio ...] shortcode
SELECT ID, post_date, post_name
FROM wp_posts
WHERE post_type = 'post' AND post_content LIKE '%[audio%'
ORDER BY post_date DESC
LIMIT 10;

-- 2c. A post that carries a [legatura_la_teme] shortcode
SELECT ID, post_date, post_name
FROM wp_posts
WHERE post_type = 'post' AND post_content LIKE '%[legatura_la_teme%'
ORDER BY post_date DESC
LIMIT 10;


-- STEP 3 — Put your chosen IDs into the list below --------------------------
-- Replace 123,456,789 with the IDs from STEP 2, in EVERY query in STEP 4.


-- STEP 4 — Select the rows to export ----------------------------------------
-- Run each, then use phpMyAdmin's "Export" link under the results (format SQL).

-- 4a. The posts themselves
SELECT * FROM wp_posts
WHERE ID IN (123,456,789);

-- 4b. All their metadata (Divi builder flags, audio/theme meta, etc.)
SELECT * FROM wp_postmeta
WHERE post_id IN (123,456,789);

-- 4c. Their category/tag links
SELECT * FROM wp_term_relationships
WHERE object_id IN (123,456,789);

-- 4d. The taxonomy definitions (small tables — take them whole so the
--     year-category structure is fully visible)
SELECT * FROM wp_term_taxonomy;
SELECT * FROM wp_terms;


-- STEP 5 — Grab the table structures ----------------------------------------
-- Run each; use "Export" on the result, OR just copy the CREATE TABLE text.
-- (Alternatively: phpMyAdmin → select these 5 tables → Export → "Structure
--  only" is the easiest way to get all of them at once.)
SHOW CREATE TABLE wp_posts;
SHOW CREATE TABLE wp_postmeta;
SHOW CREATE TABLE wp_term_relationships;
SHOW CREATE TABLE wp_term_taxonomy;
SHOW CREATE TABLE wp_terms;
