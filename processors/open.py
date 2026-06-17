from typing import Dict, List
import geopandas as gpd

from shapely.geometry import Point
from shapely.geometry import LineString, Polygon
import matplotlib.pyplot as plt

from datatypes import DataBundle, HouseResult
from . import utils

def extract_points(geom: Polygon) -> List[Point]:
    """
    Extract points from an intersection geometry.
    Returns a list of shapely Points.
    """
    points = []
    if geom.is_empty:
        return points
    if geom.geom_type == "Point":
        points.append(geom)
    elif geom.geom_type == "MultiPoint":
        points.extend(list(geom.geoms))
    elif geom.geom_type == "LineString":
        points.append(Point(list(geom.coords)[0]))
        points.append(Point(list(geom.coords)[-1]))
    elif geom.geom_type == "MultiLineString":
        for line in geom.geoms:
            points.append(Point(list(line.coords)[0]))
            points.append(Point(list(line.coords)[-1]))
    elif geom.geom_type == "GeometryCollection":
        for g in geom.geoms:
            points.extend(extract_points(g))
    return points

def _first_intersection(
    origin: Point, 
    direction: tuple, 
    weg: gpd.GeoDataFrame, 
    plot: Polygon
) -> Point:
    
    """Return the first intersection point along a ray. If the intersection is too close to the origin, it is ignored. If there are no valid intersections, return None."""

    #TODO: Should add a check if we intersect a different house 
    # or something before hitting the road or plot boundary.
    # Add data?

    extension_length = 50
    road_union = weg.geometry.unary_union
    plot_boundary = plot.boundary

    ray = LineString([
        (origin.x, origin.y),
        (origin.x + direction[0] * extension_length,
        origin.y + direction[1] * extension_length)
    ])

    intersections = []
    # print the amount of different geometries
    #check shape?
    counter = 0
    for geom in [road_union, plot_boundary]:
        #TODO: WHy does this function return different types of geoms?
        inter = ray.intersection(geom)
        if not inter.is_empty:
            points = extract_points(inter)

            for p in points:
                dist = origin.distance(p)
                intersections.append((dist, p))


        counter += 1
    if not intersections:
        return None

    # if there is more than one point, remove point that have a dist < 1e-5 (the starting point)
    # because we have other valid options
    if len(intersections) > 1:
        intersections = [(dist, p) for dist, p in intersections if dist > 1e-1]

    intersections.sort(key=lambda x: x[0])
    return intersections[0][1]

#TODO: this function is almost the same as _create_plot from multiple_aligned.py
def _create_plot_open(
    shared_walls: Dict, 
    plot: Polygon, 
    weg: gpd.GeoDataFrame
) -> Polygon:
    
    """
    Create a parcel for a house on an open plot.
    For each wall (A,B) we cast two rays:
        A -> B direction
        B -> A direction
    We take the first intersection with road or parcel boundary.
    """

    plot_lines = []
    for _, (start, end) in shared_walls.items():
        dx = end.x - start.x
        dy = end.y - start.y
        length = (dx**2 + dy**2) ** 0.5

        unit = (dx / length, dy / length)
        reverse = (-unit[0], -unit[1])

        p1 = _first_intersection(start, unit, weg, plot)
        p2 = _first_intersection(end, reverse, weg, plot)

        if p1 and p2:
            plot_lines.append([(p1.x, p1.y), (p2.x, p2.y)])

    if len(plot_lines) < 2:
        #return empty poly
        return Polygon()

    line1, line2 = plot_lines[0], plot_lines[1]

    d1 = Point(line1[0]).distance(Point(line2[0]))
    d2 = Point(line1[1]).distance(Point(line2[0]))
    if d1 > d2:
        combined_coords = line1 + line2
    else:
        combined_coords = line1 + line2[::-1]

    if combined_coords[0] != combined_coords[-1]:
        combined_coords.append(combined_coords[0])

    return Polygon(combined_coords)



import logging
from typing import Final

import geopandas as gpd
from shapely.geometry import Polygon

logger = logging.getLogger(__name__)

CLASS_INVALID_NEIGHBOUR_COUNT: Final[str] = "open_invalid_neighbour_count"
CLASS_ONE_NEIGHBOUR: Final[str] = "open_one_neighbour"
CLASS_TWO_NEIGHBOURS: Final[str] = "open_with_two_neighbours"

