"""Parse ADV control trees and project explicitly qualified alternative reactions.

No branch index is treated as a runtime predicate or an observed player choice.
The parser never reads assets or mutates the corpus.
"""

from dataclasses import dataclass, field
from collections.abc import Mapping
import re


class AdvParseError(ValueError):
    """The source does not establish an unambiguous command tree."""


class AdvProjectionError(ValueError):
    """Runtime conditions prevent a safe complete CSV projection."""


@dataclass(frozen=True)
class ConditionResolution:
    """Caller-verified external evidence; never a reconstructed source predicate."""

    labels: tuple[str, ...]
    evidence: str


def _attributes(body: str) -> list[tuple[str, str]]:
    # Attribute boundaries are recognized only outside nested commands and quotes.
    starts: list[tuple[int, int, str]] = []
    depth = 0
    quote = False
    escaped = False
    for i, char in enumerate(body):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            quote = not quote
        if quote:
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        if depth == 0 and (i == 0 or body[i - 1].isspace()):
            match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)=", body[i:])
            if match:
                starts.append((i, i + match.end(), match[1]))
    result = []
    for n, (_, begin, key) in enumerate(starts):
        end = starts[n + 1][0] if n + 1 < len(starts) else len(body)
        value = body[begin:end].rstrip()
        if value.startswith('"'):
            if not value.endswith('"') or len(value) < 2:
                raise AdvParseError(f"unclosed quoted {key}")
            value = value[1:-1].replace(r'\"', '"')
        result.append((key, value))
    return result


def _normalize(text: str) -> str:
    text = re.sub(r"<em(?:\\=|=[^>]*)?>", "<em>", text)
    return text.replace(r"\=", "=")


@dataclass
class AdvNode:
    id: str
    line: int
    command: str
    attributes: dict[str, str]
    raw: str
    children: list["AdvNode"] = field(default_factory=list)
    choices: list[str] = field(default_factory=list)
    choice_node_id: str | None = None
    branch_type: str | None = None
    branch_index: int | None = None
    option_text: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id, "line": self.line, "command": self.command,
            "attributes": self.attributes, "raw": self.raw,
            "children": [child.to_dict() for child in self.children],
            "choices": self.choices, "choice_node_id": self.choice_node_id,
            "branch_type": self.branch_type, "branch_index": self.branch_index,
            "option_text": self.option_text,
            # Runtime predicate metadata is not present in these script commands.
            "predicate": None,
            "predicate_status": "unknown" if self.branch_type == "Condition" else None,
        }


@dataclass
class AdvScript:
    source_id: str
    nodes: list[AdvNode]

    def to_dict(self) -> dict[str, object]:
        return {"source_id": self.source_id, "nodes": [n.to_dict() for n in self.nodes]}

    def csv_rows(
        self, *, common_only: bool = False,
        condition_resolutions: Mapping[str, ConditionResolution] | None = None,
        context: str | None = None,
    ) -> list[list[str]]:
        """Keep shared dialogue and label each alternative; never infer conditions.

        common_only explicitly omits all branch subtrees, including Choice branches.
        Unresolved Condition groups otherwise reject the entire projection. Resolutions
        require caller-verified external evidence and never alter the source graph.
        context qualifies every message as a conditional scenario and drops producers.
        """
        resolutions = condition_resolutions or {}
        conditions: dict[str, AdvNode] = {}

        def find_conditions(nodes: list[AdvNode]) -> None:
            for node in nodes:
                if node.command == "branchgroup" and node.branch_type == "Condition":
                    conditions[node.id] = node
                find_conditions(node.children)

        find_conditions(self.nodes)
        for node_id, resolution in resolutions.items():
            if node_id not in conditions:
                raise AdvProjectionError(f"{node_id}: resolution does not identify a Condition group")
            if len(resolution.labels) != len(conditions[node_id].children):
                raise AdvProjectionError(f"{node_id}: resolution label/branch count mismatch")
            if not resolution.labels or not resolution.evidence.strip() or any(not label.strip() for label in resolution.labels):
                raise AdvProjectionError(f"{node_id}: resolution requires nonempty labels and evidence")
        if context is not None and not context.strip():
            raise AdvProjectionError("context must be nonempty when supplied")
        rows = [["id", "name", "text", "trans"], ["info", self.source_id, "", ""]]

        def visit(nodes: list[AdvNode], path: tuple[str, ...] = ()) -> None:
            for node in nodes:
                if node.command == "branchgroup":
                    if common_only:
                        continue
                    resolution = resolutions.get(node.id)
                    if node.branch_type == "Condition" and resolution is None:
                        raise AdvProjectionError(f"{node.id}: unknown runtime predicate")
                    for index, branch in enumerate(node.children):
                        if resolution is not None:
                            option = _normalize(resolution.labels[index])
                            label = f"{node.id}/Condition#{branch.branch_index}「{option}；未确认实际触发」"
                        else:
                            option = _normalize(branch.option_text or "")
                            label = f"{node.id}/Choice#{branch.branch_index}「{option}」"
                        visit(branch.children, (*path, label))
                elif node.command == "choicegroup":
                    rows.extend(["select", "", _normalize(text), ""] for text in node.choices)
                elif node.command in ("message", "narration"):
                    text = node.attributes.get("text")
                    if text is None:
                        continue
                    speaker = node.attributes.get("name", "__narration__")
                    if node.command == "narration" or not speaker:
                        speaker = "__narration__"
                    if (path or context is not None) and speaker.strip() in ("{user}", "制作人", "プロデューサー"):
                        continue
                    text = _normalize(text)
                    if node.attributes.get("isInner") == "true" and not text.startswith(("（", "(")):
                        text = f"（{text}）"
                    if path:
                        text = f"【互斥分支・未确认选择：{' → '.join(path)}】{text}"
                    if context is not None:
                        text = f"【条件情境・未确认实际触发：{_normalize(context)}】{text}"
                    rows.append([str(node.line), speaker, text, ""])

        visit(self.nodes)
        return rows


