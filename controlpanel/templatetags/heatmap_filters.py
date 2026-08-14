from django import template

register = template.Library()

@register.filter
def heatmap_color(visits, max_visits=100):
    try:
        v = min(float(visits), float(max_visits)) / float(max_visits)
    except (ValueError, TypeError):
        v = 0

    red = int(255 * v)
    green = int(255 * (1 - v))
    blue = 0

    return f'rgba({red}, {green}, {blue}, 0.7)'

@register.filter
def heatmap_color(visit_count, max_visits):
    if max_visits == 0:
        return '#d1e5f0'  # default light color if no visits
    ratio = visit_count / max_visits
    # Map ratio to blue scale from light to dark:
    # Light blue: #d1e5f0 (low) -> Dark blue: #0570b0 (high)
    from colorsys import hsv_to_rgb
    # Instead of HSV, let's just interpolate manually (better control)

    # Convert hex to RGB helper
    def hex_to_rgb(hex_color):
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2 ,4))

    # Convert RGB to hex helper
    def rgb_to_hex(rgb):
        return '#%02x%02x%02x' % rgb

    start_rgb = hex_to_rgb('d1e5f0')  # light blue
    end_rgb = hex_to_rgb('0570b0')    # dark blue

    interp_rgb = tuple(
        int(start + (end - start) * ratio)
        for start, end in zip(start_rgb, end_rgb)
    )

    return rgb_to_hex(interp_rgb)
