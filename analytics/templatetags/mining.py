from django import template
from django.contrib.humanize.templatetags.humanize import intcomma

register = template.Library()


@register.filter
def mining_ratio(value):
    return "—" if value is None else intcomma(f"{value:.2f}")
