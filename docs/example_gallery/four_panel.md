# Four-Panel Comparison

Use four panels to compare a controlled dimension while keeping other choices
explicit. This example compares two times and two elevations from Castor Bay on
18 September 2014.

## Suggested layout

| Panel | Time UTC | Variable | Elevation |
|---|---:|---|---:|
| 1 | 1535 | Horizontal Reflectivity (DBZH) | 0.50 degrees |
| 2 | 1540 | Horizontal Reflectivity (DBZH) | 0.50 degrees |
| 3 | 1535 | Horizontal Reflectivity (DBZH) | 0.95 degrees |
| 4 | 1540 | Horizontal Reflectivity (DBZH) | 0.95 degrees |

## Steps

1. Load the first Castor Bay selection from the [Quick Start](../user_guide/quickstart.md).
2. Select **4 Panel**.
3. Enable **Link View** so all panels share zoom and pan.
4. Disable **Link Time**, **Link Variable**, and **Link Elevation** while
   entering the table above.
5. Confirm that each panel label reports its own time and elevation.
6. Zoom once and verify that the four map views move together.
7. Enable **Link Time** only if you want **Next Time** and animation to advance
   every panel.

## Checks

- Changing panel 2's elevation must not reset panel 1.
- The elevation selector must show the value actually plotted.
- A panel without the requested linked time should display a clear message and
  retain the other panels.
- Pointer readout belongs to the panel clicked and reports that panel's
  variable and elevation.

## Comparing different variables

Variable-specific automatic limits are safer than one fixed reflectivity scale
when panels contain different moments. Each panel retains its own palette and
display limits. Leave colour-scale linking off for unlike variables; enable it
only when the same units and physical range make a direct colour comparison
valid.
