"""Chunk.context: the document's title line, indexed and embedded with every chunk.

The generated search_vector is rebuilt to include it (weight C, below the heading's A and
the passage's B: it names the tender, it should not outrank the words of the passage).
Existing chunks get an empty context here; `manage.py copilot_reindex` fills it in and
recomputes their embeddings.
"""

from django.db import migrations, models

CHUNK_SEARCH_VECTOR = """
    setweight(to_tsvector('english'::regconfig, coalesce(heading, '')), 'A')
    || setweight(to_tsvector('english'::regconfig, coalesce(text, '')), 'B')
    || setweight(to_tsvector('english'::regconfig, coalesce(context, '')), 'C')
"""
OLD_SEARCH_VECTOR = """
    setweight(to_tsvector('english'::regconfig, coalesce(heading, '')), 'A')
    || setweight(to_tsvector('english'::regconfig, coalesce(text, '')), 'B')
"""


def _rebuild(expression: str) -> str:
    return (
        "DROP INDEX IF EXISTS copilot_chunk_search_vector;"
        "ALTER TABLE copilot_chunk DROP COLUMN IF EXISTS search_vector;"
        f"ALTER TABLE copilot_chunk ADD COLUMN search_vector tsvector "
        f"GENERATED ALWAYS AS ({expression}) STORED;"
        "CREATE INDEX copilot_chunk_search_vector ON copilot_chunk USING gin (search_vector);"
    )


class Migration(migrations.Migration):
    dependencies = [
        ("copilot", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="chunk",
            name="context",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.RunSQL(_rebuild(CHUNK_SEARCH_VECTOR), _rebuild(OLD_SEARCH_VECTOR)),
    ]
