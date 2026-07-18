from uk_wsr_visualizer.quantities import quantity_label


def test_known_quantities_use_scientific_long_names():
    assert quantity_label("DBZH") == "Horizontal Reflectivity"
    assert quantity_label("VRADH") == "Horizontal Radial Velocity"
    assert quantity_label("RHOHV") == "Copolar Correlation Coefficient"
    assert quantity_label("CI") == "Clutter Index"


def test_unknown_quantity_is_rendered_readably():
    assert quantity_label("custom_field") == "Custom Field"
    assert quantity_label("") == "Unknown Variable"