def _build_result(
    pand_id: str,
    classification: str,
    storage_size: float | None = None,
    garden_size: float | None = None,
    error: str | None = None,
) -> HouseResult:
    return HouseResult(
        pand_id=pand_id,
        storage_size=storage_size,
        garden_size=garden_size,
        classification=classification,
        error=error,
    )

def _validate_neighbour_count(pand_id: str, neighbour_count: int) -> HouseResult | None:
    """
    Validate neighbour count for an open plot.

    Returns:
        A failure HouseResult if processing should stop for this house,
        otherwise None.
    """
    if neighbour_count not in (1, 2):
        return _build_result(
            pand_id=pand_id,
            classification=CLASS_INVALID_NEIGHBOUR_COUNT,
            error=f"Expected 1 or 2 neighbours, found {neighbour_count}",
        )

    if neighbour_count == 1:
        return _build_result(
            pand_id=pand_id,
            classification=CLASS_ONE_NEIGHBOUR,
            error="Only one neighbour found; cannot determine plot shape",
        )

    return None

#TODO: reuse and move to utils?
def _is_valid_polygon(poly: Polygon) -> bool:
    return poly.is_valid and poly.area > 0

def _process_open_house(
    pand_id: str,
    house_gdf: gpd.GeoDataFrame,
    neighbours: Dict,
    plot_poly: Polygon,
    gdf_weg_in_plot: gpd.GeoDataFrame,
    gdf_plot: gpd.GeoDataFrame,
    gdf_bag_in_plot: gpd.GeoDataFrame,
    data: DataBundle,
    visualise: bool,
) -> HouseResult:
    """
    Process a single house in an open plot situation with two neighbours.
    """
    new_poly = _create_plot_open(neighbours, plot_poly, gdf_weg_in_plot)

    if not _is_valid_polygon(new_poly):
        logger.warning(
            "Invalid plot polygon generated for pand_id=%s (valid=%s, area=%.3f)",
            pand_id,
            new_poly.is_valid,
            new_poly.area,
        )
        return _build_result(
            pand_id=pand_id,
            classification=CLASS_TWO_NEIGHBOURS,
            error="Failed to create a valid plot polygon",
        )

    storage, storage_size = utils.find_berging(new_poly, data.gdf_pand)
    garden_size = utils.calc_areas(
        gdf_weg_in_plot,
        new_poly,
        house_gdf,
        storage_size,
    )

    if visualise:
        utils.visualise_house_plot(
            gdf_plot,
            new_poly,
            gdf_bag_in_plot,
            gdf_weg_in_plot,
            storage,
        )

    logger.info(
        "Processed pand_id=%s | garden_size=%.1f m² | storage_size=%.1f m²",
        pand_id,
        garden_size,
        storage_size,
    )

    return _build_result(
        pand_id=pand_id,
        classification=CLASS_TWO_NEIGHBOURS,
        storage_size=storage_size,
        garden_size=garden_size,
    )

def open_plot(
    data: DataBundle,
    plot_poly: Polygon,
    gdf_bag_in_plot: gpd.GeoDataFrame,
    gdf_plot: gpd.GeoDataFrame,
    gdf_weg_in_plot: gpd.GeoDataFrame,
    visualise: bool = False,
) -> list[HouseResult]:
    """
    Determine garden and storage sizes for houses in an open plot configuration.

    For each house in ``gdf_bag_in_plot``:
    - find neighbouring houses
    - validate whether the neighbour count supports open-plot processing
    - derive a plot polygon for valid cases
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
            result = _process_open_house(
                pand_id=pand_id,
                house_gdf=house_gdf,
                neighbours=neighbours,
                plot_poly=plot_poly,
                gdf_weg_in_plot=gdf_weg_in_plot,
                gdf_plot=gdf_plot,
                gdf_bag_in_plot=gdf_bag_in_plot,
                data=data,
                visualise=visualise,
            )
        except Exception:
            logger.exception("Unexpected error while processing pand_id=%s", pand_id)
            result = _build_result(
                pand_id=pand_id,
                classification=CLASS_TWO_NEIGHBOURS,
                error="Unexpected error while processing plot",
            )

        results.append(result)

    return results
