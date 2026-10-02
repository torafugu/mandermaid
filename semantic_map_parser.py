"""Minimal semanticMap DSL parser. Run: python semantic_map_parser.py diagram.smap

Input is converted to a JSON intermediate representation; no layout is computed.
Statements are line-oriented, with optional one-line `around` blocks.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


DIRECTIONS = {
    "north", "northeast", "east", "southeast",
    "south", "southwest", "west", "northwest",
}
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


class ParseError(ValueError):
    pass


@dataclass(frozen=True)
class Node:
    id: str
    label: str


@dataclass(frozen=True)
class Placement:
    anchor: str
    target: str
    direction: str | None
    distance: int


@dataclass(frozen=True)
class Link:
    source: str
    target: str


def _tokens(segment: str, line: int) -> list[str]:
    try:
        return shlex.split(segment, comments=True, posix=True)
    except ValueError as exc:
        raise ParseError(f"line {line}: {exc}") from exc


def _id(value: str, line: int) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ParseError(f"line {line}: invalid node ID {value!r}")
    return value


def parse(source: str) -> dict:
    nodes: dict[str, Node] = {}
    placements: list[Placement] = []
    links: list[Link] = []
    references: list[tuple[str, int]] = []
    focus: str | None = None
    active_anchor: str | None = None
    pending_anchor: str | None = None
    started = False

    for line_number, raw in enumerate(source.splitlines(), 1):
        # Braces delimit blocks; labels containing braces are deliberately outside v0.
        parts = re.split(r"([{}])", raw)
        for i, part in enumerate(parts):
            if part == "{":
                if pending_anchor is None or active_anchor is not None:
                    raise ParseError(f"line {line_number}: unexpected '{{'")
                active_anchor, pending_anchor = pending_anchor, None
                continue
            if part == "}":
                if active_anchor is None:
                    raise ParseError(f"line {line_number}: unexpected '}}'")
                active_anchor = None
                continue
            tokens = _tokens(part, line_number)
            if not tokens:
                continue
            if not started:
                if tokens != ["semanticMap"]:
                    raise ParseError(f"line {line_number}: expected semanticMap header")
                started = True
                continue
            if active_anchor is not None:
                direction = tokens.pop(0) if tokens[0] in DIRECTIONS else None
                if not tokens:
                    raise ParseError(f"line {line_number}: missing placement target")
                target = _id(tokens.pop(0), line_number)
                distance = 1
                if tokens:
                    if len(tokens) != 2 or tokens[0] != "at" or not tokens[1].isdigit() or int(tokens[1]) < 1:
                        raise ParseError(f"line {line_number}: expected 'at' and a positive integer")
                    distance = int(tokens[1])
                if target == active_anchor:
                    raise ParseError(f"line {line_number}: node cannot be around itself")
                placements.append(Placement(active_anchor, target, direction, distance))
                references.append((target, line_number))
                continue
            keyword, *args = tokens
            if keyword == "node" and len(args) == 2:
                node_id = _id(args[0], line_number)
                if node_id in nodes:
                    raise ParseError(f"line {line_number}: duplicate node {node_id!r}")
                nodes[node_id] = Node(node_id, args[1])
            elif keyword == "around" and len(args) == 1:
                pending_anchor = _id(args[0], line_number)
                references.append((pending_anchor, line_number))
                if i + 1 >= len(parts) or parts[i + 1] != "{":
                    raise ParseError(f"line {line_number}: expected '{{' after around anchor")
            elif keyword == "link" and len(args) == 3 and args[1] == "--":
                source_id = _id(args[0], line_number)
                target_id = _id(args[2], line_number)
                links.append(Link(source_id, target_id))
                references.extend(((source_id, line_number), (target_id, line_number)))
            elif keyword == "focus" and len(args) == 1:
                if focus is not None:
                    raise ParseError(f"line {line_number}: duplicate focus")
                focus = _id(args[0], line_number)
                references.append((focus, line_number))
            else:
                raise ParseError(f"line {line_number}: invalid statement {part.strip()!r}")
        if pending_anchor is not None:
            raise ParseError(f"line {line_number}: expected '{{' after around anchor")

    if not started:
        raise ParseError("missing semanticMap header")
    if active_anchor is not None:
        raise ParseError(f"unclosed around block for {active_anchor!r}")
    for node_id, line_number in references:
        if node_id not in nodes:
            raise ParseError(f"line {line_number}: undefined node {node_id!r}")
    return {
        "type": "semanticMap",
        "nodes": [asdict(node) for node in nodes.values()],
        "placements": [asdict(placement) for placement in placements],
        "links": [asdict(link) for link in links],
        "focus": focus,
    }


def main() -> int:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("file", nargs="?", type=Path, help="DSL file (stdin if omitted)")
    args = cli.parse_args()
    try:
        source = args.file.read_text(encoding="utf-8") if args.file else sys.stdin.read()
        print(json.dumps(parse(source), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ParseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
