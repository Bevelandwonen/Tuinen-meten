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
    return points

def _first_intersection(
    origin: Point, 
    direction: tuple, 
    weg: gpd.GeoDataFrame, 
    plot: Polygon
) -> Point:
    
    """Return the first intersection point along a ray."""

    extension_length = 30
    road_union = weg.geometry.unary_union
    plot_boundary = plot.boundary

    ray = LineString([
        (origin.x, origin.y),
        (origin.x + direction[0] * extension_length,
        origin.y + direction[1] * extension_length)
    ])

    intersections = []

    for geom in [road_union, plot_boundary]:
        inter = ray.intersection(geom)
        if not inter.is_empty:
            points = extract_points(inter)

            for p in points:
                dist = origin.distance(p)

                # ignore intersection at the starting point
                if dist > 1e-6:
                    intersections.append((dist, p))

    if not intersections:
        return None

    intersections.sort(key=lambda x: x[0])
    return intersections[0][1]

#TODO: this functino is almost the same as _create_plot from multiple_aligned.py
def _create_plot_open(
    shared_walls: Dict, 
    plot: Polygon, 
    weg: gpd.GeoDataFrame
) -> Polygon:
    
    """
    Create a parcel for an open house.
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
        # With neighbourse
        neighbours = utils.find_borders(gdf_bag_in_plot, row)
        #TODO: Check this line
        house = gdf_bag_in_plot[
            gdf_bag_in_plot["identificatie"] == row["identificatie"]
        ]

        neighbour_count = len(neighbours)

        if neighbour_count not in (1, 2):

            results.append(
                HouseResult(
                    pand_id=row["identificatie"],
                    storage=None,
                    nieuw_tuin_opp=None,
                    classificatie="open_no_neighbours",
                    error=f"Expected 1 or 2 neighbours, found {neighbour_count}"
                )
            )
            continue
            
        if neighbour_count == 1:
            results.append(
                HouseResult(
                    pand_id=row["identificatie"],
                    storage=None,
                    nieuw_tuin_opp=None,
                    classificatie="open_one_neighbour",
                    error="Only one neighbour found, cannot determine plot shape"
                )
            )
            continue
        
        else:
            print("two matches thus neibours")
            new_poly = _create_plot_open(house, neighbours, plot_poly, gdf_weg_in_plot)
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

        # TODO: Check if we need this or visaluse function works
        ax = gdf_plot.plot(color='blue', edgecolor='black')
        gdf_bag_in_plot.plot(ax=ax, color='red', edgecolor='black')
        house.plot(ax=ax, color='yellow', edgecolor='black')
        gdf_weg_in_plot.plot(ax=ax, color="green")
        #put new poly in gpd so we can visualise it
        new_poly_gdf = gpd.GeoDataFrame(geometry=[new_poly], crs=gdf_plot.crs)

        new_poly_gdf.plot(ax=ax, color="orange", edgecolor='black')
        gdf_pand_within = data.gdf_pand[data.gdf_pand.geometry.within(plot_poly)]
        gdf_pand_within.plot(ax=ax, color="pink")

        fig = ax.get_figure()
        plt.show()

        results.append(
            HouseResult(
                pand_id=row["identificatie"],
                storage=storage_size,
                nieuw_tuin_opp=garden_size,
                classificatie="open_with_two_neighbours",
            )
        )

    return results