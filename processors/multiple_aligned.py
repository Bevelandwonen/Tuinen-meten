from . import utils
# this file contains all the processors for different parcels
from xml.parsers.expat import errors
import pandas as pd
from typing import Optional, List, Dict
import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
from shapely.geometry import Point
from shapely.geometry.polygon import Polygon
from shapely.geometry import LineString
from shapely.ops import split, snap, nearest_points
import math
from datatypes import DataBundle

def _find_parallel_edge(
    house: gpd.GeoDataFrame, 
    border_line: LineString, 
    tolerance: int = 6
) -> List[LineString]:
    """Find house edges that are parallel to a given border line.
    
    Args:
        house: GeoDataFrame representing the house geometry
        border_line: LineString to compare against
        config: Configuration parameters for parallel detection
    
    Returns:
        List of LineStrings that are parallel to border_line
        
    Raises:
        ValueError: If inputs are invalid
    """
    if not isinstance(border_line, LineString):
        raise ValueError("border_line must be a LineString")
    #if not isinstance(house, Polygon):
       # raise ValueError("house must be a Polygon")
    
    # Get direction vector
    border_coords = list(utils.truncate_coordinates(border_line).coords)
    border_vector = np.array([
        border_coords[-1][0] - border_coords[0][0],       
        border_coords[-1][1] - border_coords[0][1]])

    parallel_edges = []
    for polygon in house.geometry:
        if isinstance(polygon, Polygon):

            # Get exterior coordinates of the polygon
            exterior_coords = list(polygon.exterior.coords)
            
            # Iterate through the edges of the polygon
            for i in range(len(exterior_coords) - 1):
                edge = LineString([exterior_coords[i], exterior_coords[i + 1]])

                edge_coords = list(utils.truncate_coordinates(edge).coords)
                edge_vector = np.array([
                    edge_coords[-1][0] - edge_coords[0][0], 
                    edge_coords[-1][1] - edge_coords[0][1]])
                
                # Check if the direction vectors are parallel (cross product is zero)
                cross_product = abs(
                    abs(border_vector[0] * edge_vector[1]) - 
                    abs(border_vector[1] * edge_vector[0])
                )

                if cross_product < tolerance:
                    parallel_edges.append(edge)
    
    return parallel_edges

def _find_furthest_wall(
    parallel_house_lines: List[LineString], 
    perceel_border: List[LineString]
) -> Optional[LineString]:
    """
    Finds the line from parallel_house_lines that has the greatest distance to perceel_border.
    
    Args:
        parallel_house_lines (List[Line]): A list of parallel lines representing house walls.
        perceel_border (List[Line]): A list of lines representing the property border.
    
    Returns:
        Optional[Line]: The line with the greatest distance, or None if input is empty.
    """
    furthest_line = None
    max_distance = 0.0

    for line in parallel_house_lines:
        p1, p2 = nearest_points(perceel_border, line)
        distance = math.hypot(p2.x - p1.x, p2.y - p1.y)
        
        if distance > max_distance:
            max_distance = distance
            furthest_line = line

    return furthest_line

def _handle_inner_corner(
    house: gpd.GeoDataFrame,
    border_line: LineString,
    perceel: Polygon
) -> Optional[Polygon]:
    """Handle inner corner house perceel creation."""
    try:
        # Find parallel wall
        parallel_lines = _find_parallel_edge(house, border_line)
        furthest_line = _find_furthest_wall(parallel_lines, border_line)

        if not furthest_line:
            return None

        # Create second border
        wall_coords = list(furthest_line.coords)
        matches = {"1": [Point(wall_coords[0]), Point(wall_coords[1])]}
        second_border = _create_perceel_border(matches, perceel)[0]

        # Create rectangle from both borders
        line1_coords = list(border_line.coords)
        line2_coords = list(second_border.coords)

        corners = [
            line1_coords[0],
            line1_coords[1],
            line2_coords[1],
            line2_coords[0]
        ]
        return Polygon(corners)
        
    except Exception as e:
        print(f"Error handling inner corner: {e}")
        return None

def _create_perceel_border(shared_walls: Dict, perceel: Polygon) -> List:
    """Creates an extended border line from a shared wall with a neighbor.
    
    Args:
        shared_walls: Dictionary containing one neighbor's shared wall points
        perceel: Polygon representing the complete perceel boundary
    
    Returns:
        List[LineString]: List containing the extended border line that 
        intersects with the perceel boundary
    """
    EXTENSION_LENGTH: float = 38.0

    try:
        # Get the wall points from the first (and only) match
        start, end = next(iter(shared_walls.values()))
        
        # Calculate normalized direction vector
        dx = end.x - start.x
        dy = end.y - start.y
        length = (dx ** 2 + dy ** 2) ** 0.5
        
        # Create extended line
        extended_line = LineString([
            (start.x - dx/length * EXTENSION_LENGTH, start.y - dy/length * EXTENSION_LENGTH),
            (end.x + dx/length * EXTENSION_LENGTH, end.y + dy/length * EXTENSION_LENGTH)
        ])
        
        # Get intersection with perceel boundary
        intersection = extended_line.intersection(perceel)
        return [LineString(list(intersection.coords))] if intersection else []
        
    except Exception as e:
        print(f"Error creating perceel border: {e}")
        return []

