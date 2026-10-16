"""
Tolerant JSON extraction for LLM output.
Strips markdown fences, finds the outermost object, and repairs the most
common model mistakes (unclosed brackets, trailing commas) before parsing.
"""
import json
import re


def _close_brackets(s: str) -> str:
    """Insert missing ] / } so every opener is closed in the right order."""
    out, stack, in_str, esc = [], [], False, False
    pairs = {"{": "}", "[": "]"}
    for ch in s:
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in pairs:
            stack.append(pairs[ch])
        elif ch in "]}":
            # Close any inner structures the model forgot before this closer
            while stack and stack[-1] != ch:
                out.append(stack.pop())
            if stack:
                stack.pop()
            else:
                continue          # stray closer — drop it
        out.append(ch)
    if in_str:
        out.append('"')
    out.extend(reversed(stack))
    return "".join(out)


def extract_json(raw: str, label: str = "Model") -> dict:
    text = re.sub(r"^```(?:json)?", "", raw.strip()).strip()
    text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    if start == -1:
        raise ValueError(f"{label} returned no JSON.\nRaw:\n{raw[:600]}")
    end = text.rfind("}")
    candidate = text[start:end + 1] if end > start else text[start:]

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass
    repaired = re.sub(r",\s*([}\]])", r"\1", _close_brackets(text[start:]))
    # Drop anything after the top-level object closes
    depth, in_str, esc = 0, False, False
    for i, ch in enumerate(repaired):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
            if depth == 0:
                repaired = repaired[:i + 1]
                break
    try:
        return json.loads(repaired)
    except json.JSONDecodeError as e:
        raise ValueError(f"{label} returned invalid JSON ({e}).\nRaw:\n{raw[:600]}") from e
