from django.conf import settings
from django.db import models
from pgvector.django import HnswIndex, VectorField

# multilingual-e5-small; a different EMBEDDING_MODEL must have the same dimension (or a new
# migration). The "fake" test embedder produces this many dimensions too.
EMBEDDING_DIM = 384


def upload_path(doc: "Document", filename: str) -> str:
    """MEDIA_ROOT/copilot/<org>/<hash prefix>-<name>: per-organisation folders keep deletes
    and backups simple, and the hash prefix keeps two uploads named NIT.pdf apart."""
    return f"copilot/{doc.organization_id}/{doc.sha256[:12]}-{filename}"


class Document(models.Model):
    """One uploaded tender PDF, owned by an organisation. Text, chunks and embeddings are
    produced by copilot.tasks.process_document."""

    class Status(models.TextChoices):
        PROCESSING = "processing"
        READY = "ready"
        FAILED = "failed"

    organization = models.ForeignKey(
        "workspaces.Organization", on_delete=models.CASCADE, related_name="documents"
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    tender = models.ForeignKey(
        "tenders.Tender",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="copilot_documents",
    )
    filename = models.CharField(max_length=255)
    file = models.FileField(upload_to=upload_path, max_length=500)
    sha256 = models.CharField(max_length=64)
    pages = models.PositiveIntegerField(default=0)
    ocr_pages = models.PositiveIntegerField(default=0)
    bytes = models.BigIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PROCESSING)
    error = models.TextField(blank=True, default="")
    # Cleaned text of every page (after OCR), so the Bid Brief can be recomputed with newer
    # extractors without re-reading or re-OCRing the PDF. Not exposed by the API.
    page_texts = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # The same file uploaded twice by one organisation is one document.
            models.UniqueConstraint(fields=["organization", "sha256"], name="copilot_doc_org_sha"),
        ]
        indexes = [models.Index(fields=["organization", "tender"], name="copilot_doc_org_tender")]
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.filename


class Chunk(models.Model):
    """A page-tagged passage of a document. The full-text column `search_vector` (STORED,
    GENERATED, GIN-indexed) is created by the migration and is not a model field, like
    tender.search_vector: ordinary queries never fetch it."""

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="chunks")
    ord = models.PositiveIntegerField()
    page_from = models.PositiveIntegerField()
    page_to = models.PositiveIntegerField()
    heading = models.TextField(blank=True, default="")
    # What the document is about (tender title, ID, name of work: chunking.document_context),
    # indexed and embedded with the chunk so a question naming the work finds it among other
    # tenders' documents. Never quoted or shown; `text` alone is the citable passage.
    context = models.TextField(blank=True, default="")
    text = models.TextField()
    tokens = models.PositiveIntegerField(default=0)
    embedding = VectorField(dimensions=EMBEDDING_DIM, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["document", "ord"], name="copilot_chunk_doc_ord"),
        ]
        indexes = [
            # Cosine distance: e5 vectors are normalised.
            HnswIndex(
                name="copilot_chunk_embedding_hnsw",
                fields=["embedding"],
                m=16,
                ef_construction=64,
                opclasses=["vector_cosine_ops"],
            ),
        ]
        ordering = ["document", "ord"]

    def __str__(self):
        return f"{self.document_id}#{self.ord} p.{self.page_from}"
