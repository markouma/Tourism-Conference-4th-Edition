from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import redirect
from functools import wraps
from django.core.exceptions import PermissionDenied



def is_admin_or_scanner(user):
    return user.is_authenticated and (user.is_staff or user.groups.filter(name='Scanner').exists())

def admin_or_scanner_required(view_func=None, login_url='/scanner/login/'):
    actual_decorator = user_passes_test(
        is_admin_or_scanner,
        login_url=login_url
    )
    if view_func:
        return actual_decorator(view_func)
    return actual_decorator



def scanner_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('scanner_login')
        if not request.user.groups.filter(name='Scanner').exists():
            return redirect('scanner_login')
        return view_func(request, *args, **kwargs)
    return _wrapped_view



def user_in_group(user, group_name):
    return user.is_authenticated and user.groups.filter(name=group_name).exists()

def group_required(group_name):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            if not user_in_group(request.user, group_name):
                raise PermissionDenied()
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator
