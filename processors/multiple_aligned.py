import math
from typing import Dict, List, Optional, Iterable, Mapping, Sequence, Any

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, Point, Polygon, MultiPolygon
from shapely.prepared import prep
from shapely.geometry.base import BaseGeometry
from shapely.ops import split, snap, nearest_points
from shapely.validation import explain_validity

import geopandas as gpd
from shapely.geometry import LineString, Polygon

from . import utils
from datatypes import DataBundle, HouseResult
from utility import PlotType

def _find_parallel_edge(
    house: gpd.GeoDataFrame,
    wall_line: LineString,
    angle_tolerance_degrees: float = 10.0,
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

    # Find parallel wall
    parallel_lines = _find_parallel_edge(house, border_line)
    furthest_line = _find_furthest_line(parallel_lines, border_line)

    if not furthest_line:
        return None

    second_border = _create_plot_border(furthest_line, plot)
    
    line1_coords = list(border_line.coords)
    line2_coords = list(second_border.coords)

    corners = [
        line1_coords[0],
        line1_coords[1],
        line2_coords[1],
        line2_coords[0]
    ]

    return Polygon(corners)
        
def _create_plot_border(
    shared_walls: LineString,
    plot: Polygon
) -> LineString:
    """Creates an extended border line from a shared wall with a neighbor.
    
    Args:
        shared_walls: LineString representing the shared wall with a neighbor
        plot: Polygon representing the complete plot boundary
    
    Returns:
        LineString: The extended border line that intersects with the plot boundary
    """

    extended_line = utils.extend_line_through_polygon(shared_walls, plot)
    intersection = extended_line.intersection(plot)
    if intersection:
        intersection = utils.extract_line(intersection)
    return LineString(intersection) if intersection else LineString()
        
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

    # Find polygon with most house overlap
    house_geom = house["geometry"].iloc[0]
    overlaps = [poly.intersection(house_geom).area for poly in split_polygons]
    
    #get index of the polygon with the most overlap
    max_index = overlaps.index(max(overlaps))

    return split_polygons[max_index]

def lines_intersect_inside_plot(
    line1: LineString, 
    line2: LineString, 
    plot, 
    tol=1e-6
) -> bool:

    inter = line1.intersection(line2)
    if inter.is_empty:
        return False

    if inter.geom_type in ("LineString", "MultiLineString"):
        return True

    inter_geom = inter.buffer(tol)
    return plot.contains(inter_geom)  # inside (not just touching boundary)

#TODO: Kinda duplicate with create_plot in open plot. Make one function
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
    """

    plot_lines = []
    print(f"Shared walls: {shared_walls}")

    for _, values in shared_walls.items():
        start, end = values[0], values[1]

        direction = ((end.x - start.x), (end.y - start.y))
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
            line = utils.extract_line(intersection)
            # add points from the lines to new_plot
            plot_lines.append(line)

    line_intersect = lines_intersect_inside_plot(
        LineString(plot_lines[0]),
        LineString(plot_lines[1]),
        plot
    )
    if line_intersect or len(plot_lines) < 2:
       # Maybe use a enum/object for result
       return None
     
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

    if not new_house_plot.is_valid:
        print(explain_validity(new_house_plot))
   
    return new_house_plot

def _validate_neighbour_count(pand_id: str, neighbour_count: int) -> HouseResult | None:
    """
    Validate the number of neighbours for a multiple-aligned house.

    Returns:
        A failure result if the house cannot be processed, otherwise None.
    """
    if neighbour_count not in (1, 2):
        return utils.build_result(
            pand_id=pand_id,
            classification= "multiple_aligned_error_invalid_neighbour_count",
            error=f"Expected 1 or 2 neighbours, found {neighbour_count}",
        )

    return None

def _create_corner_plot(
    neighbours: Mapping[Any, Sequence],
    house_gdf: gpd.GeoDataFrame,
    gdf_bag_in_plot: gpd.GeoDataFrame,
    plot_poly: Polygon,
) -> Polygon | None:
    """
    Create a plot polygon for a corner house.
    """
    neighbour_points = next(iter(neighbours.values()), None)
    if not neighbour_points:
        return None

    neighbour_line = LineString(neighbour_points)
    border_line = _create_plot_border(neighbour_line, plot_poly)

    if _is_outer_corner_house(gdf_bag_in_plot, house_gdf):
        return _get_corner_house_plot(
            border_line=border_line,
            house=house_gdf,
            plot_poly=plot_poly,
        )

    return _get_inner_corner_plot(
        house=house_gdf,
        border_line=border_line,
        plot_poly=plot_poly,
    )

def _create_aligned_plot(
    neighbours: Mapping[Any, Sequence],
    house_gdf: gpd.GeoDataFrame,
    gdf_bag_in_plot: gpd.GeoDataFrame,
    plot_poly: Polygon,
) -> Polygon | None:
    """
    Create a plot polygon for a multiple-aligned house.

    - 1 neighbour  -> corner house path
    - 2 neighbours -> standard aligned house path
    """
    neighbour_count = len(neighbours)

    if neighbour_count == 1:
        return _create_corner_plot(
            neighbours=neighbours,
            house_gdf=house_gdf,
            gdf_bag_in_plot=gdf_bag_in_plot,
            plot_poly=plot_poly,
        )

    return create_plot(neighbours, plot_poly)

def _process_multiple_aligned_house(
    pand_id: str,
    house_gdf: gpd.GeoDataFrame,
    neighbours: Mapping[Any, Sequence],
    gdf_bag_in_plot: gpd.GeoDataFrame,
    gdf_plot: gpd.GeoDataFrame,
    gdf_road_in_plot: gpd.GeoDataFrame,
    plot_poly: Polygon,
    data: DataBundle,
    visualise: bool,
) -> HouseResult:
    """
    Process a single house in a multiple-aligned plot configuration.
    """
    new_poly = _create_aligned_plot(
        neighbours=neighbours,
        house_gdf=house_gdf,
        gdf_bag_in_plot=gdf_bag_in_plot,
        plot_poly=plot_poly,
    )

    if not utils.is_valid_plot_polygon(new_poly):
        return utils.build_result(
            pand_id=pand_id,
            classification="multiple_aligned_error_plot_creation_failed",
            storage_size=0,
            garden_size=0,
            error="Failed to create a valid plot polygon",
        )

    storage, storage_size = utils.find_berging(new_poly, data.gdf_pand)

    garden_size = utils.calc_areas(
        gdf_road_in_plot,
        new_poly,
        house_gdf,
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

    return utils.build_result(
        pand_id=pand_id,
        classification=PlotType.MULTIPLE_ALIGNED.value,
        storage_size=storage_size,
        garden_size=garden_size,
    )

def multiple_aligned(
    data: DataBundle,
    plot_poly: Polygon,
    gdf_bag_in_plot: gpd.GeoDataFrame,
    gdf_plot: gpd.GeoDataFrame,
    gdf_road_in_plot: gpd.GeoDataFrame,
    visualise: bool = False,
) -> list[HouseResult]:
    """
    Process aligned houses within a plot and assign garden and storage areas.

    For each house in ``gdf_bag_in_plot``:
    - determine neighbouring houses
    - validate whether the neighbour count is supported
    - classify corner vs non-corner logic
    - derive a plot polygon
    - calculate storage and garden size
    - optionally visualise the result

    Returns:
        A list of HouseResult objects, one for each processed house.
    """
    results: list[HouseResult] = []

    for idx, row in gdf_bag_in_plot.iterrows():
        pand_id = row["identificatie"]
        house_gdf = gdf_bag_in_plot.loc[[idx]]
        neighbours = utils.find_borders(gdf_bag_in_plot, row)

        invalid_result = _validate_neighbour_count(pand_id, len(neighbours))
        if invalid_result is not None:
            results.append(invalid_result)
            continue

        try:
            result = _process_multiple_aligned_house(
                pand_id=pand_id,
                house_gdf=house_gdf,
                neighbours=neighbours,
                gdf_bag_in_plot=gdf_bag_in_plot,
                gdf_plot=gdf_plot,
                gdf_road_in_plot=gdf_road_in_plot,
                plot_poly=plot_poly,
                data=data,
                visualise=visualise,
            )
        except Exception as exc:
            result = utils.build_result(
                pand_id=pand_id,
                classification="multiple_aligned_error_unexpected",
                storage_size=0,
                garden_size=0,
                error=f"Unexpected error while processing house: {exc}",
            )

        results.append(result)

    return results
