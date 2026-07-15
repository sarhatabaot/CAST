import logging

from candidates.models.data_product import CandidateDataProduct
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.dispatch import receiver
from django.db.backends.signals import connection_created
from django.db.models.signals import post_delete, post_migrate

logger = logging.getLogger(__name__)


@receiver(connection_created)
def set_sqlite_pragmas(sender, connection, **kwargs):
    """
    Tune SQLite connections for concurrent read/write performance.

    WAL lets readers and the writer proceed concurrently (no "database is locked"
    when the daily ingest overlaps web traffic); the rest trade a little durability
    headroom for speed and give each connection a larger cache. No-op on other
    backends (e.g. if switched back to Postgres).
    """
    if connection.vendor != "sqlite":
        return
    with connection.cursor() as cursor:
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=20000;")
        cursor.execute("PRAGMA cache_size=-64000;")     # ~64 MB page cache
        cursor.execute("PRAGMA mmap_size=268435456;")   # 256 MB memory-mapped I/O
        cursor.execute("PRAGMA temp_store=MEMORY;")


@receiver(post_delete, sender=CandidateDataProduct)
def delete_datafile(sender, instance, **kwargs):
    """
    Delete the file backing a CandidateDataProduct when its row is removed.

    This is the single source of truth for file cleanup: it fires on direct
    deletes, queryset deletes, and cascade deletes (when a Candidate is removed,
    its data products are CASCADE-deleted and each emits this signal). Uses the
    storage API so it works regardless of the storage backend.
    """
    if instance.datafile:
        try:
            instance.datafile.delete(save=False)
        except Exception as e:
            logger.warning(f"Error deleting file for data product {instance.pk}: {e}")


@receiver(post_migrate)
def create_candidates_permissions(sender, **kwargs):
    """
    Create custom permissions for the candidates app.
    This signal runs after migrations to ensure the permission exists.
    """
    if sender.name == 'candidates':
        content_type = ContentType.objects.get_for_model(Permission)

        # Create the can_view_candidates permission
        Permission.objects.get_or_create(
            codename='can_view_candidates',
            name='Can view candidates',
            content_type=content_type,
        )
