from __future__ import annotations

from appSlicerSegelin.v2.core.commands import CommandStack, CompositeCommand, FunctionCommand


def test_push_executes_by_default_and_can_be_undone():
    state = {"value": 0}

    def do() -> None:
        state["value"] += 1

    def undo() -> None:
        state["value"] -= 1

    stack = CommandStack()
    stack.push(FunctionCommand("inc", do, undo))
    assert state["value"] == 1
    stack.undo()
    assert state["value"] == 0
    stack.redo()
    assert state["value"] == 1


def test_push_after_undo_clears_redo():
    state = {"v": 0}
    stack = CommandStack()
    stack.push(FunctionCommand("a", lambda: state.__setitem__("v", 1), lambda: state.__setitem__("v", 0)))
    stack.undo()
    assert stack.can_redo
    stack.push(FunctionCommand("b", lambda: state.__setitem__("v", 2), lambda: state.__setitem__("v", 0)))
    assert not stack.can_redo


def test_composite_command_undoes_children_in_reverse():
    order = []
    a = FunctionCommand("a", lambda: order.append("do-a"), lambda: order.append("undo-a"))
    b = FunctionCommand("b", lambda: order.append("do-b"), lambda: order.append("undo-b"))
    macro = CompositeCommand("ab", [a, b])
    macro.do()
    macro.undo()
    assert order == ["do-a", "do-b", "undo-b", "undo-a"]


def test_max_depth_drops_oldest():
    stack = CommandStack(max_depth=2)
    for i in range(5):
        stack.push(FunctionCommand(f"c{i}", lambda: None, lambda: None))
    assert len(stack._undo) == 2  # type: ignore[attr-defined]
