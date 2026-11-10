"""HTTP regressions for local tool histories, budgets, counting and Codex tools."""
from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from serve.frontend import ChatTemplate, anthropic_to_messages, openai_to_messages
from serve.server import ByteTokenizer, MockEngine, Service, serve

ROOT = Path(__file__).resolve().parents[1]
TOOL = {"name": "lookup", "description": "test lookup", "parameters": {
    "type": "object", "properties": {"city": {"type": "string"}}, "required": ["city"]}}


class CaptureEngine(MockEngine):
    def generate(self, ids, max_new, sampling, cancel, embeddings=None):
        self.sampling = dict(sampling or {})
        yield from super().generate(ids, max_new, sampling, cancel, embeddings)


class ToolHistories(unittest.TestCase):
    def history(self, api):
        if api == "anthropic":
            return {"messages": [{"role": "assistant", "content": [
                {"type": "tool_use", "id": "a", "name": "lookup", "input": {"city": "A"}},
                {"type": "tool_use", "id": "b", "name": "lookup", "input": {"city": "B"}}]},
                {"role": "user", "content": [
                    {"type": "tool_result", "tool_use_id": "b", "content": "RESULT_B"},
                    {"type": "tool_result", "tool_use_id": "a", "content": "RESULT_A"}]}]}
        return {"messages": [{"role": "assistant", "content": None, "tool_calls": [
            {"id": "a", "function": {"name": "lookup", "arguments": '{"city":"A"}'}},
            {"id": "b", "function": {"name": "lookup", "arguments": '{"city":"B"}'}}]},
            {"role": "tool", "tool_call_id": "b", "content": "RESULT_B"},
            {"role": "tool", "tool_call_id": "a", "content": "RESULT_A"}]}

    def test_parallel_results_keep_ids_and_match_calls(self):
        for api, convert in (("anthropic", anthropic_to_messages), ("openai", openai_to_messages)):
            with self.subTest(api=api):
                m, _, _ = convert(self.history(api))
                self.assertEqual([c["id"] for c in m[0]["tool_calls"]], ["a", "b"])
                self.assertEqual([(x["tool_call_id"], x["content"]) for x in m[1:]],
                                 [("a", "RESULT_A"), ("b", "RESULT_B")])
                templates = [ROOT / "serve/chat_template.jinja"]
                actual = Path("D:/AI/lla_models/gguf/Maya-M/pack/tokenizer/chat_template.jinja")
                if actual.exists():
                    templates.append(actual)
                for p in templates:
                    text = ChatTemplate(p).render(m)
                    self.assertLess(text.index("RESULT_A"), text.index("RESULT_B"))

    def test_unknown_and_duplicate_result_ids_rejected(self):
        for convert, api in ((anthropic_to_messages, "anthropic"), (openai_to_messages, "openai")):
            for bad in ("unknown", "b"):
                req = self.history(api)
                if api == "anthropic":
                    req["messages"][1]["content"][1]["tool_use_id"] = bad
                else:
                    req["messages"][2]["tool_call_id"] = bad
                with self.assertRaisesRegex(ValueError, "unknown or duplicate"):
                    convert(req)

    def test_error_status_is_visible_to_model(self):
        req = self.history("anthropic")
        req["messages"][1]["content"][0]["is_error"] = True
        messages, _, _ = anthropic_to_messages(req)
        self.assertIn("[Tool execution failed]", messages[2]["content"])
        self.assertNotIn("failed", messages[1]["content"])


