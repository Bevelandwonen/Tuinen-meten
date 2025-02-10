import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
from shapely.geometry import Point
from shapely.geometry.polygon import Polygon
from shapely.geometry import LineString
import numpy as np
from sympy import Point
import fiona
from PIL import Image


""" 
    Gebruik dit script om handmatig de tuinen in te meten.
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
                #  TODO: Maybe check % overlap

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

def calc_areas(gdf_weg, perceel, house, storage_size):
    """
        Calculate the garden size based on perceel, house and roads.
    """ 
    perceel_gdf = gpd.GeoDataFrame(geometry=[perceel], crs=gdf_weg.crs)
    assert gdf_weg.crs == perceel_gdf.crs, "CRS mismatch detected!"

    gdf_weg_dissolved = gdf_weg.dissolve()
    intersection = gdf_weg_dissolved.intersection(perceel_gdf.union_all())

    intersection_perceel_weg = intersection.area.sum()
    house_size = house.area.values[0]
    garden_size = perceel.area - (intersection_perceel_weg + house_size + storage_size)
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
    gdf2 = gpd.read_file(loc_bag, bbox=bbox1, layer = "pand")
    gdf = gpd.read_file(loc_kadaster, bbox=bbox1)
    gdf_weg = gpd.read_file(loc_wegdeel, bbox=bbox1)
    gdf_bgt_pand = gpd.read_file(loc_pand, bbox=bbox1)
    
    df_eenheid_perceel = pd.read_excel("garden_size_for_non_aligned_final.xlsx", dtype={"Pand Id": str})
    df_eenheid_nieuw = pd.read_excel("garden_size_for_non_aligned_final.xlsx", dtype={"Pand Id": str})
    df_eenheid_perceel_filtered = df_eenheid_perceel.dropna(subset=["Perceelnummer"])

    for i in df_eenheid_perceel_filtered["Perceelnummer"].unique():
        df_eenheid_perceel_filtered_temp = df_eenheid_perceel_filtered[df_eenheid_perceel_filtered["Perceelnummer"] == i]
        gdf_temp = gdf[(gdf["perceelLinks"] == i) | (gdf["perceelRechts"] == i)]
        gdf2_temp = gdf2[gdf2["identificatie"].isin(df_eenheid_perceel_filtered_temp["Pand Id"])]
        
        try:
            perceel_poly = Polygon(create_one_big_polygon(gdf_temp["geometry"]))
        except:
            continue

        if df_eenheid_perceel_filtered_temp.shape[0] > 1:
            aligned, line = check_houses_aligned(gdf2_temp)

            if not aligned:
                print("perceel nummer:", i)
                for z, row in gdf2_temp.iterrows():
                    check_temp = df_eenheid_nieuw[df_eenheid_nieuw["Pand Id"] == row["identificatie"]]
                    if check_temp["nieuw tuin opp"].values[0] == 0.0 and check_temp["oude tuin data"].values[0] == 0.0:
                        house = gdf2_temp[gdf2_temp["identificatie"] == row["identificatie"]]
                        ax = gdf_temp.plot(color='blue', edgecolor='black')
                        gdf2_temp.plot(ax=ax, color='red', edgecolor='black')
                        house.plot(ax=ax, color='yellow', edgecolor='black')
                        gdf_weg_temp = gdf_weg[gdf_weg.intersects(gdf_temp.union_all())]
                        gdf_bgt_pand_within = gdf_bgt_pand[gdf_bgt_pand.geometry.within(perceel_poly)]
                        gdf_bgt_pand_within.plot(ax=ax, color="pink")

                        points = []

                        point_scatter, = ax.plot([], [], 'go', label="Interactive Points")  # Green dots
                        line_plot, = ax.plot([], [], 'g-', label="Connecting Lines")         # Green solid line

                        def update_plot():
                            """Update the plot with the current points and lines."""
                            if points:
                                x_coords, y_coords = zip(*[(p.x, p.y) for p in points])
                                point_scatter.set_data(x_coords, y_coords)
                                if len(points) > 1:
                                    line = LineString(points)
                                    x_line, y_line = line.xy
                                    line_plot.set_data(x_line, y_line)
                                else:
                                    line_plot.set_data([], [])
                            else:
                                point_scatter.set_data([], [])
                                line_plot.set_data([], [])

                            plt.draw()

                        def onclick(event):
                            """Handle key press events to add/remove points interactively."""
                            if event.xdata is None or event.ydata is None:
                                return  # Ignore clicks outside the plot

                            if event.key == "a":
                                point = Point(event.xdata, event.ydata)
                                points.append(point)
                                print(f"Point drawn at: {point}")
                                update_plot()

                            elif event.key == "z" and points:
                                removed_point = points.pop()
                                print(f"Point removed: {removed_point}")
                                update_plot()

                        # Connect the key press event to the function
                        fig = ax.get_figure()
                        fig.canvas.mpl_connect('key_press_event', onclick)

                        # Add a title and legend for clarity
                        ax.set_title("Press 'a' to add a point, 'z' to remove the last point")
                        ax.legend()

                        plt.show()
                        
                        # Create new small perceel
                        points.append(points[0])
                        new_poly = Polygon(points)
                        
                        gdf_weg_temp = gdf_weg[gdf_weg.intersects(gdf_temp.union_all())]
                        storage, storage_size = find_berging(new_poly, gdf_bgt_pand)
                        garden_size = calc_areas(gdf_weg_temp, new_poly, house, storage_size)

                        df_eenheid_nieuw.loc[df_eenheid_nieuw["Pand Id"] == row["identificatie"], 'nieuw tuin opp'] = garden_size
                        df_eenheid_nieuw.loc[df_eenheid_nieuw["Pand Id"] == row["identificatie"], 'storage'] = storage_size
                        visualise_house_perceel(gdf_temp, new_poly, gdf2_temp, gdf_weg_temp, storage)
                        print(f"Storage size: {storage_size}, Garden size: {garden_size}")

                        df_eenheid_nieuw.to_excel("garden_size_for_non_aligned_final.xlsx")