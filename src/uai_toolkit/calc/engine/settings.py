"""Runtime settings that influence evaluation and formatting."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Settings:
    angle: str = "rad"      # 'rad' or 'deg' — affects trig
    precision: int = 12     # significant figures for float display
    base: str = "dec"       # default output base: dec/hex/bin/oct
    full: bool = False       # if True, show full float precision (no cleanup)
