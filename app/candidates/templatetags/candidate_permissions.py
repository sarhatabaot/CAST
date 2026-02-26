from django import template
from ..constants import CAN_VIEW_CANDIDATES

register = template.Library()

@register.simple_tag
def can_view_candidates_permission():
    """Returns the can_view_candidates permission string."""
    return CAN_VIEW_CANDIDATES

@register.filter
def has_candidates_permission(user):
    """Check if user has the can_view_candidates permission."""
    return user.is_superuser or user.has_perm(CAN_VIEW_CANDIDATES)