from typing import List

import geopandas as gpd
from shapely.geometry.polygon import Polygon

from . import utils
from datatypes import DataBundle, HouseResult

def single_house(
    data: DataBundle, 
    plot_poly: Polygon, 
    gdf_bag_in_plot: gpd.GeoDataFrame,
    gdf_road_in_plot: gpd.GeoDataFrame,
    visualise: bool = False
) -> List[HouseResult]:

    """Process a single house parcel and calculate garden size."""

    _, storage_size = utils.find_berging(
        plot_poly, 
        data.gdf_pand,
    )

    garden_size = utils.calc_areas(
        gdf_road_in_plot, 
        plot_poly, 
        gdf_bag_in_plot, 
        storage_size,
    )

    if visualise:
        utils.visualise_house_plot(
            data.gdf_plot, 
            plot_poly, 
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