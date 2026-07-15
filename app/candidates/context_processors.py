from django.conf import settings


def cast_version(request):
    """Expose the running CAST version to all templates as ``cast_version``."""
    return {"cast_version": settings.CAST_VERSION}
