from django import template
register = template.Library()

@register.filter
def times(number):
    try:
        return range(int(number))
    except (ValueError, TypeError):
        return []


@register.filter
def is_spacer(value):
    return value == "spacer"


@register.filter
def get_item(dictionary, key):
    try:
        return dictionary.get(key)
    except Exception:
        return None
    

@register.filter
def contains(container, item):
    return item in container
