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

PLOT_NUMBER = "Perceelnummer"
PLOT_NUMBER_LEFT = "perceelLinks"
PLOT_NUMBER_RIGHT = "perceelRechts"
IDENTIFICATIE = "identificatie"
BUILDING_ID = "Pand Id"

def update_plot(ax, points):
    """Update plot with current points and lines."""
    ax.cla()  # Clear previous points
    # Redraw base layers
    gdf_plot.plot(ax=ax, color='blue', edgecolor='black')
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

    config = utility.Config.default_config("set_garden_manual")
    bbox = None

    gdf_bag, gdf_kad, _, gdf_road, gdf_bgt_pand, _, df_units, _, _ = utility.load_data(config, bbox)
    df_units_filtered = df_units.dropna(subset=[PLOT_NUMBER])

    for plotnumber in df_units_filtered[PLOT_NUMBER].unique():
        df_units_in_plot = df_units_filtered[df_units_filtered[PLOT_NUMBER] == plotnumber]
        df_units_in_plot.reset_index(drop=True, inplace=True)
        gdf_plot = gdf_kad[(gdf_kad[PLOT_NUMBER_LEFT] == plotnumber) |
                           (gdf_kad[PLOT_NUMBER_RIGHT] == plotnumber)]
        gdf_bag_temp = gdf_bag[gdf_bag[IDENTIFICATIE].isin(df_units_in_plot[BUILDING_ID])]

        try:
            plot_poly = Polygon(utility.create_plot_polygon(gdf_plot["geometry"]))
        except Exception:
            continue

        if df_units_in_plot.shape[0] > 1:
            aligned, line = utility.check_houses_aligned(gdf_bag_temp)

            print("plot nummer:", plotnumber)

            for _, row in gdf_bag_temp.iterrows():
                df_unit_to_check = df_units[df_units[BUILDING_ID] == row[IDENTIFICATIE]]
                # Only check houses that have not been processed yet 
                #if check_temp["nieuw tuin opp"].values[0] == 0.0 and check_temp["oude tuin data"].values[0] == 0.0:

                # Only check houses that have an error and thus not na or have not been processed yet
                df_unit = df_unit_to_check.iloc[0]

                if pd.isna(df_unit["nieuw tuin opp"]) or \
                           df_unit["class"] != "" or \
                           df_unit["nieuw tuin opp"] == 0.0:

                    print(df_unit_to_check["BAG Naamgeving object"])
                    print(df_unit_to_check["class"], df_unit_to_check["nieuw tuin opp"])
                    house = gdf_bag_temp[gdf_bag_temp["identificatie"] == row["identificatie"]]

                    ax = gdf_plot.plot(color='blue', edgecolor='black')
                    gdf_bag_temp.plot(ax=ax, color='red', edgecolor='black')
                    house.plot(ax=ax, color='yellow', edgecolor='black')
                    gdf_weg_temp = gdf_road[gdf_road.intersects(gdf_bag_temp.union_all())]
                    gdf_weg_temp.plot(ax=ax, color="green")
                    gdf_bgt_pand_within = gdf_bgt_pand[gdf_bgt_pand.geometry.within(plot_poly)]
                    gdf_bgt_pand_within.plot(ax=ax, color="pink")

                    points = []

                    fig = ax.get_figure()
                    fig.canvas.mpl_connect('key_press_event', lambda event: key_press_handler(event, ax, points))
                    ax.set_title("Press 'a' to add a point, 'z' to remove the last point")
                    ax.legend()
                    plt.show()
                    
                    if len(points) != 0:
                        points.append(points[0])
                        new_poly = Polygon(points)
                        
                        gdf_weg_temp = gdf_road[gdf_road.intersects(gdf_plot.union_all())]
                        storage, storage_size = utility.find_berging(new_poly, gdf_bgt_pand)
                        garden_size = utility.calc_areas(gdf_weg_temp, new_poly, house, storage_size)
                    else:
                        garden_size = float(input("Please enter garden: "))

                        storage_size = float(input("Please enter storage: "))

                    df_units.loc[df_units["Pand Id"] == row["identificatie"], ['storage', 'nieuw tuin opp']] = [storage_size, garden_size]
                    print(f"Storage size: {storage_size}, Garden size: {garden_size}")

                    df_units.to_excel("data/open_manual/final.xlsx")


