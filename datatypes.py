import geopandas as gpd
import pandas as pd
from dataclasses import dataclass
import argparse

@dataclass
class DataBundle:
    gdf_bag: gpd.GeoDataFrame | None = None
    gdf_kad: gpd.GeoDataFrame | None = None
    gdf_road: gpd.GeoDataFrame | None = None
    gdf_pand: gpd.GeoDataFrame | None = None
    df_units: pd.DataFrame | None = None

    def validate(self):
        required = {
            "gdf_bag": {"geometry", "pand_id"},
            "gdf_kad": {"geometry"},
            "df_units": {"Pand Id"},
        }

        for name, cols in required.items():
            df = getattr(self, name)

            if df is None:
                raise ValueError(f"{name} is required")

            missing = cols - set(df.columns)
            if missing:
                raise ValueError(f"{name} missing {missing}")

@dataclass
class HouseResult:
    pand_id: str
    storage_size: float
    garden_size: float
    classification: str
    error: str | None = None

@dataclass
class Config:
    loc_bag: str | None = None
    loc_kadaster: str | None = None
    loc_road: str | None = None
    loc_pand: str | None = None
    loc_units: str | None = None

    @classmethod
    def default_config(cls, script_type: str) -> 'Config':
        if script_type == "calc_garden_size" or script_type == "set_garden_manual":
            return cls(
                loc_bag=r"data\bag\bag-light.gpkg",
                loc_kadaster=r"data\kad\kadastralekaart_kadastralegrens.gml",
                loc_road=r"data\bgt\bgt_wegdeel.gml",
                loc_pand=r"data\bgt\bgt_pand.gml",
                loc_units=r"data\bag_ids\bag_ids.xlsx",
            )

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> 'Config':
        """Change default config based on command line arguments."""
        #default = cls.default_config()
        default = cls.default_config(args.script_type)
        return cls(
            loc_bag=args.bag_path or default.loc_bag,
            loc_kadaster=args.kadaster_path or default.loc_kadaster,
            loc_road=args.road_path or default.loc_road,
            loc_pand=args.pand_path or default.loc_pand,
            loc_units=args.units_path or default.loc_units,
        )

@dataclass
class BoundingBox:
    minx: float
    miny: float
    maxx: float
    maxy: float

    def __str__(self) -> str:
        return f"BoundingBox(minx={self.minx}, miny={self.miny}, maxx={self.maxx}, maxy={self.maxy})"
