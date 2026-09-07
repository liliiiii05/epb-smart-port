from django import template

register = template.Library()

@register.filter
def shift_label(shift_key):
    """Convertit une clé de shift (ex: 07h_13h) en label lisible (ex: 07h-13h)"""
    mapping = {
        '07h_13h': '07h-13h',
        '13h_19h': '13h-19h',
        '19h_01h': '19h-01h',
        '01h_07h': '01h-07h',
    }
    return mapping.get(shift_key, shift_key)