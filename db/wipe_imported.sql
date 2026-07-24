-- ===========================================================================
-- wipe_imported.sql — remove ONLY the archive posts imported from ro_all.wxr,
-- so the WXR can be re-imported cleanly (the WP importer skips existing posts,
-- it never updates them). Run this in phpMyAdmin BEFORE each re-import.
--
-- Targets posts whose slug is date-prefixed (YYYY-MM-DD-…), which is exactly
-- our generated set. The 54 pre-existing live posts have letter-first slugs
-- (cuvantul-…) and are LEFT UNTOUCHED.
--
-- Prefix note: written for the sandbox prefix `Kup_`. Find & Replace `Kup_`
-- if different. SANDBOX ONLY unless you really mean to wipe production.
-- ===========================================================================

START TRANSACTION;

-- 0) Preview what will be deleted (run first on its own if you want a dry run).
SELECT COUNT(*) AS posts_to_delete
FROM `Kup_posts`
WHERE post_type = 'post'
  AND post_name REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}-';

-- 1) Collect target ids: the date-prefixed posts + any revisions of them.
DROP TEMPORARY TABLE IF EXISTS _del;
CREATE TEMPORARY TABLE _del AS
SELECT p.ID
FROM `Kup_posts` p
WHERE (p.post_type = 'post'
       AND p.post_name REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}-')
   OR (p.post_type = 'revision'
       AND p.post_parent IN (
           SELECT ID FROM (
               SELECT ID FROM `Kup_posts`
               WHERE post_type = 'post'
                 AND post_name REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}-'
           ) parents));

-- 2) Delete their metadata, term links, then the posts themselves.
DELETE FROM `Kup_postmeta`           WHERE post_id   IN (SELECT ID FROM _del);
DELETE FROM `Kup_term_relationships` WHERE object_id IN (SELECT ID FROM _del);
DELETE FROM `Kup_posts`              WHERE ID        IN (SELECT ID FROM _del);

-- 3) Recompute the 'cuvantul' category count so the admin shows the right number.
UPDATE `Kup_term_taxonomy` tt
JOIN `Kup_terms` t ON t.term_id = tt.term_id
SET tt.count = (
    SELECT COUNT(*) FROM `Kup_term_relationships` r
    WHERE r.term_taxonomy_id = tt.term_taxonomy_id)
WHERE t.slug = 'cuvantul' AND tt.taxonomy = 'category';

DROP TEMPORARY TABLE IF EXISTS _del;

COMMIT;

-- 4) Verify (should be 0 after commit).
SELECT COUNT(*) AS remaining_date_prefixed_posts
FROM `Kup_posts`
WHERE post_type = 'post'
  AND post_name REGEXP '^[0-9]{4}-[0-9]{2}-[0-9]{2}-';
