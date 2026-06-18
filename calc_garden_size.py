# Suppress all warnings first
from dataclasses import dataclass
import warnings
import argparse
import pandas as pd
import utility
from processors.open import open_plot
from processors.multiple_aligned import multiple_aligned
from processors.single import single_house
from utility import check_plot_type
from utility import PlotType
import os
warnings.filterwarnings('ignore')

os.environ['GDAL_VERSION'] = '3.0.0'
warnings.filterwarnings('ignore', category=UserWarning)
warnings.filterwarnings('ignore', category=RuntimeWarning)
warnings.filterwarnings('ignore', message='.*OGR.*')
warnings.filterwarnings('ignore', message='.*Shapely.*')
warnings.filterwarnings('ignore', message='.*Skipping field.*')

PLOT_NUMBER = "Perceelnummer"
PLOT_NUMBER_LEFT = "perceelLinks"
PLOT_NUMBER_RIGHT = "perceelRechts"
IDENTIFICATIE = "identificatie"
BUILDING_ID = "Pand Id"

if __name__ == "__main__": 

    #TODO: add new config options after restructuring

    config = utility.Config.default_config("calc_garden_size")
    bbox = None

    data = utility.load_data(config, bbox)

    if PLOT_NUMBER in data.df_units.columns and data.df_units[PLOT_NUMBER].notna().any():
        print("Found existing plot matches, skipping matching step.")
    else:
        print("No existing plot matches found, running matching step.")

        plot_id = (
            pd.concat([
                data.gdf_kad[PLOT_NUMBER_LEFT],
                data.gdf_kad[PLOT_NUMBER_RIGHT],
            ])
            .dropna()
            .unique()
            .tolist()
        )

        print(f"Found {len(plot_id)} new plot numbers to process")
    
        df_units_plot_matches = utility.find_plot_id_per_unit(data.df_units, 
                                                              data.gdf_kad, 
                                                              data.gdf_bag, 
                                                              plot_id)

        data.df_units = df_units_plot_matches   
        data.df_units.to_excel(r"data/bag_ids/bag_ids.xlsx", index=False)

    # Calculate garden size 
    # We remove buidings without a unique building_id, these are flats.
    df_units_unique_building = data.df_units[data.df_units[BUILDING_ID].duplicated(keep=False)]
    df_units_filtered = df_units_unique_building.dropna(subset=[PLOT_NUMBER])

    all_results = []
    errors = []

    for plotnumber in df_units_filtered[PLOT_NUMBER].unique():
        print(f"Processing plot {plotnumber}")
        df_units_in_plot = df_units_filtered[df_units_filtered[PLOT_NUMBER] == plotnumber]
        gdf_plot = data.gdf_kad[(data.gdf_kad[PLOT_NUMBER_LEFT] == plotnumber) |
                                (data.gdf_kad[PLOT_NUMBER_RIGHT] == plotnumber)]
        gdf_bag_in_plot = data.gdf_bag[data.gdf_bag[IDENTIFICATIE].isin(df_units_in_plot[BUILDING_ID])]
        gdf_road_in_plot = data.gdf_road[data.gdf_road.intersects(gdf_bag_in_plot.unary_union)]
        
        #TODO: ugly code: maybe check validity of polygon if it failed continue
        try:
            plot_poly = utility.create_plot_polygon(gdf_plot["geometry"])
        except Exception as e:
            print(f"Failed to create polygon for plot {plotnumber}: {e}")
            errors.append((plotnumber, str(e)))
            continue
            
        parcel_type = check_plot_type(df_units_in_plot, gdf_bag_in_plot)
        if parcel_type == PlotType.SINGLE:
            result = single_house(data, plot_poly, gdf_bag_in_plot, gdf_road_in_plot)
        elif parcel_type == PlotType.MULTIPLE_ALIGNED:
            result = multiple_aligned(data, plot_poly, gdf_bag_in_plot, gdf_plot, gdf_road_in_plot)
        else:
            result = open_plot(data, plot_poly, gdf_bag_in_plot, gdf_plot, gdf_road_in_plot)

        all_results.extend(result)
    
    df_results = pd.DataFrame([r.__dict__ for r in all_results])
    df_results.rename(columns={"pand_id": BUILDING_ID}, inplace=True)
    df_units_results = pd.merge(data.df_units, df_results, left_on=BUILDING_ID, right_on=BUILDING_ID, how="left")
    
    for plotnumber, error in errors:
        df_units_results.loc[df_units_results[PLOT_NUMBER] == plotnumber,
                             "class"] = f"error in plot polygon creation: {error}"

    df_units_results.loc[data.df_units[BUILDING_ID].duplicated(keep=False),
                         "class"] = "non unique building_id, prob flat"
    
    #TODO: ADD OUTLIER CHECK PER PARCEL

    df_units_results.to_excel("garden_size_nieuw_eerste_run.xlsx")