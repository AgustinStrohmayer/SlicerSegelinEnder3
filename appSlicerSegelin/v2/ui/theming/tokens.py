"""Design tokens.

Every visual decision (colour, spacing, radius, typography) lives
here. ``qss.py`` substitutes references like ``{{color.accent}}``
when loading the active theme. Swapping the accent or recolouring
the entire app is a one-line change.

The colour model is a small elevation ladder shared by both themes:

* ``bg``          — the deepest layer (app/canvas background)
* ``surface``     — panels: toolbar, docks, sidebar, menus
* ``surface_alt`` — cards / grouped sections sitting on a panel
* ``elevated``    — raised controls (buttons) and hover fills

Keeping the same semantic names in both themes means the QSS never
hard-codes a light/dark assumption.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ThemeName = Literal["dark", "light"]


@dataclass(frozen=True, slots=True)
class ColorTokens:
    bg: str            # app/canvas background — the deepest layer
    surface: str       # panels: toolbar, docks, sidebar, menus
    surface_alt: str   # cards / grouped sections sitting on a panel
    elevated: str      # raised controls (buttons) and hover fills
    border: str        # hairline separators
    border_strong: str # input outlines, emphasised dividers
    text: str
    muted: str
    accent: str
    accent_hover: str
    accent_soft: str   # tinted fill for selections / active rows
    on_accent: str     # text/icon colour on top of the accent fill
    success: str
    warning: str
    danger: str


@dataclass(frozen=True, slots=True)
class SpaceTokens:
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 24
    xxl: int = 32


@dataclass(frozen=True, slots=True)
class RadiusTokens:
    sm: int = 6
    md: int = 9
    lg: int = 14


@dataclass(frozen=True, slots=True)
class TypeTokens:
    family: str = "Inter, 'Segoe UI', system-ui, sans-serif"
    family_mono: str = "JetBrains Mono, Menlo, Consolas, monospace"
    size_body: int = 13
    size_title: int = 15
    size_small: int = 11


@dataclass(frozen=True, slots=True)
class Tokens:
    name: ThemeName
    color: ColorTokens
    space: SpaceTokens = field(default_factory=SpaceTokens)
    radius: RadiusTokens = field(default_factory=RadiusTokens)
    typography: TypeTokens = field(default_factory=TypeTokens)


# Palette: warm Graphite neutral ramp + Amber accent — an industrial,
# machine-shop feel (Fusion 360 / Bambu Studio lineage). Amber is a *light*
# accent, so text/icons sitting on top of it use the dark ``on_accent`` tone
# for contrast (white-on-amber fails WCAG). Neutrals carry a subtle warm tint.
DARK = Tokens(
    name="dark",
    color=ColorTokens(
        bg="#15171C",          # app canvas — warm graphite
        surface="#1E2127",     # panels: toolbar, sidebar, menus
        surface_alt="#262A33",  # cards, tiles (clearly raised off the panel)
        elevated="#323843",    # buttons / hover fills
        border="#2F343E",      # hairline separators
        border_strong="#454C59",  # input outlines, card edges
        text="#ECEDEF",
        muted="#9DA3AE",       # secondary text — AA on panels
        accent="#F59E0B",      # amber-500
        accent_hover="#FBBF24",  # amber-400
        accent_soft="#2C2412",  # deep amber-tinted fill (selection/pressed)
        on_accent="#18181B",   # dark text/icons on the amber fill
        success="#22C55E",
        warning="#FB923C",     # orange — distinct from the amber accent
        danger="#F05252",
    ),
)

LIGHT = Tokens(
    name="light",
    color=ColorTokens(
        bg="#F3F2EF",          # app canvas — warm off-white
        surface="#FFFFFF",     # panels
        surface_alt="#F2F0EB",  # warm light cards / inputs
        elevated="#FFFFFF",    # buttons (white, raised on warm panels)
        border="#E7E4DD",      # warm hairline
        border_strong="#D6D2C8",
        text="#1A1A18",        # near-black, warm
        muted="#6B6860",       # readable warm secondary (~AA)
        accent="#D97706",      # amber-600 — readable on white
        accent_hover="#B45309",  # amber-700
        accent_soft="#FEF3C7",  # amber-100
        on_accent="#18181B",   # dark text/icons on the amber fill
        success="#16A34A",
        warning="#EA580C",     # orange — distinct from accent
        danger="#DC2626",
    ),
)


def get_tokens(name: ThemeName) -> Tokens:
    return DARK if name == "dark" else LIGHT