class ApiHttp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tok = ByteTokenizer()
        cls.engine = CaptureEngine(cls.tok, "</think>OK", max_context=65536)
        cls.svc = Service(cls.engine, cls.tok, ChatTemplate(ROOT / "serve/chat_template.jinja"), model_name="test")
        cls.svc.think_budget = 32768
        cls.svc.think_end_id = 999999
        cls.httpd = serve(cls.svc, port=0)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def setUp(self):
        self.script("</think>OK")
        self.svc.shared = {}
        self.svc.default_effort = None
        self.svc.api_key = ""

    def script(self, text):
        self.engine.scripts = [self.tok.encode(text, parse_special=True) + self.tok.encode("<|im_end|>", parse_special=True)]
        self.engine.script = self.engine.scripts[0]

    def post(self, path, body, raw=False, headers=None):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                data = r.read()
                return r.status, data.decode("utf-8") if raw else json.loads(data)
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def body(self):
        return {"model": "test", "messages": [{"role": "user", "content": "test"}], "max_tokens": 8192}

    def test_anthropic_budget_reaches_engine_and_is_request_local(self):
        req = self.body()
        req["thinking"] = {"type": "enabled", "budget_tokens": 1024}
        self.assertEqual(self.post("/v1/messages", req)[0], 200)
        self.assertEqual(self.engine.sampling["_think_budget"], 1024)
        self.assertEqual(self.svc.history[-1]["thinking_budget"], 1024)
        self.assertGreaterEqual(self.svc.history[-1]["queue_ms"], 0)
        self.post("/v1/messages", self.body())
        self.assertEqual(self.engine.sampling["_think_budget"], 6144)

    def test_disabled_thinking_sends_no_budget(self):
        req = self.body()
        req["thinking"] = {"type": "disabled"}
        self.post("/v1/messages", req)
        self.assertNotIn("_think_budget", self.engine.sampling)

    def test_budget_is_validated_before_stream_starts(self):
        for value in (0, -1, True, "1024", 1.5):
            req = {**self.body(), "stream": True, "thinking": {"type": "enabled", "budget_tokens": value}}
            self.assertEqual(self.post("/v1/messages", req)[0], 400)

    def test_openai_budget_extension(self):
        self.post("/v1/chat/completions", {**self.body(), "thinking_budget": 512})
        self.assertEqual(self.engine.sampling["_think_budget"], 512)

    def test_responses_preserves_local_budget_extension(self):
        status, result = self.post("/v1/responses", {"input": "test", "max_output_tokens": 2048,
            "reasoning": {"effort": "low"}, "thinking_budget": 512, "store": False})
        self.assertEqual(status, 200, result)
        self.assertEqual(self.engine.sampling["_think_budget"], 512)
        self.assertEqual(self.svc.history[-1]["thinking_budget"], 512)

    def test_standard_count_uses_anthropic_system_tools_and_defaults(self):
        req = {**self.body(), "system": [{"type": "text", "text": "system only"}],
               "thinking": {"type": "disabled"},
               "tools": [{"name": TOOL["name"], "input_schema": TOOL["parameters"]}]}
        self.svc.default_effort = "high"
        status, result = self.post("/v1/messages/count_tokens?beta=true", req)
        self.assertEqual(status, 200)
        self.post("/v1/messages", req)
        self.assertEqual(result["input_tokens"], len(self.engine.last_prompt))

    def test_count_forced_tool_matches_generation_prefix(self):
        req = {**self.body(), "tools": [{"name": "lookup", "input_schema": TOOL["parameters"]}],
               "tool_choice": {"type": "tool", "name": "lookup"}}
        count = self.post("/v1/messages/count_tokens", req)[1]["input_tokens"]
        # Only the prompt matters, so a scripted malformed completion is harmless here.
        self.post("/v1/messages", req)
        self.assertEqual(count, len(self.engine.last_prompt))

    def test_count_does_not_wait_for_engine(self):
        self.svc.fifo.acquire()
        try:
            self.assertEqual(self.post("/v1/messages/count_tokens", self.body())[0], 200)
        finally:
            self.svc.fifo.release()

    def test_responses_text_stream_and_terminal_items_agree(self):
        req = {"model": "test", "input": "hello", "max_output_tokens": 256,
               "reasoning": {"effort": "none"}, "store": False}
        self.script("Hello 中文")
        status, nonstream = self.post("/v1/responses", req)
        self.assertEqual(status, 200)
        self.assertEqual(nonstream["status"], "completed")
        self.assertEqual(nonstream["output"][0]["content"][0]["text"], "Hello 中文")
        status, raw = self.post("/v1/responses", {**req, "stream": True}, raw=True)
        evs = [json.loads(x[6:]) for x in raw.splitlines() if x.startswith("data: ")]
        self.assertEqual(evs[0]["type"], "response.created")
        self.assertEqual(evs[-1]["type"], "response.completed")
        self.assertEqual([e["sequence_number"] for e in evs], list(range(len(evs))))
        self.assertEqual("".join(e["delta"] for e in evs if e["type"] == "response.output_text.delta"), "Hello 中文")
        done = next(e["item"] for e in evs if e["type"] == "response.output_item.done")
        self.assertEqual(done, evs[-1]["response"]["output"][0])

    def test_responses_tool_round_trip(self):
        self.script('</think><tool_call>\n<function=lookup>\n<parameter=city>\nA\n</parameter>\n</function>\n</tool_call>')
        req = {"model": "test", "input": "lookup A", "max_output_tokens": 2048,
               "tools": [{"type": "function", **TOOL}], "store": False}
        status, first = self.post("/v1/responses", req)
        self.assertEqual(status, 200)
        call = next(i for i in first["output"] if i["type"] == "function_call")
        self.assertEqual(json.loads(call["arguments"]), {"city": "A"})
        self.script("</think>received")
        req["input"] = [{"role": "user", "content": "lookup A"}, *first["output"],
                        {"type": "function_call_output", "call_id": call["call_id"], "output": "RESULT_A"}]
        status, second = self.post("/v1/responses", req)
        self.assertEqual(status, 200)
        self.assertIn("RESULT_A", self.tok.decode(self.engine.last_prompt))
        self.assertEqual(second["status"], "completed")

    def test_responses_custom_input_and_output(self):
        self.script('</think><tool_call>\n<function=test_patch>\n<parameter=input>\nline1\nline2\n</parameter>\n</function>\n</tool_call>')
        req = {"model": "test", "input": "test", "max_output_tokens": 2048,
               "tools": [{"type": "custom", "name": "test_patch", "format": {"type": "text"}}]}
        status, raw = self.post("/v1/responses", {**req, "stream": True}, raw=True)
        self.assertEqual(status, 200)
        events = [json.loads(x[6:]) for x in raw.splitlines() if x.startswith("data: ")]
        item = next(e["item"] for e in events if e["type"] == "response.output_item.done" and
                    e["item"]["type"] == "custom_tool_call")
        self.assertEqual(item["input"], "line1\nline2")
        self.assertEqual(next(e["delta"] for e in events if e["type"] == "response.custom_tool_call_input.delta"),
                         item["input"])
        self.script("</think>done")
        req["input"] = [{"role": "user", "content": "test"}, item,
                        {"type": "custom_tool_call_output", "call_id": item["call_id"], "output": "patched"}]
        self.assertEqual(self.post("/v1/responses", req)[0], 200)

    def test_responses_max_tokens_is_incomplete(self):
        self.script("abcdefghij")
        status, result = self.post("/v1/responses", {"input": "test", "max_output_tokens": 3,
                                                     "reasoning": {"effort": "none"}})
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["incomplete_details"], {"reason": "max_output_tokens"})

    def test_namespaced_tool_round_trip_keeps_namespace(self):
        self.script('</think><tool_call>\n<function=crm__lookup>\n<parameter=city>\nA\n</parameter>\n</function>\n</tool_call>')
        req = {"input": "test", "max_output_tokens": 2048, "tools": [
            {"type": "namespace", "name": "crm", "description": "CRM", "tools": [{"type": "function", **TOOL}]}]}
        status, result = self.post("/v1/responses", req)
        self.assertEqual(status, 200)
        call = next(i for i in result["output"] if i["type"] == "function_call")
        self.assertEqual((call["namespace"], call["name"]), ("crm", "lookup"))
        self.script("</think>received")
        req["input"] = [{"role": "user", "content": "test"}, call,
                        {"type": "function_call_output", "call_id": call["call_id"], "output": "RESULT"}]
        self.assertEqual(self.post("/v1/responses", req)[0], 200)
        self.assertIn("crm__lookup", self.tok.decode(self.engine.last_prompt))

    def test_namespaced_custom_tool_and_choice(self):
        self.script("payload\n</parameter>\n</function>\n</tool_call>")
        req = {"input": "test", "max_output_tokens": 2048, "tools": [{"type": "namespace", "name": "edit",
            "description": "edit tools", "tools": [{"type": "custom", "name": "patch"}]}],
            "tool_choice": {"type": "custom", "namespace": "edit", "name": "patch"}}
        # The forced call's opening is already part of the model's prompt.
        self.script("<parameter=input>\npayload\n</parameter>\n</function>\n</tool_call>")
        status, result = self.post("/v1/responses", req)
        self.assertEqual(status, 200)
        call = next(i for i in result["output"] if i["type"] == "custom_tool_call")
        self.assertEqual((call["namespace"], call["name"], call["input"]), ("edit", "patch", "payload"))

    def test_model_list_preserves_openai_and_codex_shapes(self):
        with urllib.request.urlopen(self.base + "/v1/models?client_version=test", timeout=10) as r:
            models = json.loads(r.read())
        self.assertEqual(models["data"][0]["id"], "test")
        self.assertEqual(models["data"][0]["owned_by"], "local")
        self.assertIsInstance(models["data"][0]["created"], int)
        self.assertEqual(models["models"][0]["slug"], "test")
        self.assertEqual(models["models"][0]["context_window"], self.engine.max_context)

    def test_responses_rejects_unsupported_input_without_generating(self):
        for extra in ({"background": True, "store": False},
                      {"input": [{"type": "item_reference", "id": "item_old"}]},
                      {"tools": [{"type": "web_search"}]}, {"max_output_tokens": True}):
            with self.subTest(extra=extra):
                self.assertEqual(self.post("/v1/responses", {"input": "test", "stream": True, **extra})[0], 400)

    def test_missing_previous_response_is_not_found(self):
        self.assertEqual(self.post("/v1/responses", {"input": "test", "previous_response_id": "resp_old"})[0], 404)

    def test_stored_namespaced_custom_call_can_be_continued(self):
        self.script("<parameter=input>\npayload\n</parameter>\n</function>\n</tool_call>")
        tools = [{"type": "namespace", "name": "edit", "tools": [{"type": "custom", "name": "patch"}]}]
        status, first = self.post("/v1/responses", {"input": "test", "store": True, "tools": tools,
            "tool_choice": {"type": "custom", "namespace": "edit", "name": "patch"}, "max_output_tokens": 2048})
        self.assertEqual(status, 200, first)
        call = next(i for i in first["output"] if i["type"] == "custom_tool_call")
        self.assertEqual((call["namespace"], call["name"], call["input"]), ("edit", "patch", "payload"))
        self.script("</think>received")
        status, second = self.post("/v1/responses", {"store": True, "tools": tools,
            "previous_response_id": first["id"], "max_output_tokens": 2048,
            "input": [{"type": "custom_tool_call_output", "call_id": call["call_id"], "output": "test_patched"}]})
        self.assertEqual(status, 200, second)
        self.assertEqual(second["status"], "completed")
        self.assertIn("test_patched", self.tok.decode(self.engine.last_prompt))

    def test_codex_summary_preference_is_accepted(self):
        status, result = self.post("/v1/responses", {"input": "test", "max_output_tokens": 256,
            "reasoning": {"effort": "none", "summary": "auto"}, "store": False})
        self.assertEqual(status, 200, result)
        self.assertEqual(result["reasoning"]["summary"], "auto")

    def test_new_endpoints_use_existing_authentication(self):
        self.svc.api_key = "test_secret"
        for path in ("/v1/responses", "/v1/messages/count_tokens"):
            self.assertEqual(self.post(path, {"input": "test"})[0], 401)


if __name__ == "__main__":
    unittest.main()
