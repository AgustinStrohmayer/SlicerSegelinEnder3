"""Width / height checks of a foam block against the segelín's arms."""
from appSlicerSegelin.v2.core.gcode_reader import parse_gcode
from appSlicerSegelin.v2.core.hotwire_rig import PRESETS, FoamBlock, check_block, check_cut


def _rig():
    return next(iter(PRESETS.values()))


def test_off_centre_block_needs_the_room_of_a_wider_one():
    rig = _rig()
    w = int(rig.usable_width(30.0)) - 4
    ok = FoamBlock(width_x=w, height_z=30.0, y0=5.0, spacer=20.0)
    assert not any("Width" in i for i in check_block(rig, ok))
    shifted = FoamBlock(width_x=w, height_z=30.0, y0=5.0, spacer=20.0, x_offset=10.0)
    assert any("Width" in i for i in check_block(rig, shifted))


def test_cut_checks_only_passes_through_the_block():
    rig = _rig()
    block = FoamBlock(length_y=100.0, height_z=40.0, width_x=rig.usable_width(10.0) - 1, y0=10.0, z0=0.0, spacer=20.0)
    # a deep entry outside the block (Y < 10) must not count; inside it the wire stays 30 mm up
    tp = parse_gcode("G1 Y0 Z-20\nG1 Y5 Z-20\nG1 Y5 Z30\nG1 Y110 Z30\nG1 Y115 Z30\n")
    assert not any("arms" in i for i in check_cut(rig, block, tp))
    deep = parse_gcode("G1 Y0 Z30\nG1 Y50 Z0\nG1 Y115 Z30\n")
    assert any("arms" in i for i in check_cut(rig, block, deep))
    assert not any("Width" in i for i in check_block(rig, block, worst_case=False))
    assert any("Width" in i for i in check_block(rig, block))
