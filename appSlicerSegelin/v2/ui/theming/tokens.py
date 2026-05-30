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


DARK = Tokens(
    name="dark",
    color=ColorTokens(
        bg="#0C0E13",
        surface="#15181F",
        surface_alt="#1B1F29",
        elevated="#242A38",
        border="#272D3A",
        border_strong="#363F50",
        text="#E8EAF0",
        muted="#969FB2",
        accent="#8268FF",
        accent_hover="#9C86FF",
        accent_soft="#241F3C",
        on_accent="#FFFFFF",
        success="#34D399",
        warning="#F5A524",
        danger="#F2585B",
    ),
)

LIGHT = Tokens(
    name="light",
    color=ColorTokens(
        bg="#EAEDF2",
        surface="#FFFFFF",
        surface_alt="#F1F3F9",
        elevated="#FFFFFF",
        border="#E4E7EF",
        border_strong="#D8DDE7",
        text="#1B1E26",
        muted="#69728A",
        accent="#6D4AFF",
        accent_hover="#5B38F0",
        accent_soft="#ECE8FF",
        on_accent="#FFFFFF",
        success="#0E9F6E",
        warning="#C2710C",
        danger="#E02424",
    ),
)


def get_tokens(name: ThemeName) -> Tokens:
    return DARK if name == "dark" else LIGHT
