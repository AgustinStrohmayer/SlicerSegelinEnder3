"""Design tokens.

Every visual decision (colour, spacing, radius, typography) lives
here. ``qss.py`` substitutes references like ``{{color.accent}}``
when loading the active theme. Swapping the accent or recolouring
the entire app is a one-line change.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

ThemeName = Literal["dark", "light"]


@dataclass(frozen=True, slots=True)
class ColorTokens:
    bg: str
    surface: str
    surface_alt: str
    border: str
    text: str
    muted: str
    accent: str
    accent_hover: str
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
    sm: int = 4
    md: int = 8
    lg: int = 12


@dataclass(frozen=True, slots=True)
class TypeTokens:
    family: str = "Inter, 'Segoe UI', system-ui, sans-serif"
    family_mono: str = "JetBrains Mono, Menlo, Consolas, monospace"
    size_body: int = 13
    size_title: int = 16
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
        bg="#0F1115",
        surface="#161A21",
        surface_alt="#1C2230",
        border="#2A3142",
        text="#E6E8EE",
        muted="#8A93A6",
        accent="#7C5CFF",
        accent_hover="#9479FF",
        success="#34D399",
        warning="#F59E0B",
        danger="#F87171",
    ),
)

LIGHT = Tokens(
    name="light",
    color=ColorTokens(
        bg="#FAFAFC",
        surface="#FFFFFF",
        surface_alt="#F1F3F8",
        border="#E2E5EC",
        text="#1A1D24",
        muted="#5B6478",
        accent="#7C5CFF",
        accent_hover="#6B47FF",
        success="#10B981",
        warning="#D97706",
        danger="#DC2626",
    ),
)


def get_tokens(name: ThemeName) -> Tokens:
    return DARK if name == "dark" else LIGHT
