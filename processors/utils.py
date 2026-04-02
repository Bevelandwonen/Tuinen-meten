from typing import Dict, Tuple, Optional
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Polygon
import matplotlib.pyplot as plt
import geopandas as gpd
import numpy as np
from datatypes import DataBundle
from shapely.geometry import Point
from shapely.geometry import box as BoundingBox

def _generate_lines(points: list) -> list:
    """Create lines between points"""
    lines = []

    for i in range(len(points) - 1):
        lines.append(LineString([points[i], points[i + 1]]))
    return lines

def truncate_coordinates(line: LineString) -> LineString:
    return LineString([(int(x * 10) / 10.0, int(y * 10) / 10.0) for x, y in line.coords])

def find_berging(
    house_perceel: Polygon, 
    buildings: gpd.GeoDataFrame
) -> Tuple[gpd.GeoDataFrame, float]:
    """Find storage buildings in perceel and calculate total area."""

    # Find buildings that overlap with perceel
    storage = buildings[
        (buildings.geometry.intersects(house_perceel)) & 
        (buildings.geometry.type == 'MultiPolygon')
    ].copy()
        
    if storage.empty:
        return gpd.GeoDataFrame(), 0.0
        
    # Calculate overlap areas
    storage['overlap'] = storage.geometry.apply(
        lambda x: house_perceel.intersection(x).area
    )
    
    # Get building with maximum overlap
    max_storage = storage.loc[storage['overlap'].idxmax()]
    return gpd.GeoDataFrame([max_storage]), float(max_storage['overlap'])

def check_perceel_type(
    df_perceel_eenheden: pd.DataFrame, 
    gdf_bag_temp: gpd.GeoDataFrame
) -> str:
    
    if df_perceel_eenheden.shape[0] == 1:
        return "single"
    #TODO: clean check_houses function. does it need the line as output
    elif check_houses_aligned(gdf_bag_temp)[0]:
        return "multiple_aligned"
    else:
        return "open"

def visualise_house_perceel(
    perceel: gpd.GeoDataFrame,
    house_perceel: gpd.GeoSeries,
    houses: gpd.GeoDataFrame,
    road: gpd.GeoDataFrame,
    storage: gpd.GeoDataFrame
) -> None:
    """Visualize the house, perceel, road and storage buildings on a single plot."""
    house_perceel = gpd.GeoDataFrame(geometry=[house_perceel])

    ax = perceel.plot(color='blue', edgecolor='black', figsize=(8, 8))
    # Move window to specific position (x=100, y=100 pixels from top-left)
    figManager = plt.get_current_fig_manager()
    figManager.window.wm_geometry("+900+100")  # Change these numbers to position the window
    
    house_perceel.plot(ax=ax, color="yellow")
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

def calc_areas(
    roads: gpd.GeoDataFrame, 
    perceel: Polygon, 
    house: gpd.GeoDataFrame, 
    storage_size: float
) -> float:
    """Calculate the garden size by subtracting roads, house and storage from perceel.
    
    Args:
        roads: GeoDataFrame containing road geometries
        perceel: Polygon representing the complete perceel
        house: GeoDataFrame containing house geometry
        storage_size: Size of storage buildings in the perceel
    
    Returns:
        float: Calculated garden size in square meters
        
    Raises:
        ValueError: If inputs are invalid or CRS mismatchn
    """

    perceel_gdf = gpd.GeoDataFrame(geometry=[perceel], crs=roads.crs)

    # Validate CRS match
    if roads.crs != perceel_gdf.crs:
        raise ValueError(f"CRS mismatch: roads={roads.crs}, perceel={perceel_gdf.crs}")

    roads_dissolved = roads.dissolve()
    intersection = roads_dissolved.intersection(perceel_gdf.union_all())
    road_area = intersection.area.sum()
    house_area = house.area.values[0]

    garden_size = perceel.area - (road_area + house_area + storage_size)
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


def perceel_borders(
    gdf: gpd.GeoDataFrame, 
    eenheid: gpd.GeoSeries
) -> Dict:
    
    """This function finds the amount of connected neighbours for a single house.
       It does this by checking if the lines of the house intersect with the lines of the neighbours.

       param:


       returns: dict: with the neighbours as keys and the lines as values
    
    """
    # The house we are checking
    perceel_points = eenheid["geometry"]

    # All house in perceel -> exclude the house we are checking
    gdf_neighbours = gdf[gdf["identificatie"] != eenheid["identificatie"]]
    neighbours_found = {}
    eenheid_walls = _generate_lines(list(perceel_points.exterior.coords))

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
