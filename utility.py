import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import geopandas as gpd
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from shapely.geometry import LineString, Polygon
from shapely.geometry import box as BoundingBox
from shapely.ops import polygonize, unary_union
from shapely.validation import make_valid

from datatypes import Config, DataBundle

warnings.filterwarnings("ignore")

from enum import Enum

class PlotType(Enum):
    SINGLE = "single"
    MULTIPLE_ALIGNED = "multiple_aligned"
    OPEN = "open"


def check_plot_type(
    df_plot_eenheden: pd.DataFrame, 
    gdf_bag_temp: gpd.GeoDataFrame
) -> PlotType:
    
    if df_plot_eenheden.shape[0] == 1:
        return PlotType.SINGLE
    #TODO: clean check_houses function. does it need the line as output
    elif check_houses_aligned(gdf_bag_temp)[0]:
        return PlotType.MULTIPLE_ALIGNED
    else:
        return PlotType.OPEN

def check_houses_aligned(
    gdf: gpd.GeoDataFrame, 
    line_length: int = 300
) -> Tuple[bool, Optional[LineString]]:
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

#TODO: adjust all naming conventions
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

def create_plot_polygon(plot: gpd.geoseries.GeoSeries) -> Polygon:
    """Creates a single polygon from multiple lines in plot"""
    lines = gpd.GeoSeries([LineString(line.coords) for line in plot])
    polygons = lines.polygonize()
    # plot the different polygons to check if they are correct
    
    if polygons.shape[0] > 1:
        polygons = sorted(polygons, key=lambda p: p.area if hasattr(p, "area") else 0, reverse=True)
    big_poly = list(polygons)[0]
    return Polygon(big_poly)

def _safe_make_valid(geom):
    if geom is None:
        return None
    try:
        return make_valid(geom)
    except Exception:
        return None

def _build_parcel_polygons_from_lines(
    gdf_kad_lines: gpd.GeoDataFrame,
    plot_nummers: Optional[List[str]] = None,
    left_col: str = "perceelLinks",
    right_col: str = "perceelRechts",
) -> gpd.GeoDataFrame:
    """
    From cadastral boundary lines (LineString), build one polygon per plot.

    Returns GeoDataFrame with:
      - 'plotnummer' (str)
      - 'borders_amount' (int)  # number of lines used
      - geometry (Polygon)
    """
    left = gdf_kad_lines[[left_col, "geometry"]].rename(columns={left_col: "Perceelnummer"})
    right = gdf_kad_lines[[right_col, "geometry"]].rename(columns={right_col: "Perceelnummer"})
    
    long = pd.concat([left, right], ignore_index=True)
    long = long.dropna(subset=["Perceelnummer"])
    #only keep the ones containing the filter_num
    if plot_nummers is not None:
        keep = set(plot_nummers)
        long = long[long["Perceelnummer"].isin(keep)]

    # Count lines per plot (for borders_amount)
    counts = long.groupby("Perceelnummer", as_index=False)["geometry"].size()
    counts = counts.rename(columns={"size": "borders_amount"})
    # Polygonize per plot
    records = []
    #TODO: improve this code add error catch
    for plot, group in long.groupby("Perceelnummer"):
        try:
            merged = unary_union(list(group.geometry.values))
            polys = list(polygonize(merged))
            if not polys:
                continue
            # pick the largest by area (most robust choice)
            poly = max(polys, key=lambda p: p.area)
            poly = _safe_make_valid(poly)
            if poly is None or poly.is_empty:
                continue
            records.append({"Perceelnummer": plot, "geometry": poly})
        except Exception:
            # skip bad groups quietly
            continue

    if not records:
        return gpd.GeoDataFrame(columns=["Perceelnummer",
                                         "borders_amount", 
                                         "geometry"], 
                                         geometry="geometry", 
                                         crs=gdf_kad_lines.crs
                                )
    
    #TODO: CHANGE PARCELS TO PLOTS
    # WE HAVE ALL LINES WITH THE SAME NUMBER and we combine them to a parcel
    parcels = gpd.GeoDataFrame(records, geometry="geometry", crs=gdf_kad_lines.crs)
    parcels = parcels.merge(counts, on="Perceelnummer", how="left")

    parcels = parcels.sort_values("geometry", key=lambda s: s.area if hasattr(s, "area") else s).drop_duplicates("Perceelnummer", keep="last")
    return parcels

