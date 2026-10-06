from django.contrib.postgres.operations import CreateExtension, TrigramExtension
from django.db import migrations

# The search document (tenders/search.py). Weights rank a title match above a buyer match:
#   A  title, stemmed (english: "roads" finds "road") and as written (simple: a partial word
#      such as "constructi" is a prefix of "construction" but not of its stem "construct");
#      the tender ID and reference number (simple: never stemmed)
#   C  buyer name
#   D  location and organisation chain
# STORED and GENERATED, so every write path (the loader's raw upsert, the admin, backfills)
# keeps it current without an index to sync. It is not a model field on purpose: ordinary
# Tender queries never fetch it.
SEARCH_VECTOR = """
    setweight(to_tsvector('english'::regconfig, coalesce(title, '')), 'A')
    || setweight(to_tsvector('simple'::regconfig, coalesce(title, '')), 'A')
    || setweight(to_tsvector('simple'::regconfig,
                             coalesce(source_tender_id, '') || ' ' || coalesce(ref_no, '')), 'A')
    || setweight(to_tsvector('english'::regconfig, coalesce(buyer_raw, '')), 'C')
    || setweight(to_tsvector('english'::regconfig,
                             coalesce(location, '') || ' ' || coalesce(org_chain, '')), 'D')
"""

# Every distinct word in the searchable text, for typo correction ("toliet" -> "toilet"): the
# pg_trgm technique of a word list searched by trigram distance, then Levenshtein. Letters
# only, 3+ characters. Refreshed by tenders.tasks.refresh_search_words.
SEARCH_WORDS = """
    SELECT word, ndoc FROM ts_stat($$
        SELECT to_tsvector('simple'::regconfig, coalesce(title, '') || ' ' || coalesce(buyer_raw, '')
                           || ' ' || coalesce(location, '') || ' ' || coalesce(org_chain, ''))
        FROM tender
    $$)
    WHERE length(word) >= 3 AND word ~ '^[a-z]+$'
"""


class Migration(migrations.Migration):
    """Postgres replaces Elasticsearch: full-text search, typo correction, ID lookups.

    Also enables pgvector for the Copilot's chunk embeddings (copilot migrations depend on
    this one)."""

    dependencies = [("tenders", "0003_tender_sector")]

    operations = [
        TrigramExtension(),
        CreateExtension("fuzzystrmatch"),  # levenshtein()
        CreateExtension("vector"),  # pgvector
        migrations.RunSQL(
            f"ALTER TABLE tender ADD COLUMN search_vector tsvector "
            f"GENERATED ALWAYS AS ({SEARCH_VECTOR}) STORED;",
            "ALTER TABLE tender DROP COLUMN IF EXISTS search_vector;",
        ),
        migrations.RunSQL(
            "CREATE INDEX tender_search_vector ON tender USING gin (search_vector);",
            "DROP INDEX IF EXISTS tender_search_vector;",
        ),
        # 0002 created it already; repeated so this migration states the whole search setup.
        migrations.RunSQL(
            "CREATE INDEX IF NOT EXISTS tender_title_trgm ON tender USING gin (title gin_trgm_ops);",
            migrations.RunSQL.noop,
        ),
        # Exact tender-ID / reference lookups are case-insensitive (search.exact_ids).
        migrations.RunSQL(
            "CREATE INDEX tender_upper_source_tender_id ON tender (upper(source_tender_id));"
            "CREATE INDEX tender_upper_ref_no ON tender (upper(ref_no));",
            "DROP INDEX IF EXISTS tender_upper_source_tender_id;"
            "DROP INDEX IF EXISTS tender_upper_ref_no;",
        ),
        migrations.RunSQL(
            f"CREATE MATERIALIZED VIEW tender_word AS {SEARCH_WORDS};"
            # REFRESH ... CONCURRENTLY needs a unique index.
            "CREATE UNIQUE INDEX tender_word_word ON tender_word (word);"
            "CREATE INDEX tender_word_prefix ON tender_word (word text_pattern_ops);"
            "CREATE INDEX tender_word_trgm ON tender_word USING gist (word gist_trgm_ops);",
            "DROP MATERIALIZED VIEW IF EXISTS tender_word;",
        ),
    ]
