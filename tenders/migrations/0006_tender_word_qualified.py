from django.db import migrations

# The typo-correction word list of 0004, rebuilt with its table schema-qualified. Postgres 17
# (Neon) creates and refreshes a materialized view with search_path "pg_catalog, pg_temp",
# where the query string ts_stat runs cannot see a bare "tender". 0004 now says
# "public.tender"; databases that ran it before (Postgres 16 dev and CI databases) get the
# same definition here, so a later upgrade to Postgres 17 cannot break the hourly refresh.
SEARCH_WORDS = """
    SELECT word, ndoc FROM ts_stat($$
        SELECT to_tsvector('simple'::regconfig, coalesce(title, '') || ' ' || coalesce(buyer_raw, '')
                           || ' ' || coalesce(location, '') || ' ' || coalesce(org_chain, ''))
        FROM public.tender
    $$)
    WHERE length(word) >= 3 AND word ~ '^[a-z]+$'
"""


class Migration(migrations.Migration):
    dependencies = [("tenders", "0005_tender_prebid_meeting")]

    operations = [
        migrations.RunSQL(
            "DROP MATERIALIZED VIEW IF EXISTS tender_word;"
            f"CREATE MATERIALIZED VIEW tender_word AS {SEARCH_WORDS};"
            # REFRESH ... CONCURRENTLY needs a unique index.
            "CREATE UNIQUE INDEX tender_word_word ON tender_word (word);"
            "CREATE INDEX tender_word_prefix ON tender_word (word text_pattern_ops);"
            "CREATE INDEX tender_word_trgm ON tender_word USING gist (word gist_trgm_ops);",
            migrations.RunSQL.noop,
        ),
    ]
