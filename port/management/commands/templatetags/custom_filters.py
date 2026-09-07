from django import template
register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Récupère la valeur d'un dictionnaire par sa clé, retourne 0 si absent."""
    val = dictionary.get(key, 0)
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0