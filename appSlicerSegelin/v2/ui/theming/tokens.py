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


# Palette: Slate neutral ramp + Indigo accent — a calm, high-contrast,
# professional pairing (Linear / Vercel / Tailwind-docs lineage). Text and
# muted tones meet WCAG AA on their intended surfaces.
DARK = Tokens(
    name="dark",
    color=ColorTokens(
        bg="#0A0E16",          # app canvas — deep slate
        surface="#121826",     # panels: toolbar, sidebar, menus
        surface_alt="#1B2335",  # cards, tiles (clearly raised off the panel)
        elevated="#27324A",    # buttons / hover fills
        border="#28324A",      # hairline separators
        border_strong="#3C4A66",  # input outlines, card edges
        text="#F1F5F9",        # slate-100
        muted="#94A3B8",       # slate-400 — secondary text
        accent="#6366F1",      # indigo-500
        accent_hover="#818CF8",  # indigo-400
        accent_soft="#1E1B4B",  # indigo-950 — selection / pressed fills
        on_accent="#FFFFFF",
        success="#22C55E",
        warning="#F59E0B",
        danger="#F05252",
    ),
)

LIGHT = Tokens(
    name="light",
    color=ColorTokens(
        bg="#EBEEF4",          # app canvas — cool slate-100/200
        surface="#FFFFFF",     # panels
        surface_alt="#F1F5F9",  # slate-100 cards / inputs
        elevated="#FFFFFF",    # buttons (white, raised on slate panels)
        border="#E2E8F0",      # slate-200
        border_strong="#CBD5E1",  # slate-300
        text="#0F172A",        # slate-900 — strong contrast
        muted="#475569",       # slate-600 — readable secondary
        accent="#4F46E5",      # indigo-600
        accent_hover="#4338CA",  # indigo-700
        accent_soft="#E0E7FF",  # indigo-100
        on_accent="#FFFFFF",
        success="#16A34A",
        warning="#D97706",
        danger="#DC2626",
    ),
)


def get_tokens(name: ThemeName) -> Tokens:
    return DARK if name == "dark" else LIGHT
