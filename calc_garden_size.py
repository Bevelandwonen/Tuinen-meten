# Suppress all warnings first
from dataclasses import dataclass
import warnings
warnings.filterwarnings('ignore')

# Suppress specific Fiona/OGR warnings
import os
os.environ['GDAL_VERSION'] = '3.0.0'

# More specific warning filters
warnings.filterwarnings('ignore', category=UserWarning)
warnings.filterwarnings('ignore', category=RuntimeWarning)
warnings.filterwarnings('ignore', message='.*OGR.*')
warnings.filterwarnings('ignore', message='.*Shapely.*')
warnings.filterwarnings('ignore', message='.*Skipping field.*')
# ...existing imports and code...

import argparse
import pandas as pd
import utility
from datatypes import DataBundle
from processors.open import open_parcel
from processors.multiple_aligned import multiple_aligned
from processors.single import single_house
from processors.utils import check_perceel_type

if __name__ == "__main__": 

    # Clean this mess
    parser = argparse.ArgumentParser(description='Process garden data with optional custom bounding box')
    parser.add_argument('--custom-bbox', action='store_true', help='Use custom bounding box instead of full dataset')
    parser.add_argument('--bag-path', help='Path to BAG dataset')
    parser.add_argument('--kadaster-path', help='Path to kadaster dataset')
    parser.add_argument('--tobias-path', help='Path to Tobias Excel file')
    parser.add_argument('--road-path', help='Path to road dataset')
    parser.add_argument('--pand-path', help='Path to pand dataset')
    parser.add_argument('--perceel-eenheid-path', help='Path to perceel-eenheid dataset')
    args = parser.parse_args()

    config = utility.Config.default_config("calc_garden_size")
    bbox = None

    if args.custom_bbox:
        print("Using custom bounding box...")
        bbox = utility.get_bbox_input()
        print(f"Using bbox: {bbox}")
    else:
        print("Processing full dataset...")


    #TODO: maybe start here with the data class
    data = utility.load_data(config, bbox)


    ############## CHECK OF PERCEEL MATCHES ER AL ZIJN ##############
    # anders voer dit uit
    ##############################################################################

    #create a function here
    # check if data.df_units has a column "Perceelnummer" with non-null values
    if "Perceelnummer" in data.df_units.columns and data.df_units["Perceelnummer"].notna().any():
        print("Found existing perceel matches, skipping matching step.")
    else:
        print("No existing perceel matches found, running matching step.")

        perceel_nummers = list(set(data.gdf_kad["perceelLinks"].tolist() + data.gdf_kad["perceelRechts"].tolist()))
        print(f"Processing {len(perceel_nummers)} perceel numbers")

        # Check if an output file already exists if it does, check perceel_nummers already found
        if "Perceelnummer" in data.df_units.columns:
            perceel_nummers = [perceel for perceel in perceel_nummers if perceel not in data.df_units["Perceelnummer"].unique()]
            print(f"Found {len(perceel_nummers)} new perceel numbers to process")

        df_tobias = find_perceel_nummer_per_eenheid(df_tobias, gdf_kad, gdf_bag, perceel_nummers)

        #find path to this script
        output_file = os.path.join(os.path.dirname(__file__), "data", "output", f"ids_with_parcel.xlsx")
        
        df_tobias.to_excel(output_file)
        #update data.df_units with the new matches
        data.df_units = data.df_units.merge(df_tobias[["Pand ID", "Perceelnummer"]], left_on="Pand Id", right_on="Pand ID", how="left").drop(columns=["Pand ID"])   
        #we also want to write these new results to disk so we can use them in a new run without having to redo the matching step
        #maybe should create a function in data loader for saving and reloading the units with matches
        data.df_units.to_excel(os.path.join(os.path.dirname(__file__), "data", "output", f"units_with_parcel.xlsx"), index=False)






    ################################# Begin met berekenen tuinoppervlakte #################################

    #maybe use .copy()
    df_units_new = data.df_units

    df_units_filtered = df_units_new.dropna(subset=["Perceelnummer"])

    all_results = []

    # we gaan elk perceel langs
    for plotnumber in df_units_filtered["Perceelnummer"].unique():
        #de eenheden in het perceel
        df_units_in_plot = df_units_filtered[df_units_filtered["Perceelnummer"] == plotnumber]
        # verzameling van de lijnen van het perceel
        gdf_plot = data.gdf_kad[(data.gdf_kad["perceelLinks"] == plotnumber) | (data.gdf_kad["perceelRechts"] == plotnumber)]
        # verzameling van de huizen in het perceel
        gdf_bag_temp = data.gdf_bag[data.gdf_bag["identificatie"].isin(df_units_in_plot["Pand Id"])]
        gdf_road_temp = data.gdf_road[data.gdf_road.intersects(gdf_bag_temp.union_all())]

        try:
            # maken een heel perceel van de lijnen van het perceel
            plot_poly = utility.create_perceel_polygon(gdf_plot["geometry"])
        except Exception:
            continue
            
        parcel_type = check_perceel_type(df_units_in_plot, gdf_bag_temp)
        #TODO: Catch results
        if parcel_type == "single":
            single_house(data, plot_poly, gdf_bag_temp, gdf_plot, gdf_road_temp)
            #all_results.extend(processors.single_house(data, plot_poly, gdf_bag_temp, gdf_plot))
        elif parcel_type == "multiple_aligned":
            multiple_aligned(data, plot_poly, gdf_bag_temp, gdf_plot, gdf_road_temp)
        else:
            open_parcel(data, gdf_bag_temp, plot_poly, gdf_plot, gdf_road_temp)

    #df_results = df_results.set_index("Pand Id")
    #df_final = df_eenheid_perceel.set_index("Pand Id")


    #df_eenheid_nieuw.to_excel("garden_size_without_overlap_safety_4.xlsx")
    #error.to_excel("errors_calc_garden_size.xlsx")