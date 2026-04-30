import math
from typing import Dict, Optional, Tuple

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.geometry import box as BoundingBox

def _generate_lines(points: list) -> list:
    """Create lines between points"""
    lines = []

    for i in range(len(points) - 1):
        lines.append(LineString([points[i], points[i + 1]]))
    return lines

def truncate_coordinates(line: LineString) -> LineString:
    return LineString([(int(x * 10) / 10.0, int(y * 10) / 10.0) for x, y in line.coords])

def extend_line_through_polygon(line: LineString, plot: Polygon) -> LineString:
    """Extend a line through a polygon, it always intersect the polygon twice."""
    start, end = line.coords[0], line.coords[-1]

    dx = end[0] - start[0]
    dy = end[1] - start[1]

    length = math.hypot(dx, dy)
    if length == 0:
        raise ValueError("Cannot extend a zero-length line")

    # Unit direction vector
    ux = dx / length
    uy = dy / length

    minx, miny, maxx, maxy = plot.bounds
    bbox_size = max(maxx - minx, maxy - miny)

    extension = bbox_size * 2

    return LineString([
        (start[0] - extension * ux, start[1] - extension * uy),
        (end[0] + extension * ux, end[1] + extension * uy),
    ])

def find_berging(
    house_plot: Polygon, 
    buildings: gpd.GeoDataFrame
) -> Tuple[gpd.GeoDataFrame, float]:
    """Find storage buildings in plot and calculate total area."""

    # Find buildings that overlap with plot
    storage = buildings[
        (buildings.geometry.intersects(house_plot)) & 
        (buildings.geometry.type == 'MultiPolygon')
    ].copy()
        
    if storage.empty:
        return gpd.GeoDataFrame(), 0.0

    storage['overlap'] = storage.geometry.apply(
        lambda x: house_plot.intersection(x).area
    )
    
    # Get building with maximum overlap
    max_storage = storage.loc[storage['overlap'].idxmax()]
    return gpd.GeoDataFrame([max_storage]), float(max_storage['overlap'])

def check_plot_type(
    df_plot_eenheden: pd.DataFrame, 
    gdf_bag_temp: gpd.GeoDataFrame
) -> str:
    
    if df_plot_eenheden.shape[0] == 1:
        return "single"
    #TODO: clean check_houses function. does it need the line as output
    elif check_houses_aligned(gdf_bag_temp)[0]:
        return "multiple_aligned"
    else:
        return "open"

def visualise_house_plot(
    plot: gpd.GeoDataFrame,
    house_plot: gpd.GeoSeries,
    houses: gpd.GeoDataFrame,
    road: gpd.GeoDataFrame,
    storage: gpd.GeoDataFrame
) -> None:
    """Visualize the house, plot, road and storage buildings on a single plot."""
    house_plot = gpd.GeoDataFrame(geometry=[house_plot])
    #print full linestring house plot
    ax = plot.plot(color='blue', edgecolor='black', figsize=(8, 8))
    # Move window to specific position (x=100, y=100 pixels from top-left)
    figManager = plt.get_current_fig_manager()
    figManager.window.wm_geometry("+900+100")  # Change these numbers to position the window
    
    house_plot.plot(ax=ax, color="yellow")
    houses.plot(ax=ax, color='red', edgecolor='black')
    road.plot(ax=ax, color="green")

    # Only plot storage if it exists and has valid geometry
    if not storage.empty and 'geometry' in storage.columns:
        storage = storage.set_geometry('geometry')
        storage.plot(ax=ax, color="pink")

    # Hide axis labels and ticks
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_xlabel('')
    ax.set_ylabel('')

    def on_key(event):
        if event.key == 'a':
            plt.close()

    # Connect the key press event to the callback function
    fig = ax.get_figure()
    fig.canvas.mpl_connect('key_press_event', on_key)

    plt.show()

    return None

try:
    from shapely.validation import make_valid
except Exception:
    make_valid = None

def _fix_geom(geom):
    """Make geometry valid enough for overlay operations."""
    if geom is None or geom.is_empty:
        return geom
    if geom.is_valid:
        return geom
    if make_valid is not None:
        return make_valid(geom)
    return geom.buffer(0)  # fallback

