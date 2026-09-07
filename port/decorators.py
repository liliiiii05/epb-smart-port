from django.contrib.auth.decorators import user_passes_test
from django.core.exceptions import PermissionDenied

def group_required(*group_names):
    def in_groups(user):
        if user.is_superuser:
            return True
        if user.groups.filter(name__in=group_names).exists():
            return True
        return False
    return user_passes_test(in_groups, login_url='/login/')