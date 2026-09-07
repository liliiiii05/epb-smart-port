from django import template
from django.utils import timezone
from datetime import datetime, timedelta

register = template.Library()

@register.filter
def decimal_to_datetime(value):
    """Convertit une heure décimale (ex: 32.5) en datetime lisible."""
    if value is None:
        return ''
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    dt = today + timedelta(hours=value)
    return dt.strftime('%d/%m %H:%M')