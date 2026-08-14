from django import template
from decimal import Decimal
import decimal

register = template.Library()

@register.filter
def currency_format(value):
    """
    Format currency with commas
    Usage: {{ amount|currency_format }}
    """
    try:
        if value is None:
            return "0"
        
        # Convert to Decimal for precision
        if isinstance(value, str):
            value = Decimal(value)
        elif isinstance(value, (int, float)):
            value = Decimal(str(value))
        
        # Format with commas
        return f"{value:,.0f}"
        
    except (ValueError, TypeError, decimal.InvalidOperation):
        return "0"



@register.filter 
def ksh_format(value):
    """
    Format with Ksh prefix and commas
    Usage: {{ amount|ksh_format }}
    """
    try:
        formatted = currency_format(value)
        return f"Ksh {formatted}"
    except:
        return "Ksh 0"