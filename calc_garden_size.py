# Suppress all warnings first
from dataclasses import dataclass
import warnings
import argparse
import pandas as pd
import utility
from processors.open import open_plot
from processors.multiple_aligned import multiple_aligned
from processors.single import single_house
from processors.utils import check_plot_type
import os
warnings.filterwarnings('ignore')

os.environ['GDAL_VERSION'] = '3.0.0'
warnings.filterwarnings('ignore', category=UserWarning)
warnings.filterwarnings('ignore', category=RuntimeWarning)
warnings.filterwarnings('ignore', message='.*OGR.*')
warnings.filterwarnings('ignore', message='.*Shapely.*')
warnings.filterwarnings('ignore', message='.*Skipping field.*')

if __name__ == "__main__": 

    #TODO: add new config options after restructuring

    config = utility.Config.default_config("calc_garden_size")
    bbox = None

    data = utility.load_data(config, bbox)

    ############## CHECK OF plot MATCHES ER AL ZIJN ##############
    if "Perceelnummer" in data.df_units.columns and data.df_units["Perceelnummer"].notna().any():
        print("Found existing plot matches, skipping matching step.")
    else:
        print("No existing plot matches found, running matching step.")

        plot_id = list(set(data.gdf_kad["perceelLinks"].tolist() + data.gdf_kad["perceelRechts"].tolist()))
        print(f"Processing {len(plot_id)} plot numbers")

        # Check if an output file already exists if it does, check plot_nummers already found
        if "Perceelnummer" in data.df_units.columns:
            plot_id = (
                pd.concat([
                    data.gdf_kad["perceelLinks"],
                    data.gdf_kad["perceelRechts"],
                ])
                .dropna()
                .unique()
                .tolist()
            )
            print(f"Found {len(plot_id)} new plot numbers to process")
        #print(plot_id)
        #plot_id = [4280515670000, 4280606570000]
        # and perceel: 4280606570000
        df_units_plot_matches = utility.find_plot_id_per_unit(data.df_units, 
                                                                       data.gdf_kad, 
                                                                       data.gdf_bag, 
                                                                       plot_id)

        data.df_units = df_units_plot_matches   
        data.df_units.to_excel(r"data/bag_ids/bag_ids.xlsx", index=False)
        
    ################################# Begin met berekenen tuinoppervlakte #################################

    # we only want buidings with a unique pand_id, we remove all rows without a unique pand_id
    df_units_unique_pand = data.df_units[data.df_units["Pand Id"].duplicated(keep=False) == False]
    df_units_filtered = df_units_unique_pand.dropna(subset=["Perceelnummer"])
    # we do this to filter out flats etc.

    all_results = []

    # we gaan elk plot langs
    for plotnumber in df_units_filtered["Perceelnummer"].unique():
        print("weee")
        #de eenheden in het plot
        df_units_in_plot = df_units_filtered[df_units_filtered["Perceelnummer"] == plotnumber]
        # verzameling van de lijnen van het plot
        gdf_plot = data.gdf_kad[(data.gdf_kad["perceelLinks"] == plotnumber) | (data.gdf_kad["perceelRechts"] == plotnumber)]
        # verzameling van de huizen in het plot
        gdf_bag_in_plot = data.gdf_bag[data.gdf_bag["identificatie"].isin(df_units_in_plot["Pand Id"])]
        # verzameling van de wegen in het plot
        #TODO: shouldnt this be gdf_plot instead of gdf_bag_in_plot?
        gdf_road_in_plot = data.gdf_road[data.gdf_road.intersects(gdf_bag_in_plot.unary_union)]

        #why dont we just give one  geometry?
        #this because we can have multiple plots with the same number so we need to check again

        try:
            plot_poly = utility.create_plot_polygon(gdf_plot["geometry"])
        except Exception as e:
            print(f"Failed to create polygon for plot {plotnumber}: {e}")
            continue
        
        # we do this so we can check create_plot_polygon is working correctly, if not we can check the error message
        continue

        parcel_type = check_plot_type(df_units_in_plot, gdf_bag_in_plot)
        #TODO: Catch results
        print(gdf_bag_in_plot)
        if parcel_type == "single":
            result = single_house(data, plot_poly, gdf_bag_in_plot, gdf_road_in_plot)
        elif parcel_type == "multiple_aligned":
            print("multiple aligned")
            result = multiple_aligned(data, plot_poly, gdf_bag_in_plot, gdf_plot, gdf_road_in_plot)
        else:
            print("open")
            result = open_plot(data, plot_poly, gdf_bag_in_plot, gdf_plot, gdf_road_in_plot)

        all_results.extend(result)
    
    # concatenate the results with data.df_units based on pand_id
    df_results = pd.DataFrame([r.__dict__ for r in all_results])
    print(df_results.head())
    df_eenheid_nieuw = pd.merge(data.df_units, df_results, left_on="Pand Id", right_on="Pand Id", how="left")
    # For every row with a non unique pand_id set classification to "non unique pand_id, prob flat"
    df_eenheid_nieuw.loc[data.df_units["Pand Id"].duplicated(keep=False), "class"] = "non unique pand_id, prob flat"
    
    
    df_eenheid_nieuw.to_excel("garden_size_nieuw_eerste_run.xlsx")