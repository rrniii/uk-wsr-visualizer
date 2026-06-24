"""Optional dependency loading with actionable error messages."""

from __future__ import annotations


def require_h5py():
    try:
        import h5py  # type: ignore
    except ImportError as exc:
        raise RuntimeError("h5py is required for HDF5 catalog/preview operations. Install with: pip install -e .") from exc
    return h5py


def require_numpy():
    try:
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise RuntimeError("numpy is required for radar array operations. Install with: pip install -e .") from exc
    return np


def require_pillow():
    try:
        from PIL import Image  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Pillow is required for PNG preview generation. Install with: pip install -e .") from exc
    return Image


def require_rasterio():
    try:
        import rasterio  # type: ignore
        from rasterio.transform import from_origin  # type: ignore
    except ImportError as exc:
        raise RuntimeError("rasterio is required for GeoTIFF export. Install with: pip install -e '.[export]'") from exc
    return rasterio, from_origin


def require_netcdf4():
    try:
        import netCDF4  # type: ignore
    except ImportError as exc:
        raise RuntimeError("netCDF4 is required for CF NetCDF export. Install with: pip install -e '.[export]'") from exc
    return netCDF4


def require_shapefile():
    try:
        import shapefile  # type: ignore
    except ImportError as exc:
        raise RuntimeError("pyshp is required for Shapefile export. Install with: pip install -e '.[export]'") from exc
    return shapefile