def _create_corner_house_perceel(
    shared_walls: Dict, 
    houses: gpd.GeoDataFrame, 
    perceel: Polygon, 
    house: gpd.GeoDataFrame
) -> Polygon:
    """Create a perceel for a corner house, handling both outer and inner corners.
    
    Args:
        shared_walls: Dictionary of shared walls with neighbors
        houses: GeoDataFrame containing all houses in the perceel
        perceel: Complete perceel polygon
        house: GeoDataFrame containing single house geometry
    
    Returns:
        Polygon representing the corner house's portion of the perceel
    """

    # Find if it's an outer corner by comparing centroid distances
    houses['centroid'] = houses.geometry.centroid
    distance_matrix = houses['centroid'].apply(lambda x: houses['centroid'].distance(x))
    distance_array = np.array(distance_matrix)
    
    # Get indices of houses furthest apart
    max_indices = np.unravel_index(np.argmax(distance_array), distance_array.shape)
    house_ids = list(houses["identificatie"])
    current_house_id = house["identificatie"].iloc[0] 
    
    # Check if current house is an outer corner
    is_outer_corner = (
        current_house_id == house_ids[max_indices[0]] or 
        current_house_id == house_ids[max_indices[1]]
    )
    
    # Create initial border line
    border_line = _create_perceel_border(shared_walls, perceel)[0]
    if is_outer_corner:
        # Use simple method
        return get_corner_house_perceel(border_line, house, perceel)
    else:
        # Handle inner corner using parallel walls
        return _handle_inner_corner(house, border_line, perceel)

def get_corner_house_perceel(
    border_line: List,
    house: gpd.GeoDataFrame, 
    perceel: Polygon
) -> Polygon:
    """Split a perceel into two parts using a border line and return the part containing most of the house.
    
    Args:
        border_line: LineString representing the shared wall/border
        house: GeoDataFrame containing a single house geometry
        perceel: Polygon representing the complete perceel
        
    Returns:
        Polygon representing the corner house's portion of the perceel
        
    Raises:
        ValueError: If any required input is missing
        RuntimeError: If splitting fails or produces unexpected results
    """

    if not all([border_line is not None,
                house is not None and not house.empty,
                perceel is not None]):
        raise ValueError("Missing required input geometries")

    # Snap the LineString to the Polygon boundary for precision
    TOLERANCE = 1e-2
    EXTENSION_FACTOR = 10.0  # Factor to extend line beyond perceel bounds

    snapped_line = snap(border_line, perceel, TOLERANCE)

    # Get line coordinates
    start, end = snapped_line.coords[0], snapped_line.coords[-1]

    # Calculate extension vectors
    dx = end[0] - start[0]
    dy = end[1] - start[1]
        
    # Create extended line
    extended_line = LineString([
        (start[0] - EXTENSION_FACTOR * dx, start[1] - EXTENSION_FACTOR * dy),
        (end[0] + EXTENSION_FACTOR * dx, end[1] + EXTENSION_FACTOR * dy)
    ])

    # Perform the split using the extended LineString
    split_result = split(perceel, extended_line)
    split_polygons = [geom for geom in split_result.geoms if isinstance(geom, Polygon)]

    if len(split_polygons) != 2:
        raise RuntimeError(f"Expected 2 polygons after split, got {len(split_polygons)}")

    # Find polygon with most house overlap
    house_geom = house["geometry"].iloc[0]
    overlaps = [poly.intersection(house_geom).area for poly in split_polygons]
    
    return split_polygons[0] if overlaps[0] > overlaps[1] else split_polygons[1]


