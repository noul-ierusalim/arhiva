-- ===========================================================================
-- sdbx_wipe.sql — reset the archive on the SANDBOX: delete EVERY post in the
-- 'Cuvântul lui Dumnezeu' (slug: cuvantul) category, plus their metadata and
-- revisions, so the full-archive WXR can be imported into a clean slate.
--
-- Table prefix: `Kup_`.  DESTRUCTIVE — take a full DB backup first.
-- Sandbox only.
-- ===========================================================================

START TRANSACTION;

SET @tt := (SELECT tt.term_taxonomy_id
            FROM `Kup_term_taxonomy` tt
            JOIN `Kup_terms` t ON t.term_id = tt.term_id
            WHERE t.slug = 'cuvantul' AND tt.taxonomy = 'category'
            LIMIT 1);

-- Preview: how many posts are attached to the category (run first for a dry run).
SELECT COUNT(*) AS posts_in_category
FROM `Kup_term_relationships` WHERE term_taxonomy_id = @tt;

-- Target ids: every post in the category + any revisions of those posts.
DROP TEMPORARY TABLE IF EXISTS _del;
CREATE TEMPORARY TABLE _del AS
SELECT p.ID
FROM `Kup_posts` p
WHERE p.ID IN (SELECT object_id FROM `Kup_term_relationships` WHERE term_taxonomy_id = @tt)
   OR (p.post_type = 'revision'
       AND p.post_parent IN (
           SELECT object_id FROM `Kup_term_relationships` WHERE term_taxonomy_id = @tt));

DELETE FROM `Kup_postmeta`           WHERE post_id   IN (SELECT ID FROM _del);
DELETE FROM `Kup_term_relationships` WHERE object_id IN (SELECT ID FROM _del);
DELETE FROM `Kup_posts`              WHERE ID        IN (SELECT ID FROM _del);

UPDATE `Kup_term_taxonomy` SET count = 0 WHERE term_taxonomy_id = @tt;

DROP TEMPORARY TABLE IF EXISTS _del;
COMMIT;

-- Verify (should be 0).
SELECT COUNT(*) AS remaining_in_category
FROM `Kup_term_relationships` WHERE term_taxonomy_id = @tt;
