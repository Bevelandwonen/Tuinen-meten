import math
from typing import Dict, List, Optional, Iterable

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, Point, Polygon, MultiPolygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import split, snap, nearest_points

from . import utils
from datatypes import DataBundle, HouseResult
#TODO: use this import format in all files

def _find_parallel_edge(
    house: gpd.GeoDataFrame,
    wall_line: LineString,
    angle_tolerance_degrees: float = 5.0,
    min_segment_length: float = 0.25,
) -> List[LineString]:
    """
    Given a single house geometry, return all exterior wall segments that are
    approximately parallel to `wall_line`.

    Parallelism check:
      For unit direction vectors u and v, |cross(u, v)| = |sin(theta)|.
      If sin(theta) <= sin(angle_tolerance), we consider them parallel.

    Args:
        house: GeoDataFrame with (typically) one row containing Polygon/MultiPolygon geometry.
        wall_line: Reference LineString to compare against.
        angle_tolerance_degrees: Maximum angular deviation to still count as parallel.
                                 Typical values: 2–10 degrees.
        min_segment_length: Ignore candidate wall segments shorter than this length.

    Returns:
        List[LineString]: wall segments from the house exterior that are parallel to wall_line.

    Raises:
        ValueError: For invalid inputs (non-LineString wall_line, missing geometry, zero-length line).
    """
    if not isinstance(wall_line, LineString):
        raise ValueError("wall_line must be a LineString")
    if wall_line.is_empty:
        raise ValueError("wall_line must not be empty")

    if house is None or house.empty:
        raise ValueError("house must not be empty")
    if "geometry" not in house:
        raise ValueError("house must contain a geometry column")

    ref_line = utils.truncate_coordinates(wall_line)
    ref_coords = list(ref_line.coords)
    if len(ref_coords) < 2:
        raise ValueError("wall_line must have at least two points")

    dx_ref = ref_coords[-1][0] - ref_coords[0][0]
    dy_ref = ref_coords[-1][1] - ref_coords[0][1]
    ref_len = math.hypot(dx_ref, dy_ref)
    if ref_len == 0:
        raise ValueError("wall_line can;t have 0 length")

    ref_unit = np.array([dx_ref / ref_len, dy_ref / ref_len], dtype=float)
    sin_threshold = math.sin(math.radians(angle_tolerance_degrees))

    parallel_edges: List[LineString] = []

    geom = house.geometry.iloc[0]
    if geom is None or geom.is_empty:
        return parallel_edges

    if isinstance(geom, Polygon):
        polygons = [geom]
    elif isinstance(geom, MultiPolygon):
        polygons = list(geom.geoms)
    else:
        return parallel_edges

    #TODO: change name to edge because poly should be closing the loop
    for poly in polygons:
        exterior = list(poly.exterior.coords)
        for i in range(len(exterior) - 1):
            seg = LineString([exterior[i], exterior[i + 1]])
            if seg.is_empty:
                continue

            seg_t = utils.truncate_coordinates(seg)
            seg_coords = list(seg_t.coords)
            if len(seg_coords) < 2:
                continue

            dx = seg_coords[-1][0] - seg_coords[0][0]
            dy = seg_coords[-1][1] - seg_coords[0][1]
            seg_len = math.hypot(dx, dy)

            if seg_len < min_segment_length:
                continue

            seg_unit = np.array([dx / seg_len, dy / seg_len], dtype=float)

            sin_theta = abs(ref_unit[0] * seg_unit[1] - ref_unit[1] * seg_unit[0])

            if sin_theta <= sin_threshold:
                parallel_edges.append(seg)

    return parallel_edges

