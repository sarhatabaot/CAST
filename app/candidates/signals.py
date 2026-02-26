from django.db.models.signals import post_migrate
from django.dispatch import receiver
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType


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