def create_perceel(
    shared_walls: Dict, 
    perceel: Polygon
) -> Polygon:
    """
        Create a perceel for a single non corner house. We use the shared walls with neightbours.
        We use these base lines and extend them until we intersect the perceel_poly.

    Args:
        matches (dict): _description_
        perceel_poly (Polygon): _description_

    Returns:
        tuple: _description_
    """

    perceel_lines = []

    # Extend current lines.
    for _, values in shared_walls.items():
        start, end = values[0], values[1]

        direction = ((end.x - start.x), (end.y - start.y))
        length = (direction[0] ** 2 + direction[1] ** 2) **0.2
        unit_direction = (direction[0] / length, direction[1] / length)

        extension_length = 30
        new_start = Point(start.x - unit_direction[0] * extension_length, start.y - unit_direction[1] * extension_length)
        new_end = Point(end.x + unit_direction[0] * extension_length, end.y + unit_direction[1] * extension_length)

        new_perceel_line = LineString([new_start, new_end])
        intersection = new_perceel_line.intersection(perceel)
        
        if intersection:
            # add points from the lines to new_perceel
            perceel_lines.append(list(intersection.coords))

    # Use the distance between the point to make sure we put them in the right order.
    # To create a polygon
    distance_a = sum((a - b) ** 2 for a, b in zip(perceel_lines[0][0], perceel_lines[1][0])) ** 0.5
    distance_b = sum((a - b) ** 2 for a, b in zip(perceel_lines[0][1], perceel_lines[1][0])) ** 0.5
    if distance_a > distance_b:
        combined_coord = perceel_lines[0] + perceel_lines[1]
    else:
        combined_coord = perceel_lines[0] + perceel_lines[1][::-1]

    if combined_coord[0] != combined_coord[-1]:
        # Make sure loop is closed
        combined_coord.append(combined_coord[0])

    new_house_perceel = Polygon(combined_coord)
    return new_house_perceel

def _one_row_houses(
    houses: gpd.GeoDataFrame, 
    max_corner_houses: int = 2
) -> bool:
    """Check if houses are arranged in a single row by counting corner houses.
    
    A house is considered a corner house if it shares a wall with only one neighbor.
    For a valid single row arrangement, there should be exactly two corner houses.
    
    Args:
        houses: GeoDataFrame containing house geometries and identifications
        max_corner_houses: Maximum number of corner houses allowed (default: 2)
    
    Returns:
        bool: True if houses form a single row (exactly 2 corner houses),
              False otherwise
    """
    if houses.empty:
        return False
        
    # Count corner houses using vectorized operations
    neighbor_counts = pd.Series(dtype=int, index=houses.index)
    
    for idx, row in houses.iterrows():
        matches = utils.perceel_borders(houses, row)
        neighbor_counts[idx] = len(matches.keys())
    
    # Count houses with only one neighbor (corner houses)
    corner_house_count = (neighbor_counts <= 1).sum()
    
    # Validate row arrangement
    if corner_house_count != max_corner_houses:
        return False
        
    # Additional validation: all non-corner houses should have exactly 2 neighbors
    non_corner_houses = (neighbor_counts > 1)
    if not all(neighbor_counts[non_corner_houses] == 2):
        return False
    
    return True

def multiple_aligned(
    data: DataBundle,
    perceel_poly: Polygon,
    gdf_bag_temp: gpd.GeoDataFrame,
    gdf_perceel: gpd.GeoDataFrame,
    gdf_weg_temp: gpd.GeoDataFrame
) -> List[Dict]:
    
    results = []
    errors = []

    one_row = _one_row_houses(gdf_bag_temp)
    for _, row in gdf_bag_temp.iterrows():

        matches = utils.perceel_borders(gdf_bag_temp, row)
        house = gdf_bag_temp[gdf_bag_temp["identificatie"] == row["identificatie"]]
        try:
            if len(matches) == 1:
                new_poly = get_corner_house_perceel(_create_perceel_border(matches, perceel_poly)[0], house, perceel_poly) if one_row \
                    else _create_corner_house_perceel(matches, gdf_bag_temp, perceel_poly, house)
            elif len(matches) == 2:
                new_poly = utils.create_perceel(matches, perceel_poly)
            else:
                new_poly = None  # Ensure new_poly is always defined

            if new_poly is None:
                continue

           #TODO: check if this is correct GDF_PERCEEL???? SHouldnt it be perceel poly
           #MAYBE I dont have te recalc gdf_weg_temp every time
           # DUbbele shit 
            gdf_weg_temp = data.gdf_road[data.gdf_road.intersects(gdf_perceel.unary_union)]
            storage, storage_size = utils.find_berging(new_poly, data.gdf_bgt_pand)
            garden_size = utils.calc_areas(gdf_weg_temp, new_poly, house, storage_size)
            utils.visualise_house_perceel(gdf_perceel, new_poly, gdf_bag_temp, gdf_weg_temp, storage)

            print(f"Tuin opp = {garden_size:.1f}m², Berging opp = {storage_size:.1f}m²")

            results.append({
                "Pand Id": row["identificatie"],
                "storage": storage_size,
                "nieuw tuin opp": garden_size,
                "classificatie": "multiple_aligned"
            })

        except Exception as e:
            errors.append({
            "Pand Id": row["identificatie"],
            "error": str(e),
            # optionally add perceelnummer if available
        })
        
    return results, errors