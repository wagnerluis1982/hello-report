from django import template
from django.utils.formats import number_format as django_number_format

register = template.Library()


@register.filter(is_safe=True)
def numberformat(value, decimal_pos=2):
    """
    Display a number grouping thousand separators and the specified number of decimal places (default to two).

    * {{ 18040.173|floatformat }} displays "18,040.17"
    * {{ 3000|floatformat }} displays "3,000.00"
    * {{ 34.2|floatformat }} displays "34.20"
    """
    return django_number_format(value, decimal_pos=decimal_pos, use_l10n=True, force_grouping=True)