def parse_adv(text: str, source_id: str) -> AdvScript:
    """Consume groupLength *child nodes*, recursively, retaining physical lines."""
    flat = []
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        match = re.fullmatch(r"\s*\[([A-Za-z_][A-Za-z0-9_]*)(?:\s+(.*))?\]\s*", raw)
        if not match:
            raise AdvParseError(f"{source_id}:{number}: invalid command")
        command, body = match[1], match[2] or ""
        attrs = _attributes(body)
        choices = []
        for key, value in attrs:
            if key == "choices":
                choice = re.fullmatch(r"\[choice\s+(.*)\]", value)
                if not choice:
                    raise AdvParseError(f"{source_id}:{number}: invalid choice")
                values = dict(_attributes(choice[1]))
                if "text" not in values:
                    raise AdvParseError(f"{source_id}:{number}: choice missing text")
                choices.append(values["text"])
        flat.append(AdvNode(f"{source_id}:L{number}", number, command, dict(attrs), raw,
                            choices=choices))
    position = 0

    def consume(*, branch_allowed: bool = False) -> AdvNode:
        nonlocal position
        if position >= len(flat):
            raise AdvParseError(f"{source_id}: groupLength exceeds source")
        node = flat[position]
        position += 1
        if node.command == "branch" and not branch_allowed:
            raise AdvParseError(f"{node.id}: orphan branch")
        if node.command in ("branchgroup", "branch"):
            value = node.attributes.get("groupLength", "0")
            if not re.fullmatch(r"\d+", value):
                raise AdvParseError(f"{node.id}: invalid groupLength {value!r}")
            if node.command == "branchgroup":
                node.branch_type = node.attributes.get("type")
                if node.branch_type not in ("Choice", "Condition"):
                    raise AdvParseError(f"{node.id}: unknown branch type {node.branch_type!r}")
            for index in range(int(value)):
                child = consume(branch_allowed=node.command == "branchgroup")
                if node.command == "branchgroup":
                    if child.command != "branch":
                        raise AdvParseError(f"{node.id}: groupLength expects branch children")
                    child.branch_type = node.branch_type
                    child.branch_index = index + 1
                node.children.append(child)
        return node

    roots = []
    while position < len(flat):
        roots.append(consume())

    def bind(nodes: list[AdvNode]) -> None:
        pending: AdvNode | None = None
        for node in nodes:
            if node.command == "choicegroup":
                if pending is not None:
                    raise AdvParseError(f"{pending.id}: choicegroup has no matching Choice group")
                if not node.choices:
                    raise AdvParseError(f"{node.id}: empty choicegroup")
                pending = node
            elif node.command == "branchgroup" and node.branch_type == "Choice":
                if pending is None or len(pending.choices) != len(node.children):
                    raise AdvParseError(f"{node.id}: missing choices or choice/branch count mismatch")
                node.choice_node_id = pending.id
                for child, option in zip(node.children, pending.choices, strict=True):
                    child.option_text = option
                    child.choice_node_id = pending.id
                pending = None
            bind(node.children)
        if pending is not None:
            raise AdvParseError(f"{pending.id}: choicegroup has no matching Choice group")

    bind(roots)
    return AdvScript(source_id, roots)
