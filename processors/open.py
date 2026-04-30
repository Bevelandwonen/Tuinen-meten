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
            """
            print(points)
            fig, ax = plt.subplots(figsize=(8, 8))
            gpd.GeoSeries(road_union).plot(ax=ax, color='green', linewidth=1, zorder=1)
            gpd.GeoSeries(plot_boundary).plot(ax=ax, color='blue', linewidth=1, zorder=1)
            gpd.GeoSeries(ray).plot(ax=ax, color='orange', linewidth=2, zorder=2)
            if points:
                    gpd.GeoSeries(points).plot(ax=ax, color='red', markersize=50, zorder=3)
            plt.show()
            """

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
        raise ValueError("Not enough intersection points found to create a polygon.")

    line1, line2 = plot_lines[0], plot_lines[1]

    d1 = Point(line1[0]).distance(Point(line2[0]))
    d2 = Point(line1[1]).distance(Point(line2[0]))
    if d1 > d2:
        combined_coords = line1 + line2
    else:
        combined_coords = line1 + line2[::-1]

    if combined_coords[0] != combined_coords[-1]:
        combined_coords.append(combined_coords[0])

    #plot the plot and the polygon(combined_coords)
    ax = plt.subplot(111)
    gpd.GeoSeries(plot).boundary.plot(ax=ax, color='blue', linewidth=1, zorder=1)
    gpd.GeoSeries(LineString(combined_coords)).plot(ax=ax, color='orange', linewidth=2, zorder=2)
    plt.show()


    return Polygon(combined_coords)

def open_plot(
    data: DataBundle, 
    plot_poly: Polygon,
    gdf_bag_in_plot: gpd.GeoDataFrame, 
    gdf_plot: gpd.GeoDataFrame,
    gdf_weg_in_plot: gpd.GeoDataFrame,
    visualise: bool = False
) -> List[Dict]:

    results = []
    
    for _, row in gdf_bag_in_plot.iterrows():
        neighbours = utils.find_borders(gdf_bag_in_plot, row)
        #TODO: Check this line
        house = gdf_bag_in_plot[
            gdf_bag_in_plot["identificatie"] == row["identificatie"]
        ]
        print("dit is 1 woning", row["identificatie"])
        if row["identificatie"] != "0718100000000981":
            continue

        #plot plot_poly, house, neighbours and gdf_weg_in_plot
        ax = plt.subplot(111)
        gpd.GeoSeries(plot_poly).boundary.plot(ax=ax, color='blue', linewidth=1, zorder=1)
        gpd.GeoSeries(house.geometry).plot(ax=ax, color='green', linewidth=1, zorder=2)
        gpd.GeoSeries(gdf_weg_in_plot.geometry).plot(ax=ax, color='grey', linewidth=1, zorder=3)
        plt.show()

        neighbour_count = len(neighbours)

        if neighbour_count not in (1, 2):

            results.append(
                HouseResult(
                    pand_id=row["identificatie"],
                    storage_size=None,
                    garden_size=None,
                    classification="open_no_neighbours",
                    error=f"Expected 1 or 2 neighbours, found {neighbour_count}"
                )
            )
            continue
            
        if neighbour_count == 1:
            results.append(
                HouseResult(
                    pand_id=row["identificatie"],
                    storage_size=None,
                    garden_size=None,
                    classification="open_one_neighbour",
                    error="Only one neighbour found, cannot determine plot shape"
                )
            )
            continue
        
        else:
            try:
                new_poly = _create_plot_open(neighbours, plot_poly, gdf_weg_in_plot)
            except Exception as e:
                results.append(
                    HouseResult(
                        pand_id=row["identificatie"],
                        storage_size=None,
                        garden_size=None,
                        classification="open_with_two_neighbours",
                        error=f"Failed to create plot polygon: {e}"
                    )
                )
                continue
            storage, storage_size = utils.find_berging(new_poly, data.gdf_pand)
            garden_size = utils.calc_areas(gdf_weg_in_plot, new_poly, house, storage_size)

        if visualise:
            utils.visualise_house_plot(
                gdf_plot, 
                new_poly, 
                gdf_bag_in_plot, 
                gdf_weg_in_plot, 
                storage,
            )

        print(f"Tuin opp = {garden_size:.1f}m², Berging opp = {storage_size:.1f}m²")
        
        results.append(
            HouseResult(
                pand_id=row["identificatie"],
                storage_size=storage_size,
                garden_size=garden_size,
                classification="open_with_two_neighbours",
            )
        )

    return results