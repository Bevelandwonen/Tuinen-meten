from . import utils
# this file contains all the processors for different parcels
import pandas as pd
from typing import Optional, List, Dict
import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point
from shapely.geometry.polygon import Polygon
from shapely.geometry import LineString
from shapely.ops import split, snap, nearest_points
import math
from datatypes import DataBundle, HouseResult

def _find_parallel_edge(
    house: gpd.GeoDataFrame, 
    wall_line: LineString, 
    tolerance: int = 6
) -> List[LineString]:
    """Find a wall that is parallel to a given border line.
    
    Args:
        house: GeoDataFrame representing the house geometry
        border_line: LineString to compare against
        config: Configuration parameters for parallel detection
    
    Returns:
        List of LineStrings that are parallel to border_line
        
    Raises:
        ValueError: If inputs are invalid
    """
    if not isinstance(wall_line, LineString):
        raise ValueError("wall_line must be a LineString")
    #if not isinstance(house, Polygon):
       # raise ValueError("house must be a Polygon")
    
    # Get direction vector
    wall_coords = list(utils.truncate_coordinates(wall_line).coords)
    wall_vector = np.array([
        wall_coords[-1][0] - wall_coords[0][0],       
        wall_coords[-1][1] - wall_coords[0][1]])

    parallel_edges = []
    for polygon in house.geometry:
        if isinstance(polygon, Polygon):

            # Get exterior coordinates of the polygon
            exterior_coords = list(polygon.exterior.coords)
            
            # Iterate through the walls of the polygon
            for i in range(len(exterior_coords) - 1):
                wall = LineString([exterior_coords[i], exterior_coords[i + 1]])

                wall_coords = list(utils.truncate_coordinates(wall).coords)
                wall_vector = np.array([
                    wall_coords[-1][0] - wall_coords[0][0], 
                    wall_coords[-1][1] - wall_coords[0][1]])
                
                # Check if the direction vectors are parallel (cross product is zero)
                cross_product = abs(
                    abs(wall_vector[0] * wall_vector[1]) - 
                    abs(wall_vector[1] * wall_vector[0])
                )

                if cross_product < tolerance:
                    parallel_edges.append(wall)
    
    return parallel_edges

def _find_outer_wall(
    parallel_house_lines: List[LineString], 
    plot_border: List[LineString]
) -> Optional[LineString]:
    """
    Finds the line from parallel_house_lines that has the greatest distance to plot_border.
    
    Args:
        parallel_house_lines (List[Line]): A list of parallel lines representing house walls.
        plot_border (List[Line]): A list of lines representing the property border.
    
    Returns:
        Optional[Line]: The line with the greatest distance, or None if input is empty.
    """
    furthest_line = None
    max_distance = 0.0

    for line in parallel_house_lines:
        p1, p2 = nearest_points(plot_border, line)
        distance = math.hypot(p2.x - p1.x, p2.y - p1.y)
        
        if distance > max_distance:
            max_distance = distance
            furthest_line = line

    return furthest_line

def _get_inner_corner_plot(
    house: gpd.GeoDataFrame,
    border_line: LineString,
    plot: Polygon
) -> Optional[Polygon]:
    """Create a naive plot for an inner corner house by taking the shared wall and a parallel wall. 
    Then these are extended until they intersect the plot boundary. 
    The resulting lines are used to create a polygon."""
    
    try:
        # Find parallel wall
        parallel_lines = _find_parallel_edge(house, border_line)
        furthest_line = _find_outer_wall(parallel_lines, border_line)

        if not furthest_line:
            return None

        # Create second border
        wall_coords = list(furthest_line.coords)
        wall_line = LineString(wall_coords)
        second_border = _create_plot_border(wall_line, plot)[0]
        
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

def _create_plot_border(shared_walls: Dict, plot: Polygon) -> List:
    """Creates an extended border line from a shared wall with a neighbor.
    
    Args:
        shared_walls: LineString representing the shared wall with a neighbor
        plot: Polygon representing the complete plot boundary
    
    Returns:
        List[LineString]: List containing the extended border line that 
        intersects with the plot boundary
    """

    shared_walls = LineString(list(shared_walls.values())[0])

    extended_line = utils.extend_line_through_polygon(shared_walls, plot)
    intersection = extended_line.intersection(plot)

    return [LineString(list(intersection.coords))] if intersection else []
        
def _is_outer_corner_house(
    houses: gpd.GeoDataFrame, 
    house: gpd.GeoDataFrame
) -> bool:
    """Check if the house is an outer corner house.
    
    Args:
        shared_walls: Dictionary of shared walls with neighbors
        houses: GeoDataFrame containing all houses in the plot
        plot: Complete plot polygon
        house: GeoDataFrame containing single house geometry
    
    Returns:
        Polygon representing the corner house's portion of the plot
    """

    # Find if it's an outer corner by comparing centroid distances
    houses['centroid'] = houses.geometry.centroid
    distance_matrix = houses['centroid'].apply(lambda x: houses['centroid'].distance(x))
    distance_array = np.array(distance_matrix)
    
    # Get indices of houses furthest apart
    # If houses are furthest apart, they are likely to be on opposite corners of the plot.
    max_indices = np.unravel_index(np.argmax(distance_array), distance_array.shape)
    house_ids = list(houses["identificatie"])
    current_house_id = house["identificatie"].iloc[0] 
    
    # Check if current house is an outer corner
    is_outer_corner = (
        current_house_id == house_ids[max_indices[0]] or 
        current_house_id == house_ids[max_indices[1]]
    )
    
    # Create initial border line
    return is_outer_corner