def calc_areas(
    roads: gpd.GeoDataFrame | None,
    plot: Polygon,
    house: gpd.GeoDataFrame,
    storage_size: float
) -> float:
    """Calculate the garden size by subtracting roads, house and storage from plot."""

    if plot is None:
        raise ValueError("plot is None")

    if house is None or house.empty:
        raise ValueError("house is empty/None")
    if house.crs is None:
        raise ValueError("house.crs is None")

    # If roads are provided, they must have a CRS. If roads is empty/None, that's OK.
    if roads is not None and not roads.empty and roads.crs is None:
        raise ValueError("roads.crs is None")

    plot_geom = _fix_geom(plot)
    plot_area = float(plot_geom.area)

    if not isinstance(plot_geom, (Polygon, MultiPolygon)):
        raise ValueError(
            f"plot_geom must be Polygon or MultiPolygon, got {type(plot_geom)}"
        )

    # ----------------------
    # Roads area (optional)
    # ----------------------
    road_area = 0.0
    if roads is not None and not roads.empty:
        roads_fixed = roads.copy()

        # Fix invalid road geometries
        bad = ~roads_fixed.geometry.is_valid
        if bad.any():
            roads_fixed.loc[bad, "geometry"] = roads_fixed.loc[bad, "geometry"].apply(_fix_geom)

        # drop empties / Nones
        roads_fixed = roads_fixed[roads_fixed.geometry.notna() & ~roads_fixed.geometry.is_empty]

        if not roads_fixed.empty:
            # Clip to plot
            try:
                roads_in_plot = gpd.clip(roads_fixed, plot_geom)
            except Exception:
                # fallback repair on plot (in case of topology issues)
                plot_geom2 = _fix_geom(plot_geom)
                print(type(plot_geom), type(plot_geom2))
                roads_in_plot = gpd.clip(roads_fixed, plot_geom2)

            road_area = float(roads_in_plot.area.sum())

    # ----------------------
    # House area
    # ----------------------
    house_geom = _fix_geom(house.geometry.iloc[0])
    house_area = float(house_geom.intersection(plot_geom).area)

    garden_area = plot_area - road_area - house_area - float(storage_size)
    return max(0.0, garden_area)

def calc_areas2(
    roads: gpd.GeoDataFrame, 
    plot: Polygon, 
    house: gpd.GeoDataFrame, 
    storage_size: float
) -> float:
    """Calculate the garden size by subtracting roads, house and storage from plot.
    
    Args:
        roads: GeoDataFrame containing road geometries
        plot: Polygon representing the complete plot
        house: GeoDataFrame containing house geometry
        storage_size: Size of storage buildings in the plot
    
    Returns:
        float: Calculated garden size in square meters
        
    Raises:
        ValueError: If inputs are invalid or CRS mismatchn
    """

    plot_gdf = gpd.GeoDataFrame(geometry=[plot], crs=roads.crs)

    # Validate CRS match
    if roads.crs != plot_gdf.crs:
        raise ValueError(f"CRS mismatch: roads={roads.crs}, plot={plot_gdf.crs}")

    roads_dissolved = roads.dissolve()
    intersection = roads_dissolved.intersection(plot_gdf.union_all())
    road_area = intersection.area.sum()
    house_area = house.area.values[0]

    garden_size = plot.area - (road_area + house_area + storage_size)
    return garden_size

def check_houses_aligned(
    gdf: gpd.GeoDataFrame, 
    line_length: int = 300
) -> Tuple[bool, Optional[LineString]]:
    """Check if all houses are in one line. Draw a straight line from a house. 
       Extend the line and check if it intersects all houses.

    Args:
        gdf (_type_): _description_

    Returns:
        _type_: _description_
    """

    # Extract the coordinates of the middle point of the house geometries
    p1 = [geom.centroid.coords[0] for geom in gdf.geometry][0]
    
    # Check for each point and angle
    for angle in np.linspace(0, 2 * np.pi, 360):
        extended_line = LineString([
                (p1[0] - np.cos(angle) * line_length, p1[1] - np.sin(angle) * line_length),
                (p1[0] + np.cos(angle) * line_length, p1[1] + np.sin(angle) * line_length)
            ])

        if all(extended_line.intersects(house) for house in gdf.geometry):
            return True, extended_line
    
    return False, None


def find_borders(
    gdf: gpd.GeoDataFrame, 
    eenheid: gpd.GeoSeries
) -> Dict:
    
    """This function finds the amount of connected neighbours for a single house.
       It does this by checking if the lines of the house intersect with the lines of the neighbours.

       returns: dict: with the neighbours as keys and the lines as values
    
    """
    # The house we are checking
    plot_points = eenheid["geometry"]

    # All house in plot -> exclude the house we are checking
    gdf_neighbours = gdf[gdf["identificatie"] != eenheid["identificatie"]]
    neighbours_found = {}
    eenheid_walls = _generate_lines(list(plot_points.exterior.coords))

    # For every wall of the house
    for wall in eenheid_walls:
        
        # For every neighbours house
        # Check if walls overlap with the main eenheid.
        for _, neighbour in gdf_neighbours.iterrows():
            # Generate all possible lines from the polygon points
            eenheid_neighbour = neighbour["identificatie"]
            neighbour_polygon = neighbour['geometry']
            neighbour_walls = _generate_lines(list(neighbour_polygon.exterior.coords))

            # Check every wall
            for neighbour_wall in neighbour_walls:

                truncated_wall = truncate_coordinates(wall)
                truncated_neighbour_walls = truncate_coordinates(neighbour_wall)

                if truncated_wall.intersects(truncated_neighbour_walls):
                    buf_truncated_wall = truncated_wall.buffer(0.0111)
                    buf_truncated_neighbour_wall = truncated_neighbour_walls.buffer(0.0111)
                    overlap = buf_truncated_wall.intersection(buf_truncated_neighbour_wall).length

                    if overlap >= 2.0:
                        if eenheid_neighbour in neighbours_found:
                            continue
                        else:
                            neighbours_found[eenheid_neighbour] = [Point(neighbour_wall.coords[0]), Point(neighbour_wall.coords[1])]
    return neighbours_found
