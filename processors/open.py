from . import utils
import geopandas as gpd
import matplotlib.pyplot as plt
import geopandas as gpd
from shapely.geometry import LineString, Polygon
import matplotlib.pyplot as plt
import geopandas as gpd
from shapely.geometry import Point
from typing import Dict, List
from datatypes import DataBundle

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

def first_intersection(
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
        print(type(inter))
        print(inter)
        if not inter.is_empty:
            points = extract_points(inter)

            for p in points:
                print(p)
                print(origin)
                dist = origin.distance(p)

                # ignore intersection at the starting point
                if dist > 1e-6:
                    intersections.append((dist, p))

    if not intersections:
        return None

    intersections.sort(key=lambda x: x[0])
    return intersections[0][1]

def _create_plot_open(
    house: gpd.GeoDataFrame, 
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

        p1 = first_intersection(start, unit, weg, plot)
        p2 = first_intersection(end, reverse, weg, plot)

        if p1 and p2:
            plot_lines.append([(p1.x, p1.y), (p2.x, p2.y)])

    if len(plot_lines) < 2:
        raise ValueError("Not enough intersection points found to create a polygon.")

    print(plot_lines)

    line1, line2 = plot_lines[0], plot_lines[1]

    d1 = Point(line1[0]).distance(Point(line2[0]))
    d2 = Point(line1[1]).distance(Point(line2[0]))

    if d1 > d2:
        combined_coords = line1 + line2
    else:
        combined_coords = line1 + line2[::-1]

    if combined_coords[0] != combined_coords[-1]:
        combined_coords.append(combined_coords[0])

    fig, ax = plt.subplots()

    for line in plot_lines:
        for p in line:
            ax.plot(p[0], p[1], 'ro')

    gpd.GeoSeries(plot).plot(ax=ax, edgecolor='black')
    house.plot(ax=ax, color='yellow', edgecolor='black')

    plt.show()
    
    return Polygon(combined_coords)

def open_plot(
    data: DataBundle, 
    plot_poly: Polygon,
    gdf_bag_temp: gpd.GeoDataFrame, 
    gdf_plot: gpd.GeoDataFrame,
    gdf_weg_temp: gpd.GeoDataFrame
) -> List[Dict]:

    #TODO: fix deze functie

    results = []
    errors = []
    
    for _, row in gdf_bag_temp.iterrows():
        # With neighbourse
        matches = utils.find_borders(gdf_bag_temp, row)
        #TODO: Check this line
        house = gdf_bag_temp[gdf_bag_temp["identificatie"] == row["identificatie"]]

        #TODO: catch errors

        if len(matches) == 1:
            print("one match, dont have neighbours")
        elif len(matches) == 2:
            try:
                print("two matches thus neibours")
                new_poly = _create_plot_open(house, matches, plot_poly, gdf_weg_temp)
            except Exception as e:
                results.append({
                    "Pand Id": row["identificatie"],
                    "storage": None,
                    "nieuw tuin opp": None,
                    "classificatie": "open_error",
                    "error": str(e)
                })
                continue

        storage, storage_size = utils.find_berging(new_poly, data.gdf_pand)
        garden_size = utils.calc_areas(gdf_weg_temp, new_poly, house, storage_size)
        utils.visualise_house_plot(gdf_plot, new_poly, gdf_bag_temp, gdf_weg_temp, storage)

        print(f"Tuin opp = {garden_size:.1f}m², Berging opp = {storage_size:.1f}m²")

        ax = gdf_plot.plot(color='blue', edgecolor='black')
        gdf_bag_temp.plot(ax=ax, color='red', edgecolor='black')
        house.plot(ax=ax, color='yellow', edgecolor='black')
        gdf_weg_temp.plot(ax=ax, color="green")
        #put new poly in gpd so we can visualise it
        new_poly_gdf = gpd.GeoDataFrame(geometry=[new_poly], crs=gdf_plot.crs)

        new_poly_gdf.plot(ax=ax, color="orange", edgecolor='black')
        gdf_pand_within = data.gdf_pand[data.gdf_pand.geometry.within(plot_poly)]
        gdf_pand_within.plot(ax=ax, color="pink")

        fig = ax.get_figure()
        plt.show()

        results.append({
            "Pand Id": row["identificatie"],
            "storage": storage_size,
            "nieuw tuin opp": garden_size,
            "classificatie": "multiple_aligned"
        })
    
    return results