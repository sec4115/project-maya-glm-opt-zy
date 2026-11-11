"""Keep local Codex custom/namespace tools over upstream's checked function path."""
from __future__ import annotations

import copy
import json


def expand_request(request: dict) -> tuple[dict, dict[str, tuple[str | None, str, bool]]]:
    """Flatten declarations and replay items; leave the caller's stored history intact."""
    req = copy.deepcopy(request)
    tools = req.get("tools")
    if tools is not None and not isinstance(tools, list):
        raise ValueError("tools must be an array")
    declared, mapping = [], {}

    def name_of(name, namespace=None):
        if not isinstance(name, str) or not name:
            raise ValueError("client tools require a nonempty name")
        if namespace is not None:
            # A namespace is one path segment: no separators inside (upstream v1.1.56's contract; ours uses
            # __ to qualify names, so "__" would make a qualified name ambiguous too).
            if not isinstance(namespace, str) or not namespace:
                raise ValueError("tool namespace requires a nonempty name")
            if "::" in namespace or "__" in namespace:
                raise ValueError("a namespace name must not contain a separator")
        return f"{namespace}__{name}" if namespace else name

    for tool in tools or []:
        if not isinstance(tool, dict):
            raise ValueError("tools must be objects")
        if tool.get("type") == "namespace":
            ns = tool.get("name")
            name_of(ns)
            if isinstance(ns, str) and ("::" in ns or "__" in ns):
                raise ValueError("a namespace name must not contain a separator")
            children = tool.get("tools")
            if not isinstance(children, list):
                raise ValueError("namespace.tools must be an array")
            if set(tool) - {"type", "name", "description", "tools"}:
                raise ValueError("unsupported namespace parameter")
            declared.extend((child, ns, tool.get("description", "")) for child in children)
        else:
            declared.append((tool, None, ""))
    flat = []
    for tool, ns, description in declared:
        if not isinstance(tool, dict) or tool.get("type") not in ("function", "custom"):
            raise ValueError("only client function or custom tools are supported")
        leaf = tool.get("name")
        name = name_of(leaf, ns)
        if name in mapping:
            raise ValueError("duplicate or colliding tool names")
        custom = tool["type"] == "custom"
        mapping[name] = (ns, leaf, custom)
        if custom:
            if set(tool) - {"type", "name", "description", "format"}:
                raise ValueError("unsupported custom tool parameter")
            fn = {"type": "function", "name": name, "description": tool.get("description", ""),
                  "parameters": {"type": "object", "properties": {"input": {"type": "string"}},
                                 "required": ["input"], "additionalProperties": False}}
            fmt = tool.get("format") or {"type": "text"}
            if not isinstance(fmt, dict) or fmt.get("type") not in ("text", "grammar"):
                raise ValueError("custom tool format must be text or grammar")
            if fmt["type"] == "grammar":
                if not isinstance(fmt.get("definition"), str):
                    raise ValueError("custom grammar requires a definition")
                fn["description"] += "\nThe raw input must follow this grammar:\n" + fmt["definition"]
        else:
            fn = {**tool, "name": name}
        if description:
            fn["description"] = description + "\n" + (fn.get("description") or "")
        flat.append(fn)
    if tools is not None:
        req["tools"] = flat
    choice = req.get("tool_choice")
    if isinstance(choice, dict) and choice.get("type") in ("function", "custom"):
        if set(choice) - {"type", "name", "namespace"}:
            raise ValueError("unsupported tool_choice parameter")
        name = name_of(choice.get("name"), choice.get("namespace"))
        if name not in mapping or mapping[name][2] != (choice["type"] == "custom"):
            raise ValueError("tool_choice must name a declared tool of the same type")
        req["tool_choice"] = {"type": "function", "name": name}
    items = req.get("input")
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue  # The upstream validator reports the malformed item.
            kind = item.get("type")
            if kind in ("function_call", "custom_tool_call"):
                item["name"] = name_of(item.get("name"), item.pop("namespace", None))
                if kind == "custom_tool_call":
                    raw = item.pop("input", None)
                    if not isinstance(raw, str):
                        raise ValueError("custom_tool_call.input must be a string")
                    item.update(type="function_call", arguments=json.dumps({"input": raw}, ensure_ascii=False))
            elif kind == "custom_tool_call_output":
                item["type"] = "function_call_output"
    # Codex asks for a summary preference; this local model emits its visible
    # reasoning. Keep the preference on the response but use the same effort.
    reasoning = req.get("reasoning")
    if isinstance(reasoning, dict) and reasoning.get("summary") in ("auto", "concise", "detailed"):
        reasoning.pop("summary")
    return req, mapping


def restore_item(item: dict, mapping: dict) -> dict:
    out = copy.deepcopy(item)
    if out.get("type") == "function_call" and out.get("name") in mapping:
        ns, leaf, custom = mapping[out["name"]]
        out["name"] = leaf
        if ns:
            out["namespace"] = ns
        if custom:
            args = out.pop("arguments", "")
            raw = ""
            if args:
                try:
                    raw = json.loads(args).get("input", "")
                except (ValueError, AttributeError):
                    if out.get("status") == "completed":
                        raise ValueError("custom tool arguments must contain a string input") from None
            if not isinstance(raw, str):
                raise ValueError("custom tool input must be a string")
            out.update(type="custom_tool_call", input=raw)
    return out


def restore_response(response: dict, original: dict, mapping: dict) -> dict:
    out = copy.deepcopy(response)
    out["tools"] = copy.deepcopy(original.get("tools") or [])
    out["tool_choice"] = copy.deepcopy(original.get("tool_choice", "auto"))
    out["reasoning"] = {"effort": None, "summary": None, **(original.get("reasoning") or {})}
    out["output"] = [restore_item(item, mapping) for item in out["output"]]
    return out


def restore_events(events, original: dict, mapping: dict):
    """Custom arguments use one raw-input delta at completion, with contiguous IDs."""
    custom_ids, sequence = set(), 0

    def numbered(name, data):
        nonlocal sequence
        data = {**data, "type": name, "sequence_number": sequence}
        sequence += 1
        return name, data

    try:
        for event in events:
            if event is None:
                yield None
                continue
            name, data = event
            data = copy.deepcopy(data)
            item = data.get("item")
            if isinstance(item, dict):
                data["item"] = item = restore_item(item, mapping)
                if item.get("type") == "custom_tool_call":
                    custom_ids.add(item["id"])
                    if name == "response.output_item.done":
                        fields = {"item_id": item["id"], "output_index": data["output_index"]}
                        yield numbered("response.custom_tool_call_input.delta", {**fields, "delta": item["input"]})
                        yield numbered("response.custom_tool_call_input.done", {**fields, "input": item["input"]})
            if data.get("item_id") in custom_ids and name.startswith("response.function_call_arguments."):
                continue
            if isinstance(data.get("response"), dict):
                data["response"] = restore_response(data["response"], original, mapping)
            yield numbered(name, data)
    finally:
        events.close()
