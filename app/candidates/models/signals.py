import os

from candidates.models.candidate import Candidate
from candidates.models.data_product import CandidateDataProduct
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.dispatch import receiver
from django.db.models.signals import post_delete, post_migrate


@receiver(post_delete, sender=CandidateDataProduct)
def delete_datafile(sender, instance, **kwargs):
    """
    Deletes the file associated with a CandidateDataProduct when the instance is deleted.
    """
    if instance.datafile and os.path.isfile(instance.datafile.path):
        try:
            os.remove(instance.datafile.path)
        except Exception as e:
            print(f"Error deleting file {instance.datafile.path}: {e}")


@receiver(post_delete, sender=Candidate)
def delete_candidate_data_products(sender, instance, **kwargs):
    """
    Deletes all data products associated with a Candidate when the Candidate is deleted.
    """
    data_products = CandidateDataProduct.objects.filter(candidate=instance)
    for data_product in data_products:
        data_product.delete()


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
