"""High-level slicing orchestration.

Turns a :class:`Project` into trajectories, layers and cut plans by
composing the pure ``core`` building blocks. UI controllers call these
functions; they never touch Qt and are fully unit-testable.
"""
from __future__ import annotations

from ..core.cutplan import CutPlan
from ..core.geometry import Segment
from ..core.kerf import compensate_kerf
from ..core.machine import MachineProfile
from ..core.plates import Layer, partition_by_manual_cuts, split_into_plates
from ..core.project import Project
from ..core.trajectory import build_block_trajectory, build_full_trajectory


def standard_trajectory(project: Project) -> list[Segment]:
    """Full machine trajectory (entry → cut → exit → returns) for the part.

    Once the project has a foam block, the wire enters it from the side or the top
    and never crosses the foam on its way in or out; before that, the legacy path.
    """
    machine = project.machine_segments()
    key = (tuple(machine), project.block_created, project.block if project.block_created else None,
           project.entry, project.reverse_cut, project.kerf_comp_mm)
    global _last_standard
    if _last_standard is not None and _last_standard[0] == key:
        return list(_last_standard[1])  # a block edit asks for it several times; it only changes with the key
    machine = compensate_kerf(machine, project.kerf_comp_mm)
    if project.block_created:
        out = build_block_trajectory(machine, project.block, entry=project.entry, reverse=project.reverse_cut)
    else:
        out = build_full_trajectory(machine, add_unions=False, reverse=project.reverse_cut)
    _last_standard = (key, tuple(out))
    return out


_last_standard: tuple | None = None


def build_layers(project: Project) -> list[Layer]:
    """Split into plates or partition by manual cuts, depending on mode."""
    machine = project.machine_segments()
    if project.use_manual_cuts:
        return partition_by_manual_cuts(
            machine,
            project.manual_cuts,
            project.offset_y,
            project.offset_z,
            auto_close=project.auto_close_manual,
        )
    if project.split_into_plates:
        return split_into_plates(machine, project.area_y_mm, project.area_z_mm)
    return []


def cut_plan(segments: list[Segment], machine: MachineProfile, notes: tuple[str, ...] = ()) -> CutPlan:
    return CutPlan(segments=tuple(segments), machine=machine, notes=notes)


def standard_cut_plan(project: Project) -> CutPlan:
    return cut_plan(standard_trajectory(project), project.machine)
