from . import utils
import geopandas as gpd
from datatypes import DataBundle, HouseResult
from shapely.geometry.polygon import Polygon
from typing import List

def single_house(
    data: DataBundle, 
    perceel_poly: Polygon, 
    gdf_bag_in_plot: gpd.GeoDataFrame,
    gdf_road_in_plot: gpd.GeoDataFrame,
    visualise: bool = False
) -> List[HouseResult]:

    """Process a single house parcel and calculate garden size."""

    _, storage_size = utils.find_berging(
        perceel_poly, 
        data.gdf_pand,
    )

    garden_size = utils.calc_areas(
        gdf_road_in_plot, 
        perceel_poly, 
        gdf_bag_in_plot, 
        storage_size,
    )

    if visualise:
        utils.visualise_house_perceel(
            data.gdf_perceel, 
            perceel_poly, 
            gdf_bag_in_plot, 
            gdf_road_in_plot, 
            storage_size,
        )

    if gdf_bag_in_plot.empty:
        raise ValueError("No BAG object found for single house")

    return [
        HouseResult(
            pand_id=gdf_bag_in_plot.iloc[0]["identificatie"],
            storage_size=storage_size,
            garden_size=garden_size,
            classification="single",
        )
    ]
