import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from shapely.geometry import Point
from shapely.geometry.polygon import Polygon
from shapely.geometry import LineString
from shapely.ops import split
import numpy as np
from shapely.ops import snap
from sympy import Point
from shapely.ops import nearest_points
import math
import fiona

# Final file
""" This script takes four files:
#TODO: change filename and df names
    - BAG file with pand data
    - Kadaster file
    - ERP data with matching kadaster number -> made by perceel_eenheid_matcher
    - POK file containing public road data  
    

    We go over each perceel match that we found.

    In this file we find the walls that share a neighbour, then we extend these to find the mini perceel

"""

def create_one_big_polygon(perceel):
    """Creates a single polygon from multiple lines in perceel using GeoPandas."""
    # Convert perceel to a GeoSeries of LineStrings
    lines = gpd.GeoSeries([LineString(line.coords) for line in perceel])
    # Use polygonize to create polygons from the lines
    polygons = lines.polygonize()
    # Assuming you want the first polygon created
    big_poly = list(polygons)[0]
    return big_poly 

def perceel_borders2(gdf2_temp, row):
    #TODO ROW HERE IS THE HOUSE ITSELF.
    # WHAT IS GOING WRONG
    perceel_points = row["geometry"]
    gdf2_temp_neighbours = gdf2_temp[gdf2_temp["identificatie"] != row["identificatie"]]
    matches = {}

    for point_x, point_y in perceel_points.exterior.coords:
        check_point = Point(point_x, point_y)
        for _, neighbour_points in gdf2_temp_neighbours.iterrows():
            eenheid_neighbour = neighbour_points["identificatie"]
            poly = neighbour_points["geometry"]
            is_equal = any(check_point.equals(Point(x, y)) for x, y in poly.exterior.coords)
            if is_equal:
                if eenheid_neighbour in matches:
                    if check_point in matches[eenheid_neighbour]:
                        continue
                    else:
                        side_wall_coordinates = matches[eenheid_neighbour]
                        side_wall_coordinates.append(check_point)
                        matches[eenheid_neighbour] = side_wall_coordinates
                else:
                    matches[eenheid_neighbour] = [check_point]
    return matches

def generate_lines(points):
    lines = []

    for i in range(len(points) - 1):
        line1 = LineString([points[i], points[i + 1]])
        lines.append(line1)
    return lines

# Move to diff file
def truncate_coordinates(line):
    return LineString([(int(x * 10) / 10.0, int(y * 10) / 10.0) for x, y in line.coords])

def perceel_borders(gdf2_temp, row):
    # Get walls with neigbours
    # We give all houses and one house and check how many neighbours
    perceel_points = row["geometry"]
    gdf2_temp_neighbours = gdf2_temp[gdf2_temp["identificatie"] != row["identificatie"]]
    matches = {}
    eenheid_points_list = list(perceel_points.exterior.coords)
    eenheid_lines = generate_lines(eenheid_points_list)
    for i in eenheid_lines:
        line1 = i
        
        # Iterate over the lines of the neighboring geometries
        # TODO: CAn do a more extensive search (not only next, but all combinations)
        for _, neighbour in gdf2_temp_neighbours.iterrows():

            # Generate all possible lines from the polygon points
            eenheid_neighbour = neighbour["identificatie"]
            neighbour_polygon = neighbour['geometry']
            polygon_lines = list(neighbour_polygon.exterior.coords)
            polygon_lines = generate_lines(polygon_lines)
            for neighbour_lines in polygon_lines:
                # Check if the lines overlap
                # If one point is the same we also have overlap
                # That is why we test for x amount of overlap
                #  TODO: Maybe check % overlap
                #TODO: Make seperate function

                # Truncated linestrings
                truncated_line1 = truncate_coordinates(line1)
                truncated_neighbour_lines = truncate_coordinates(neighbour_lines)

                if truncated_line1.intersects(truncated_neighbour_lines):
                    # We add a buffer, to widen the line
                    line11 = truncated_line1.buffer(0.0111)
                    neighbour_lines1 = truncated_neighbour_lines.buffer(0.0111)
                    # Dont write the buffered ones to matches, 
                    overlap = line11.intersection(neighbour_lines1).length
                    if overlap >= 2.0:
                        if eenheid_neighbour in matches:
                            continue
                        else:
                            matches[eenheid_neighbour] = [Point(neighbour_lines.coords[0]), Point(neighbour_lines.coords[1])]
    return matches

def create_perceel(matches, perceel_poly):
    # Create gardens here
    perceel_lines = []
    for key, values in matches.items():
        start, end = values[0], values[1]

        direction = ((end.x - start.x), (end.y - start.y))

        #normalize the direction vector
        length = (direction[0] ** 2 + direction[1] ** 2) **0.2
        unit_direction = (direction[0] / length, direction[1] / length)

        extension_length = 30
        new_start = Point(start.x - unit_direction[0] * extension_length, start.y - unit_direction[1] * extension_length)
        new_end = Point(end.x + unit_direction[0] * extension_length, end.y + unit_direction[1] * extension_length)

        extended_line = LineString([new_start, new_end])
        intersection = extended_line.intersection(perceel_poly)
        
        if intersection:
            # add points from the lines to new_perceel
            perceel_lines.append(list(intersection.coords))

    distance_a = sum((a - b) ** 2 for a, b in zip(perceel_lines[0][0], perceel_lines[1][0])) ** 0.5
    distance_b = sum((a - b) ** 2 for a, b in zip(perceel_lines[0][1], perceel_lines[1][0])) ** 0.5
    if distance_a > distance_b:
        combined_coord = perceel_lines[0] + perceel_lines[1]
    else:
        combined_coord = perceel_lines[0] + perceel_lines[1][::-1]

    if combined_coord[0] != combined_coord[-1]:
        # Make sure loop is closed
        combined_coord.append(combined_coord[0])

    polygon = Polygon(combined_coord)
    new_perceel = gpd.GeoSeries([polygon])
    return new_perceel, polygon

def check_houses_aligned(gdf, line_length:int = 300):
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

def create_perceel_border(matches, perceel_poly):
    """Create a wall for corner house

    Args:
        matches (_type_): _description_
        perceel_poly (_type_): _description_

    Returns:
        _type_: _description_
    """
    perceel_lines = []

    # Directly access the single item in matches
    key, values = next(iter(matches.items()))
    start, end = values[0], values[1]

    direction = ((end.x - start.x), (end.y - start.y))

    # Normalize the direction vector
    length = (direction[0] ** 2 + direction[1] ** 2) ** 0.5
    unit_direction = (direction[0] / length, direction[1] / length)

    extension_length = 38
    new_start = Point(start.x - unit_direction[0] * extension_length, start.y - unit_direction[1] * extension_length)
    new_end = Point(end.x + unit_direction[0] * extension_length, end.y + unit_direction[1] * extension_length)

    extended_line = LineString([new_start, new_end])
    intersection = extended_line.intersection(perceel_poly)
    if intersection:
        perceel_lines.append(LineString(list(intersection.coords)))

    return perceel_lines

def get_corner_house_perceel(lol, house, perceel_poly):
    """ This function uses a perceel, border and house to create a perceel for a single corner house.
    It splits the perceel in 2 parts and check which has the most overlap.

    Returns:
        _type_: _description_
    """

    # Snap the LineString to the Polygon boundary for precision
    tolerance = 1e-2
    snapped_linestring = snap(lol, perceel_poly, tolerance)

    # Extend the LineString to ensure it spans the Polygon
    start, end = snapped_linestring.coords[0], snapped_linestring.coords[-1]
    extended_line = LineString([
        (start[0] - 10 * (end[0] - start[0]), start[1] - 10 * (end[1] - start[1])),
        (end[0] + 10 * (end[0] - start[0]), end[1] + 10 * (end[1] - start[1]))
    ])

    # Perform the split using the extended LineString
    split_result = split(perceel_poly, extended_line)

    # Extract resulting polygons
    split_polygons = [geom for geom in split_result.geoms if isinstance(geom, Polygon)]

    # Extract the resulting polygons
    polygon1, polygon2 = split_polygons

    # Check for each poly area, which one contains the most of the house.
    # Take whatever is highest.
    intersection1 = polygon1.intersection(house["geometry"])
    intersection_with_house1 = intersection1.area.sum()

    intersection2 = polygon2.intersection(house["geometry"])
    intersection_with_house2 = intersection2.area.sum()

    if intersection_with_house1 > intersection_with_house2:
        new_poly = polygon1
    else:
        new_poly = polygon2
    return new_poly

def one_row_houses(houses):
    """ This function checks how many corner houses the plot contains.
    If more than 2, return false, because not all houses are connected.
    It does this by counting the amount of houses that share a wall wioth another house

    Args:
        houses (_type_): _description_
    """

    corner_house_count = 0

    for z, row in houses.iterrows():
        matches = perceel_borders(houses, row)
        if len(matches.keys()) <= 1:
            corner_house_count += 1
    if corner_house_count == 2:
        return True
    return False

#TODO: normalize the vectors?6
def find_parallel_edge(house: Polygon, lol: LineString, tolerance: int = 6):
    """This function is used to check if a line in a house is parallel to line lol

    Args:
        house (_type_): _description_
        lol (_type_): _description_
        tolerance (_type_, optional): _description_. Defaults to 1e-4.

    Raises:
        ValueError: _description_

    Returns:
        _type_: _description_
    """
    # Ensure lol is a LineString
    if not isinstance(lol, LineString):
        raise ValueError("lol must be a LineString")
    
    # Get the direction vector of lol
    lol = truncate_coordinates(lol)
    lol_coords = list(lol.coords)
    lol_vector = (lol_coords[-1][0] - lol_coords[0][0], lol_coords[-1][1] - lol_coords[0][1])
    cross_product2 = []
    for polygon in house.geometry:
        if isinstance(polygon, Polygon):
            # Get the exterior coordinates of the polygon
            exterior_coords = list(polygon.exterior.coords)
            
            # Iterate through the edges of the polygon
            for i in range(len(exterior_coords) - 1):
                edge = LineString([exterior_coords[i], exterior_coords[i + 1]])
                edge2 = truncate_coordinates(edge)
                edge_coords = list(edge2.coords)
                edge_vector = (edge_coords[-1][0] - edge_coords[0][0], edge_coords[-1][1] - edge_coords[0][1])
                # Check if the direction vectors are parallel (cross product is zero)
                cross_product = abs(abs(lol_vector[0] * edge_vector[1]) - abs(lol_vector[1] * edge_vector[0]))
                if cross_product < tolerance:
                    cross_product2.append(edge)
    
    return cross_product2

def find_furthest_wall(parallel_house_lines, perceel_border):
    """Compare the distance between a single line and parallel lines.
        We return the line with the greatest distance.

    Args:
        parallel_house_lines (_type_): _description_
        perceel_border (_type_): _description_

    Returns:
        _type_: _description_
    """
    furthest_points = (None, None)
    max_length = 0
    max_line = ""
    for line in parallel_house_lines:
        p1, p2 = nearest_points(perceel_border, line)
        dx = p2.x - p1.x
        dy = p2.y - p1.y
        length = math.sqrt(dx**2 + dy**2)
        if length > max_length:
            furthest_points = (p1, p2)
            max_length = length
            max_line = line

    return max_line

def create_perceel_from_parellel_lines(p1, p2, dx, dy, length, perceel_border):
    """We create a polygon (rectangle) from:
            - from a point, direction, length
            - line
        This is used to created a naive perceel for a corner house.

    Args:
        p1 (_type_): _description_
        p2 (_type_): _description_
        dx (_type_): _description_
        dy (_type_): _description_
        length (_type_): _description_
        perceel_border (_type_): _description_

    Returns:
        _type_: _description_
    """
    # Normalize the direction vector
    length = math.sqrt(dx**2 + dy**2)

    dx /= length
    dy /= length
    # Define the length of the perpendicular line (distance between p1 and p2)
    perpendicular_length = p1.distance(p2)

    # Get the coordinates of lol
    lol_coords = list(perceel_border.coords)

    # Calculate the opposite corners of the rectangle using the direction and distance
    corner1 = lol_coords[0]
    corner2 = (lol_coords[0][0] + dx * perpendicular_length, lol_coords[0][1] + dy * perpendicular_length)
    corner3 = (lol_coords[-1][0] + dx * perpendicular_length, lol_coords[-1][1] + dy * perpendicular_length)
    corner4 = lol_coords[-1]

    return Polygon([corner1, corner2, corner3, corner4])

def calc_areas(gdf_weg, perceel, house, storage_size):
    """
        Calculate the garden size based on perceel, house and roads.
    """ 
    perceel_gdf = gpd.GeoDataFrame(geometry=[perceel], crs=gdf_weg.crs)
    assert gdf_weg.crs == perceel_gdf.crs, "CRS mismatch detected!"

    gdf_weg_dissolved = gdf_weg.dissolve()
    #intersection = gdf_weg_dissolved.intersection(perceel_gdf.unary_union)
    intersection = gdf_weg_dissolved.intersection(perceel_gdf.union_all())

    intersection_perceel_weg = intersection.area.sum()
    house_size = house.area.values[0]
    garden_size = perceel.area - (intersection_perceel_weg + house_size + storage_size)
    #print("perceel", perceel.area, "housesize", house_size, "weg size", gdf_weg["geometry"].area.sum(), "intersectionsize", intersection_perceel_weg)
    #if garden_size < ((perceel_size - house_size) / 2):
    #    garden_size = (perceel_size - house_size) * 0.8
    #print(garden_size)
    return garden_size

def visualise_house_perceel(perceel, house_perceel, houses, weg, storage):
    house_perceel = gpd.GeoDataFrame(geometry=[house_perceel])
    ax = perceel.plot(color='blue', edgecolor='black')
    house_perceel.plot(ax=ax, color="yellow")
    houses.plot(ax=ax, color='red', edgecolor='black')
    weg.plot(ax=ax, color="green")
    storage.plot(ax=ax, color="pink")
    plt.show()
    return None

