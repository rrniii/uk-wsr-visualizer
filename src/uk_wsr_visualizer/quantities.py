"""Human-readable labels for UK weather surveillance radar quantities.

The viewer retains ODIM quantity codes for file selection and provenance, but
uses these labels in normal user-facing controls and figure metadata.
"""

from __future__ import annotations


QUANTITY_LABELS = {
    "DBZH": "Horizontal Reflectivity",
    "DBZ": "Reflectivity",
    "DBZV": "Vertical Reflectivity",
    "TH": "Total Reflectivity",
    "TV": "Vertical Reflectivity",
    "VRADH": "Horizontal Radial Velocity",
    "VRADDH": "Horizontal Radial Velocity",
    "VRAD": "Radial Velocity",
    "WRADH": "Horizontal Spectrum Width",
    "WRAD": "Spectrum Width",
    "ZDR": "Differential Reflectivity",
    "RHOHV": "Copolar Correlation Coefficient",
    "PHIDP": "Differential Phase",
    "KDP": "Specific Differential Phase",
    "SQIH": "Signal Quality Index",
    "SQI": "Signal Quality Index",
    "SNR": "Signal-to-Noise Ratio",
    "SNRH": "Horizontal Signal-to-Noise Ratio",
    "SNRV": "Vertical Signal-to-Noise Ratio",
    "CI": "Clutter Index",
    "QIND": "Quality Index",
}


def quantity_label(quantity: str | None) -> str:
    """Return a readable quantity label without exposing an ODIM code by default."""

    code = str(quantity or "").strip().upper()
    if code in QUANTITY_LABELS:
        return QUANTITY_LABELS[code]
    return code.replace("_", " ").title() if code else "Unknown Variable"
