from celery import shared_task

from tenders import search


@shared_task(ignore_result=True)
def refresh_search_words() -> None:
    """Rebuild the word list typo correction uses (tender_word), so words from newly crawled
    tenders can be suggested. The search document itself is a generated column: nothing else
    needs syncing."""
    search.refresh_words()
