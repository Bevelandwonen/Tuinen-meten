from dataclasses import dataclass
import geopandas as gpd
import pandas as pd
from typing import Optional, Tuple
from shapely.geometry.polygon import Polygon
from shapely.geometry import LineString
from datatypes import Config
from shapely.geometry import box as BoundingBox
from datatypes import DataBundle
from pathlib import Path

def _check(path: str, name: str) -> str:
    if not path:
        raise ValueError(f"{name} path is missing")
    if not Path(path).exists():
        raise FileNotFoundError(f"{name} not found: {path}")
    return path

def load_data(
    config: Config, 
    bbox: Optional[BoundingBox] = None
) -> DataBundle:
    
    print("Loading data.")
    bbox_tuple = (bbox.minx, bbox.miny, bbox.maxx, bbox.maxy) if bbox else None

    bag_path = _check(config.loc_bag, "BAG")
    kad_path = _check(config.loc_kadaster, "Kadaster")
    units_path = _check(config.loc_units, "Units")
    road_path = _check(config.loc_road, "Road")
    pand_path = _check(config.loc_pand, "Pand")

    gdf_bag = gpd.read_file(bag_path, bbox=bbox_tuple, layer="pand")
    gdf_kad = gpd.read_file(kad_path, bbox=bbox_tuple)
    df_units = pd.read_excel(units_path, dtype={"Pand Id": str})
    gdf_road = gpd.read_file(road_path, bbox=bbox_tuple)
    gdf_pand = gpd.read_file(pand_path, bbox=bbox_tuple)

    print(f"Loaded {len(gdf_bag)} BAG records")
    print(f"Loaded {len(gdf_kad)} Cadastral records")
    print(f"Loaded {len(df_units)} unit records")
    print(f"Loaded {len(gdf_road)} road records")
    print(f"Loaded {len(gdf_pand)} pand records")

    return DataBundle(
        gdf_bag=gdf_bag,
        gdf_kad=gdf_kad,
        gdf_road=gdf_road,
        gdf_pand=gdf_pand,
        df_units=df_units,
    )

def get_bbox_input() -> BoundingBox:
    """Get bounding box coordinates from user input"""
    print("\nEnter bounding box coordinates:")
    while True:
        try:
            minx = float(input("Enter minimum X coordinate: "))
            miny = float(input("Enter minimum Y coordinate: "))
            maxx = float(input("Enter maximum X coordinate: "))
            maxy = float(input("Enter maximum Y coordinate: "))
            if maxx <= minx or maxy <= miny:
                print("Maximum coordinates must be greater than minimum coordinates.")
                continue
            return BoundingBox(minx, miny, maxx, maxy)
        except ValueError:
            print("Invalid input. Please enter valid numeric coordinates.")

def create_perceel_polygon(perceel: gpd.geoseries.GeoSeries) -> Polygon:
    """Creates a single polygon from multiple lines in perceel"""
    lines = gpd.GeoSeries([LineString(line.coords) for line in perceel])
    polygons = lines.polygonize()
    big_poly = list(polygons)[0]
    return Polygon(big_poly)
