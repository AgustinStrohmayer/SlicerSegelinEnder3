"""Design tokens.

Every visual decision (colour, spacing, radius, typography, shadow,
elevation) lives here. ``qss.py`` substitutes references like
``{{color.accent}}`` when loading the active theme; ``effects.py``
reads :class:`ShadowTokens` to apply ``QGraphicsDropShadowEffect``
(Qt does not honour CSS ``box-shadow``).

The system intentionally mirrors Linear / Vercel: 4-step spacing scale,
3 radii, body weights 400-700, a single accent colour with a 10%-alpha
subtle variant for hovers and active backgrounds.
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
    border_strong: str
    text: str
    text_strong: str
    muted: str
    accent: str
    accent_hover: str
    accent_subtle: str  # ~10% alpha — backgrounds for active/hover states
    success: str
    warning: str
    danger: str
    overlay: str  # semi-transparent backdrop for modals


@dataclass(frozen=True, slots=True)
class SpaceTokens:
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 24
    xxl: int = 32
    xxxl: int = 48


@dataclass(frozen=True, slots=True)
class RadiusTokens:
    sm: int = 6
    md: int = 10
    lg: int = 14


@dataclass(frozen=True, slots=True)
class TypeTokens:
    family: str = "Inter, 'Segoe UI', system-ui, sans-serif"
    family_mono: str = "'JetBrains Mono', 'SF Mono', Menlo, Consolas, monospace"
    size_caption: int = 11
    size_small: int = 12
    size_body: int = 13
    size_title: int = 15
    size_display: int = 22
    weight_body: int = 400
    weight_medium: int = 500
    weight_semibold: int = 600
    weight_bold: int = 700


@dataclass(frozen=True, slots=True)
class ShadowSpec:
    """Parameters for :class:`QGraphicsDropShadowEffect`."""

    radius: float
    offset_y: float
    color: str  # #RRGGBBAA


@dataclass(frozen=True, slots=True)
class ShadowTokens:
    sm: ShadowSpec
    md: ShadowSpec
    lg: ShadowSpec


@dataclass(frozen=True, slots=True)
class Tokens:
    name: ThemeName
    color: ColorTokens
    shadow: ShadowTokens
    space: SpaceTokens = field(default_factory=SpaceTokens)
    radius: RadiusTokens = field(default_factory=RadiusTokens)
    typography: TypeTokens = field(default_factory=TypeTokens)


DARK = Tokens(
    name="dark",
    color=ColorTokens(
        bg="#0B0D11",
        surface="#14181F",
        surface_alt="#1B2230",
        border="#242C3D",
        border_strong="#384256",
        text="#ECEEF4",
        text_strong="#FFFFFF",
        muted="#8A93A6",
        accent="#7C5CFF",
        accent_hover="#9479FF",
        accent_subtle="rgba(124, 92, 255, 0.14)",
        success="#34D399",
        warning="#F59E0B",
        danger="#F87171",
        overlay="rgba(8, 10, 14, 0.62)",
    ),
    shadow=ShadowTokens(
        sm=ShadowSpec(radius=6, offset_y=1, color="#00000040"),
        md=ShadowSpec(radius=18, offset_y=4, color="#00000055"),
        lg=ShadowSpec(radius=32, offset_y=10, color="#00000070"),
    ),
)

LIGHT = Tokens(
    name="light",
    color=ColorTokens(
        bg="#FAFBFC",
        surface="#FFFFFF",
        surface_alt="#F4F6FA",
        border="#E5E8EE",
        border_strong="#CBD1DC",
        text="#0F1115",
        text_strong="#000000",
        muted="#5A6376",
        accent="#7C5CFF",
        accent_hover="#6B47FF",
        accent_subtle="rgba(124, 92, 255, 0.12)",
        success="#10B981",
        warning="#D97706",
        danger="#DC2626",
        overlay="rgba(15, 17, 21, 0.32)",
    ),
    shadow=ShadowTokens(
        sm=ShadowSpec(radius=6, offset_y=1, color="#0F111514"),
        md=ShadowSpec(radius=18, offset_y=4, color="#0F11151F"),
        lg=ShadowSpec(radius=32, offset_y=12, color="#0F111530"),
    ),
)


def get_tokens(name: ThemeName) -> Tokens:
    return DARK if name == "dark" else LIGHT
