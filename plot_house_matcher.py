import warnings
import math
warnings.filterwarnings('ignore')
from typing import Tuple, List, Optional
import argparse
import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Polygon
from shapely.ops import polygonize, unary_union
from utility import Config, load_data, get_bbox_input
import os
import time
import matplotlib.pyplot as plt
import geopandas as gpd
import matplotlib.cm as cm
import numpy as np

try:
    # Shapely 2.0+
    from shapely.validation import make_valid
    HAS_MAKE_VALID = True
except Exception:
    HAS_MAKE_VALID = False

def _safe_make_valid(geom):
    if geom is None:
        return None
    try:
        if HAS_MAKE_VALID:
            return make_valid(geom)
        # classic self-heal fallback
        fixed = geom.buffer(0)
        return fixed if not fixed.is_empty else None
    except Exception:
        return None


def plot_all_parcels(parcels: gpd.GeoDataFrame, figsize=(10, 10)):
    """
    Plot all parcels with different colors.
    """
    # Create a color map
    n = len(parcels)
    colors = cm.get_cmap("tab20", n)  # tab20 has up to 20 distinct colors, repeated if more parcels
    parcel_colors = [colors(i % 20) for i in range(n)]

    # Plot
    fig, ax = plt.subplots(figsize=figsize)
    parcels.plot(
        ax=ax,
        color=parcel_colors,
        edgecolor="black",
        linewidth=0.8
    )

    ax.set_title("All Parcels")
    ax.set_axis_off()
    plt.show()

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

    # Long format: one record per (line, plot side)


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
        return gpd.GeoDataFrame(columns=["Perceelnummer", "borders_amount", "geometry"], geometry="geometry", crs=gdf_kad_lines.crs)
    parcels = gpd.GeoDataFrame(records, geometry="geometry", crs=gdf_kad_lines.crs)
    parcels = parcels.merge(counts, on="Perceelnummer", how="left")

    # Drop duplicates if any, keep polygon with max area
    parcels = parcels.sort_values("geometry", key=lambda s: s.area if hasattr(s, "area") else s).drop_duplicates("Perceelnummer", keep="last")
    return parcels

def find_plot_nummer_per_eenheid(
    df_tobias: pd.DataFrame,
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
      - df_tobias["Pand Id"]
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
    if parcels.empty:
        # nothing to match; return df unchanged
        if out_file:
            df_tobias.to_parquet(out_file, index=False)
        return df_tobias

    # Set parcels index to plotnummer so sjoin carries it via 'index_right'
    parcels = parcels.set_index("Perceelnummer", drop=True)
    # --- Prepare BAG centroids only for Tobias Pand Ids
    bag = gdf_bag[gdf_bag["identificatie"].isin(df_tobias["Pand ID"])][["identificatie", "geometry"]].copy()
    bag["geometry"] = bag.geometry.centroid  # centroid for point-in-polygon
    bag = bag.set_geometry("geometry")
    # --- Spatial join: which parcel contains each BAG centroid?
    # Result has columns: ['identificatie', 'geometry', 'index_right']
    matches = gpd.sjoin(bag, parcels[["geometry"]], how="inner", predicate="within")
    print("amount of matches found:", len(matches))
    # Rename 'index_right' to 'plotnummer' (since parcels index IS the plotnummer)
    matches = matches.rename(columns={"index_right": "Perceelnummer"})
    # Attach borders_amount from parcels (indexed by plotnummer)
    matches = matches.join(parcels[["borders_amount"]], on="Perceelnummer")
    # In case a centroid falls within multiple parcels (overlaps), keep smallest borders_amount
    # if part of pand falls outside of parcel lines, huse the bigger one
    best = (
        matches.sort_values("borders_amount", kind="stable")
               .drop_duplicates(subset="identificatie", keep="first")
               .loc[:, ["identificatie", "Perceelnummer", "borders_amount"]]
    )

    # --- Merge back to Tobias
    out = df_tobias.merge(
        best, left_on="Pand ID", right_on="identificatie", how="left"
    ).drop(columns=["identificatie"])

    out = out.rename(columns={"Perceelnummer": "Perceelnummer"})

    if out_file:
        out.to_parquet(out_file, index=False)

    return out

def main():
    parser = argparse.ArgumentParser(description='Process garden data with optional custom bounding box')
    parser.add_argument('--bag-path', help='Path to BAG dataset')
    parser.add_argument('--kadaster-path', help='Path to kadaster dataset')
    parser.add_argument('--tobias-path', help='Path to Tobias Excel file')
    args = parser.parse_args()

    config = Config.default_config("plot_eenheid_matcher")
    bbox = None

    print("Processing full dataset...")

    gdf_bag, gdf_kad, df_tobias, _, _, _, _, loc_bag, loc_kad = load_data(config, bbox)
    # Get unique plot numbers

    plot_nummers = list(set(gdf_kad["perceelLinks"].tolist() + gdf_kad["perceelRechts"].tolist()))
    print(f"Processing {len(plot_nummers)} plot numbers")

    # Check if an output file already exists if it does, check plot_nummers already found
    if "Perceelnummer" in df_tobias.columns:
        plot_nummers = [plot for plot in plot_nummers if plot not in df_tobias["Perceelnummer"].unique()]
        print(f"Found {len(plot_nummers)} new plot numbers to process")

    df_tobias = find_plot_nummer_per_eenheid(df_tobias, gdf_kad, gdf_bag, plot_nummers)

    #find path to this script
    output_file = os.path.join(os.path.dirname(__file__), "data", "output", f"ids_with_parcel.xlsx")
    
    df_tobias.to_excel(output_file)
    print(f"Results saved to {output_file}")

if __name__ == "__main__":
    tic = time.perf_counter()
    main()
    toc = time.perf_counter()
    print(f"Script finished in {toc - tic:0.4f} seconds")