def _get_corner_house_plot(
    border_line: List,
    house: gpd.GeoDataFrame, 
    plot: Polygon
) -> Polygon:
    """Split a plot into two parts using a border line and return the part containing most of the house.
    
    Args:
        border_line: LineString representing the shared wall/border
        house: GeoDataFrame containing a single house geometry
        plot: Polygon representing the complete plot
        
    Returns:
        Polygon representing the corner house's portion of the plot
        
    Raises:
        ValueError: If any required input is missing
        RuntimeError: If splitting fails or produces unexpected results
    """

    if not all([border_line is not None,
                house is not None and not house.empty,
                plot is not None]):
        raise ValueError("Missing required input geometries")

    TOLERANCE = 1e-2

    #Snap the border line to the plot boundary for precision
    snapped_line = snap(border_line, plot, TOLERANCE)

    cut_line = utils.extend_line_through_polygon(snapped_line, plot)

    # Perform the split using the extended LineString
    split_result = split(plot, cut_line)
    split_polygons = [geom for geom in split_result.geoms if isinstance(geom, Polygon)]

    if len(split_polygons) != 2:
        raise RuntimeError(f"Expected 2 polygons after split, got {len(split_polygons)}")

    # Find polygon with most house overlap
    house_geom = house["geometry"].iloc[0]
    overlaps = [poly.intersection(house_geom).area for poly in split_polygons]
    
    return split_polygons[0] if overlaps[0] > overlaps[1] else split_polygons[1]

def create_plot(
    shared_walls: Dict, 
    plot: Polygon
) -> Polygon:
    """
        Create a plot for a single non corner house. We use the shared walls with neightbours.
        We use these base lines and extend them until we intersect the plot_poly.

    Args:
        matches (dict): _description_
        plot_poly (Polygon): _description_

    Returns:
        tuple: _description_
    """

    plot_lines = []

    # Extend current lines.
    for _, values in shared_walls.items():
        start, end = values[0], values[1]

        direction = ((end.x - start.x), (end.y - start.y))
        length = (direction[0] ** 2 + direction[1] ** 2) **0.2
        unit_direction = (direction[0] / length, direction[1] / length)

        extension_length = 30
        new_start = Point(start.x - unit_direction[0] * extension_length, start.y - unit_direction[1] * extension_length)
        new_end = Point(end.x + unit_direction[0] * extension_length, end.y + unit_direction[1] * extension_length)

        new_plot_line = LineString([new_start, new_end])
        intersection = new_plot_line.intersection(plot)
        
        if intersection:
            # add points from the lines to new_plot
            plot_lines.append(list(intersection.coords))

    # Use the distance between the point to make sure we put them in the right order.
    # To create a polygon
    distance_a = sum((a - b) ** 2 for a, b in zip(plot_lines[0][0], plot_lines[1][0])) ** 0.5
    distance_b = sum((a - b) ** 2 for a, b in zip(plot_lines[0][1], plot_lines[1][0])) ** 0.5
    if distance_a > distance_b:
        combined_coord = plot_lines[0] + plot_lines[1]
    else:
        combined_coord = plot_lines[0] + plot_lines[1][::-1]

    if combined_coord[0] != combined_coord[-1]:
        # Make sure loop is closed
        combined_coord.append(combined_coord[0])

    new_house_plot = Polygon(combined_coord)
    return new_house_plot

def multiple_aligned(
    data: DataBundle,
    plot_poly: Polygon,
    gdf_bag_in_plot: gpd.GeoDataFrame,
    gdf_plot: gpd.GeoDataFrame,
    gdf_road_in_plot: gpd.GeoDataFrame
) -> List[Dict]:
    
    results = []
    errors = []

    for _, row in gdf_bag_in_plot.iterrows():
        neighbours = utils.find_borders(gdf_bag_in_plot, row)

        house = gdf_bag_in_plot[
            gdf_bag_in_plot["identificatie"] == row["identificatie"]
        ]

        neighbour_count = len(neighbours)

        if neighbour_count not in (1, 2): 
            # This is possible if the corporation doesnt own the neighbouring houses.
            #TODO: Fix this by using bag data from other houses aswell and checking if they have the same bag id.

            results.append(
                HouseResult(
                    pand_id=row["identificatie"],
                    storage_size=0,
                    garden_size=0,
                    classification="multiple_aligned_error_no_neighbours",
                )
            )
            continue

        if neighbour_count == 1:
            outer_corner = _is_outer_corner_house(gdf_bag_in_plot, house)
            border_line = _create_plot_border(neighbours, plot_poly)[0]

            if outer_corner:
                new_poly = _get_corner_house_plot(
                    border_line, 
                    house,
                    plot_poly
                )
            else:                    
                new_poly = _get_inner_corner_plot(
                    house, 
                    border_line, 
                    plot_poly
                )

        else:
            #not a corner house
            new_poly = create_plot(
                neighbours, 
                plot_poly
            )

        #TODO: test if this can be removed due to param gdf_road_in_plot already being passed in
        #gdf_road_in_plot = data.gdf_road[data.gdf_road.intersects(gdf_plot.unary_union)]
        storage, storage_size = utils.find_berging(
            new_poly, 
            data.gdf_pand
        )

        garden_size = utils.calc_areas(
            gdf_road_in_plot, 
            new_poly, 
            house, 
            storage_size,
        )

        utils.visualise_house_plot(
            gdf_plot, 
            new_poly, 
            gdf_bag_in_plot, 
            gdf_road_in_plot, 
            storage,
        )

        print(f"Tuin opp = {garden_size:.1f}m², Berging opp = {storage_size:.1f}m²")

        results.append(
            HouseResult(
                pand_id=row["identificatie"],
                storage_size=storage_size,
                garden_size=garden_size,
                classification="multiple_aligned",
            )
        )
        
    return results, errors