#TODO: clean this function
def find_plot_id_per_unit(
    df_units: pd.DataFrame,
    gdf_kad_lines: gpd.GeoDataFrame,
    gdf_bag: gpd.GeoDataFrame,
    plot_nummers: List[str],
    out_file: Optional[str] = None,
) -> pd.DataFrame:
    """
    Fast version:
      1) build parcel polygons per plot from boundary lines,
      2) point-in-polygon join of BAG centroids to parcels,
      3) pick smallest borders_amount per BAG unit,
      4) merge back to Tobias.

    Expects:
      - df_units["Pand Id"]
      - gdf_bag["identificatie"], gdf_bag.geometry (Polygon/MultiPolygon per unit)
      - gdf_kad_lines["perceelLinks"], gdf_kad_lines["perceelRechts"], gdf_kad_lines.geometry (LineString)
    """
    # --- CRS sanity: do everything in the same projected CRS (important in NL: EPSG:28992).
    if gdf_kad_lines.crs is None or gdf_bag.crs is None:
        raise ValueError("Both gdf_kad_lines and gdf_bag must have a CRS set.")
    if gdf_kad_lines.crs != gdf_bag.crs:
        gdf_bag = gdf_bag.to_crs(gdf_kad_lines.crs)

    # --- Build parcel polygons from lines (ONLY for the plot_nummers you care about)
    parcels = _build_parcel_polygons_from_lines(gdf_kad_lines, plot_nummers)

    #for in parcels, plot the parcel and the lines that make up the parcel

    if parcels.empty:
        print("is parcels empty?")
        # nothing to match; return df unchanged
        if out_file:
            df_units.to_parquet(out_file, index=False)
        return df_units

    # Set parcels index to plotnummer so sjoin carries it via 'index_right'
    parcels = parcels.set_index("Perceelnummer", drop=True)
    # --- Prepare BAG centroids only for Tobias Pand Ids
    bag = gdf_bag[gdf_bag["identificatie"].isin(df_units["Pand Id"])][["identificatie", "geometry"]].copy()
    bag["geometry"] = bag.geometry.centroid  # centroid for point-in-polygon
    bag = bag.set_geometry("geometry")
    # --- Spatial join: which parcel contains each BAG centroid?
    # Result has columns: ['identificatie', 'geometry', 'index_right']
    # We have all parcels as rows and then we check which bag lies in which parcel.
    # is that actually what happens?
    matches = gpd.sjoin(bag, parcels[["geometry"]], how="inner", predicate="within")
    #TODO: Border amount doesnt guarantee anything. Should use area for smallest plot
    #TODO: then i should check if all houses fall in that small plot
    # Rename 'index_right' to 'plotnummer' (since parcels index IS the plotnummer)
    matches = matches.rename(columns={"index_right": "Perceelnummer"})
    # Attach borders_amount from parcels (indexed by plotnummer)
    matches = matches.join(parcels[["borders_amount"]], on="Perceelnummer")
    # In case a centroid falls within multiple parcels (overlaps), keep smallest borders_amount
    # if part of pand falls outside of parcel lines, use the bigger one
    #plot all parcel polygons and all bag geometry

    best = (
        matches.sort_values("borders_amount", kind="stable")
               .drop_duplicates(subset="identificatie", keep="first")
               .loc[:, ["identificatie", "Perceelnummer", "borders_amount"]]
    )

    best_idx = best.set_index("identificatie")

    cols = ["Perceelnummer", "borders_amount"]

    out = df_units.merge(
        best_idx[cols],
        how="left",
        left_on="Pand Id",
        right_index=True,
        suffixes=("", "_new"),
    )

    # Fill only where missing (NaN) in the original
    for c in cols:
        out[c] = out[c].fillna(out[f"{c}_new"])

    # Optional: drop helper columns
    out = out.drop(columns=[f"{c}_new" for c in cols])

    return out