#TODO: remove
def _find_outer_wall(
    parallel_house_lines: List[LineString], 
    plot_border: LineString
) -> Optional[LineString]:
    """
    Finds the line from parallel_house_lines that has the greatest distance to plot_border.
    
    Args:
        parallel_house_lines (List[Line]): A list of parallel lines representing house walls.
        plot_border (LineString): A line representing the property border.
    
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

def _find_furthest_line(
    candidate_lines: Iterable[LineString],
    reference_geom: BaseGeometry,
) -> Optional[LineString]:
    """
    Return the candidate line with the greatest shortest distance to a reference geometry.

    Args:
        candidate_lines: Iterable of LineStrings to compare.
        reference_geom: Geometry (LineString/Polygon/etc.) to measure distance from.

    Returns:
        The LineString with the maximum distance to reference_geom, or None if no valid candidates.
    """
    if reference_geom is None or reference_geom.is_empty:
        return None

    best_line: Optional[LineString] = None
    max_distance: float = float("-inf")

    for line in candidate_lines:
        if line is None or line.is_empty:
            continue

        d = line.distance(reference_geom)  # shortest distance
        if d > max_distance:
            max_distance = d
            best_line = line

    return best_line

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
        furthest_line = _find_furthest_line(parallel_lines, border_line)

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

def _create_plot_border(shared_walls: Dict, plot: Polygon) -> LineString:
    """Creates an extended border line from a shared wall with a neighbor.
    
    Args:
        shared_walls: LineString representing the shared wall with a neighbor
        plot: Polygon representing the complete plot boundary
    
    Returns:
        LineString: The extended border line that intersects with the plot boundary
    """

    shared_walls = LineString(list(shared_walls.values())[0])

    extended_line = utils.extend_line_through_polygon(shared_walls, plot)
    intersection = extended_line.intersection(plot)

    return LineString(list(intersection.coords)) if intersection else LineString()
        
def _is_outer_corner_house(
    houses: gpd.GeoDataFrame, 
    house: gpd.GeoDataFrame
) -> bool:
    """Check if the house is an outer corner house.
    
    Args:
        houses: GeoDataFrame containing all houses in the plot
        house: GeoDataFrame containing single house geometry
    
    Returns:
        bool: True if the house is an outer corner house, False otherwise
    """

    # Find if it's an outer corner by comparing centroid distances
    houses['centroid'] = houses.geometry.centroid
    distance_matrix = houses['centroid'].apply(lambda x: houses['centroid'].distance(x))
    distance_array = np.array(distance_matrix)
    
    # If houses are furthest apart, they are likely to be on opposite corners of the plot.
    max_indices = np.unravel_index(np.argmax(distance_array), distance_array.shape)
    house_ids = list(houses["identificatie"])
    current_house_id = house["identificatie"].iloc[0] 
    
    # Check if current house is an outer corner
    is_outer_corner = (
        current_house_id == house_ids[max_indices[0]] or 
        current_house_id == house_ids[max_indices[1]]
    )
    
    return is_outer_corner

def _get_corner_house_plot(
    border_line: LineString,
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
        #length = (direction[0] ** 2 + direction[1] ** 2) **0.2
        length = math.hypot(direction[0], direction[1])
        unit_direction = (direction[0] / length, direction[1] / length)

        extension_length = 30
        new_start = Point(start.x - unit_direction[0] * extension_length, 
                          start.y - unit_direction[1] * extension_length)
        
        new_end = Point(end.x + unit_direction[0] * extension_length,
                        end.y + unit_direction[1] * extension_length)

        new_plot_line = LineString([new_start, new_end])
        intersection = new_plot_line.intersection(plot)
        
        if intersection:
            # add points from the lines to new_plot
            plot_lines.append(list(intersection.coords))


    if len(plot_lines) < 2:
        raise RuntimeError("Expected at least 2 plot border intersections")

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
    gdf_road_in_plot: gpd.GeoDataFrame,
    visualise: bool = False
) -> List[Dict]:
    
    """
    Process a set of aligned houses within a plot to assign garden and storage areas for each house.

    This function iterates over all houses in the provided GeoDataFrame, determines their neighbors,
    classifies them as corner or non-corner houses, and computes the corresponding garden and storage
    areas. Optionally, it can visualize the results for each house.

    Args:
        data (DataBundle): Data bundle containing relevant GeoDataFrames, including building footprints.
        plot_poly (Polygon): The complete plot boundary polygon.
        gdf_bag_in_plot (gpd.GeoDataFrame): GeoDataFrame of houses within the plot.
        gdf_plot (gpd.GeoDataFrame): GeoDataFrame of the plot itself.
        gdf_road_in_plot (gpd.GeoDataFrame): GeoDataFrame of roads within the plot.
        visualise (bool, optional): If True, visualize the house, plot, and storage assignment. Default is False.

    Returns:
        List[Dict]: A list of HouseResult dictionaries, each containing the house ID, storage size,
        garden size, and classification for each processed house.
    """
    results = []

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
            border_line = _create_plot_border(neighbours, plot_poly)

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

        if visualise:
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
        
    return results

