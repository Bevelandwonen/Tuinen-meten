import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
import argparse
from shapely.geometry import Point
from shapely.geometry.polygon import Polygon
from shapely.geometry import LineString
from sympy import Point
from PIL import Image
import utility

""" 
    Gebruik dit script om handmatig de tuinen in te meten.
"""

def update_plot(ax, points):
    """Update plot with current points and lines."""
    ax.cla()  # Clear previous points
    # Redraw base layers
    gdf_perceel.plot(ax=ax, color='blue', edgecolor='black')
    gdf_bag_temp.plot(ax=ax, color='red', edgecolor='black')
    house.plot(ax=ax, color='yellow', edgecolor='black')
    gdf_weg_temp.plot(ax=ax, color="green")
    gdf_bgt_pand_within.plot(ax=ax, color="pink")
    
    # Draw points and lines
    if points:
        x_coords, y_coords = zip(*[(p.x, p.y) for p in points])
        ax.plot(x_coords, y_coords, 'go-', label="Garden Border")
    ax.set_title("Press 'a' to add a point, 'z' to remove the last point")
    ax.legend()
    plt.draw()

def key_press_handler(event, ax, points):
    """Handle keyboard events for point manipulation."""
    if event.key == 'a':
        if event.xdata is not None and event.ydata is not None:
            points.append(Point(event.xdata, event.ydata))
            print(f"Added point at: ({event.xdata:.2f}, {event.ydata:.2f})")
            update_plot(ax, points)
    elif event.key == 'z' and points:
        removed = points.pop()
        print(f"Removed last point at: ({removed.x:.2f}, {removed.y:.2f})")
        update_plot(ax, points)

if __name__ == "__main__": 

    parser = argparse.ArgumentParser(description='Process garden data with optional custom bounding box')
    parser.add_argument('--custom-bbox', action='store_true', help='Use custom bounding box instead of full dataset')
    parser.add_argument('--bag-path', help='Path to BAG dataset')
    parser.add_argument('--kadaster-path', help='Path to kadaster dataset')
    parser.add_argument('--tobias-path', help='Path to Tobias Excel file')
    parser.add_argument('--road-path', help='Path to road dataset')
    parser.add_argument('--pand-path', help='Path to pand dataset')
    parser.add_argument('--perceel-eenheid-path', help='Path to perceel-eenheid dataset')
    args = parser.parse_args()

    config = utility.Config.default_config("set_garden_manual")
    bbox = None

    if args.custom_bbox:
        print("Using custom bounding box...")
        bbox = utility.get_bbox_input()
        print(f"Using bbox: {bbox}")
    else:
        print("Processing full dataset...")

    gdf_bag, gdf_kad, _, gdf_road, gdf_bgt_pand, _, df_eenheid_nieuw, _, _ = utility.load_data(config, bbox)
    df_eenheid_perceel_filtered = df_eenheid_nieuw.dropna(subset=["Perceelnummer"])

    for perceelnummer in df_eenheid_perceel_filtered["Perceelnummer"].unique():
        df_perceel_eenheden = df_eenheid_perceel_filtered[df_eenheid_perceel_filtered["Perceelnummer"] == perceelnummer]
        df_perceel_eenheden.reset_index(drop=True, inplace=True)
        gdf_perceel = gdf_kad[(gdf_kad["perceelLinks"] == perceelnummer) | (gdf_kad["perceelRechts"] == perceelnummer)]
        gdf_bag_temp = gdf_bag[gdf_bag["identificatie"].isin(df_perceel_eenheden["Pand Id"])]

        try:
            perceel_poly = Polygon(utility.create_perceel_polygon(gdf_perceel["geometry"]))
        except Exception:
            continue

        if df_perceel_eenheden.shape[0] > 1:
            aligned, line = utility.check_houses_aligned(gdf_bag_temp)

            print("perceel nummer:", perceelnummer)

            for _, row in gdf_bag_temp.iterrows():
                check_temp = df_eenheid_nieuw[df_eenheid_nieuw["Pand Id"] == row["identificatie"]]
                # Only check houses that have not been processed yet 
                #if check_temp["nieuw tuin opp"].values[0] == 0.0 and check_temp["oude tuin data"].values[0] == 0.0:

                if check_temp["class"].values[0] == "errors":
                    print(check_temp["BAG Naamgeving object"])
                    print(check_temp["class"], check_temp["nieuw tuin opp"])
                    house = gdf_bag_temp[gdf_bag_temp["identificatie"] == row["identificatie"]]
                    ax = gdf_perceel.plot(color='blue', edgecolor='black')
                    gdf_bag_temp.plot(ax=ax, color='red', edgecolor='black')
                    house.plot(ax=ax, color='yellow', edgecolor='black')
                    gdf_weg_temp = gdf_road[gdf_road.intersects(gdf_bag_temp.union_all())]
                    gdf_weg_temp.plot(ax=ax, color="green")
                    gdf_bgt_pand_within = gdf_bgt_pand[gdf_bgt_pand.geometry.within(perceel_poly)]
                    gdf_bgt_pand_within.plot(ax=ax, color="pink")

                    points = []

                    fig = ax.get_figure()
                    fig.canvas.mpl_connect('key_press_event', lambda event: key_press_handler(event, ax, points))
                    ax.set_title("Press 'a' to add a point, 'z' to remove the last point")
                    ax.legend()
                    plt.show()
                    
                    # Create new small perceel
                    if len(points) != 0:
                        points.append(points[0])
                        new_poly = Polygon(points)
                        
                        gdf_weg_temp = gdf_road[gdf_road.intersects(gdf_perceel.union_all())]
                        storage, storage_size = utility.find_berging(new_poly, gdf_bgt_pand)
                        garden_size = utility.calc_areas(gdf_weg_temp, new_poly, house, storage_size)
                    else:
                        # Ask the user for the first value
                        garden_size = float(input("Please enter garden: "))

                        # Ask the user for the second value
                        storage_size = float(input("Please enter storage: "))

                    df_eenheid_nieuw.loc[df_eenheid_nieuw["Pand Id"] == row["identificatie"], ['storage', 'nieuw tuin opp']] = [storage_size, garden_size]
                    print(f"Storage size: {storage_size}, Garden size: {garden_size}")

                    df_eenheid_nieuw.to_excel("data/open_manual/final.xlsx")


