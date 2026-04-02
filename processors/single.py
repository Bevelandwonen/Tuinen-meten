from . import utils
import geopandas as gpd
from datatypes import DataBundle
from shapely.geometry.polygon import Polygon
from typing import Dict, List

def single_house(
    data: DataBundle, 
    perceel_poly: Polygon, 
    gdf_bag_temp: gpd.GeoDataFrame,
    gdf_perceel: gpd.GeoDataFrame,
    gdf_weg_temp: gpd.GeoDataFrame
) -> List[Dict]:
    
    _, storage_size = utils.find_berging(perceel_poly, data.gdf_pand)
    garden_size = utils.calc_areas(gdf_weg_temp, perceel_poly, gdf_bag_temp, storage_size)
    #TODO: Add option to visualise
    #utils.visualise_house_perceel(gdf_perceel, perceel_poly, gdf_bag_temp, gdf_weg_temp, storage)
    pand_id = gdf_bag_temp["identificatie"].values[0]
    #TODO: what do we use as output
    return [{
        "Pand Id": pand_id,
        "storage": storage_size,
        "nieuw tuin opp": garden_size,
        "classificatie": "single"
    }]
