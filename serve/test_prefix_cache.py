"""Schema-only canonicalization must improve prefixes without changing content."""
import copy
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from serve.frontend import ChatTemplate, openai_to_messages, anthropic_to_messages

ROOT = Path(__file__).resolve().parents[1]


def reverse_maps(value):
    if isinstance(value, dict):
        return {k: reverse_maps(value[k]) for k in reversed(value)}
    if isinstance(value, list):
        return [reverse_maps(x) for x in value]
    return value


class PrefixStability(unittest.TestCase):
    def test_schema_mapping_order_does_not_change_rendered_prefix(self):
        tool = {"name": "cache_test_schema", "description": "test", "parameters": {"type": "object",
                "properties": {"zeta": {"type": "string"}, "alpha": {"enum": ["B", "A"], "type": "string"}},
                "required": ["zeta", "alpha"]}}
        template = ChatTemplate(ROOT / "serve/chat_template.jinja")
        for api in ("openai", "anthropic"):
            def render(t):
                r = {"messages": [{"role": "user", "content": "test"}]}
                if api == "openai":
                    r["tools"] = [{"type": "function", "function": t}]
                    m, tools, kw = openai_to_messages(r)
                else:
                    r["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}]
                    m, tools, kw = anthropic_to_messages(r)
                return template.render(m, tools=tools, **kw), tools
            before = copy.deepcopy(tool)
            with patch.dict(os.environ, {"STRATA_PREFIX_CANONICAL_TOOLS": "1"}):
                a, tools = render(tool)
                b, _ = render(reverse_maps(tool))
            self.assertEqual(a, b, api)
            self.assertEqual(tools[0]["parameters"]["required"], ["zeta", "alpha"])
            self.assertEqual(tools[0]["parameters"]["properties"]["alpha"]["enum"], ["B", "A"])
            self.assertEqual(tool, before)

    def test_opt_out_preserves_legacy_mapping_order(self):
        tool = {"name": "cache_test_legacy", "parameters": {"properties": {"z": {}, "a": {}}}}
        with patch.dict(os.environ, {"STRATA_PREFIX_CANONICAL_TOOLS": "0"}):
            _, tools, _ = openai_to_messages({"tools": [tool]})
        self.assertEqual(list(tools[0]["parameters"]["properties"]), ["z", "a"])

    def test_history_and_generated_arguments_are_never_canonicalized(self):
        args = {"z": 1, "a": 2}
        req = {"messages": [{"role": "assistant", "content": "  text\n", "tool_calls": [
            {"id": "test_call", "function": {"name": "cache_test", "arguments": args}}]}]}
        m, _, _ = openai_to_messages(req)
        self.assertEqual(list(m[0]["tool_calls"][0]["function"]["arguments"]), ["z", "a"])
        self.assertEqual(m[0]["content"], "  text\n")


if __name__ == "__main__":
    unittest.main()