def find_berging(house_perceel, all_buildings) -> tuple:
    buildings_in_perceel = all_buildings[all_buildings.geometry.intersects(house_perceel)]
    storage_in_perceel = buildings_in_perceel[buildings_in_perceel["geometry"].type == 'MultiPolygon']
    storage_in_perceel["overlap"] = 0.0
    for i, row in storage_in_perceel.iterrows():
        temp_storage_gdf = gpd.GeoDataFrame(geometry=[row["geometry"]])
        intersection = house_perceel.intersection(temp_storage_gdf)
        storage_in_perceel.loc[i, "overlap"] = float(intersection.area.sum())
    
    # Check if we have an empty perceel:
    if storage_in_perceel.shape[0] == 0.0:
        # FIX THIS
        print("its emptyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy")
        storage_size = 0.0
    else:
        storage_in_perceel = gpd.GeoDataFrame([storage_in_perceel.loc[storage_in_perceel['overlap'].idxmax()]])
        storage_size = storage_in_perceel["overlap"].values[0]
    
    return storage_in_perceel, storage_size

if __name__ == "__main__": 

    # TOOD: SHOULD BE ABLE TO ITERATE OVER THE PERCEELS IN EENHEID PERCEEEl
    loc_bag = r"C:\Users\t.ars\Downloads\bag-light.gpkg"
    loc_kadaster = r'C:\Werkruimte\Projecten\working on\TUINEN/data2/kadastralekaart_kadastralegrens.gml'
    loc_wegdeel = r"C:\Werkruimte\Projecten\working on\TUINEN\data_pok2\bgt_wegdeel.gml"
    loc_pand = r"C:\Werkruimte\Projecten\working on\TUINEN\data_pok2\bgt_pand.gml"
    bbox1 = (37283.00, 378500.00, 73000.00, 396797.00)
    layers = fiona.listlayers(loc_bag)
    print("Available layers:", layers)
    gdf2 = gpd.read_file(loc_bag, bbox=bbox1, layer = "pand")
    gdf = gpd.read_file(loc_kadaster, bbox=bbox1)
    gdf_weg = gpd.read_file(loc_wegdeel, bbox=bbox1)
    gdf_bgt_pand = gpd.read_file(loc_pand, bbox=bbox1)
    
    df_eenheid_perceel = pd.read_excel("output_data/LALA_alleen_unieke.xlsx", dtype={"Pand Id": str})
    df_eenheid_nieuw = pd.read_excel("output_data/LALA_alleen_unieke.xlsx", dtype={"Pand Id": str})
    df_eenheid_nieuw["nieuw tuin opp"] = 0.0
    df_eenheid_perceel_filtered = df_eenheid_perceel.dropna(subset=["Perceelnummer"])

    print(len(df_eenheid_perceel_filtered["Perceelnummer"].unique()))

    numbers_list = [
        1200143470000,
        1260036470000,
        1230307870000,
        1220268770000,
        1160367670000
    ]

    for i in df_eenheid_perceel_filtered["Perceelnummer"].unique():
        if i in numbers_list:
            print(i)
            df_eenheid_perceel_filtered_temp = df_eenheid_perceel_filtered[df_eenheid_perceel_filtered["Perceelnummer"] == i]
            gdf_temp = gdf[(gdf["perceelLinks"] == i) | (gdf["perceelRechts"] == i)]
            gdf2_temp = gdf2[gdf2["identificatie"].isin(df_eenheid_perceel_filtered_temp["Pand Id"])]
            
            #TODO: catch error in polygon
            try:
                perceel_poly = Polygon(create_one_big_polygon(gdf_temp["geometry"]))
            except:
                continue

            # Perceel contains more than one eenheid
            if df_eenheid_perceel_filtered_temp.shape[0] > 1:
                # Somehow detect if it is a clean perceel or not. Houses only in 1 line. (can prob test this)
                # Need to detect if they are clean.
                aligned, line = check_houses_aligned(gdf2_temp)

                if not aligned:

                    ax = gdf_temp.plot(color='blue', edgecolor='black')
                    gdf2_temp.plot(ax=ax, color='red', edgecolor='black')
                    gdf_weg_temp = gdf_weg[gdf_weg.intersects(gdf_temp.union_all())]
                    gdf_bgt_pand_within = gdf_bgt_pand[gdf_bgt_pand.geometry.within(perceel_poly)]
                    gdf_bgt_pand_within.plot(ax=ax, color="pink")
                    plt.show()

                    print("whidhdihdih")
                    # process not aligned houses

#df_eenheid_nieuw.to_excel("garden_size_without_overlap_safety_4.xlsx")