import json
import threading
import unittest
from unittest.mock import patch

from debate_agent import (
    ChatCompletionClient,
    CompletionResult,
    DebateAgentError,
    DebaterAgent,
    DebateRunner,
    ProviderSettings,
    SpeechResult,
    SummaryAgent,
    SummaryResult,
    ViewpointAgent,
)


class FakeCompletionResponse:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    @staticmethod
    def read():
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {"content": "测试回复"},
                        "finish_reason": "stop",
                    }
                ]
            }
        ).encode("utf-8")


class ChatCompletionClientTests(unittest.TestCase):
    def request_payload_for(self, model):
        settings = ProviderSettings(
            provider="kimi",
            api_url="https://example.invalid/chat/completions",
            api_key="unit-test-key",
            model=model,
        )
        client = ChatCompletionClient(settings)
        with patch("debate_agent.urlopen", return_value=FakeCompletionResponse()) as request:
            client.complete([{"role": "user", "content": "测试"}], max_tokens=800)
        return json.loads(request.call_args.args[0].data.decode("utf-8"))

    def test_kimi_k3_uses_supported_reasoning_parameters(self):
        payload = self.request_payload_for("kimi-k3")

        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertNotIn("thinking", payload)
        self.assertEqual(payload["max_completion_tokens"], 800)

    def test_kimi_k2_6_keeps_non_thinking_mode(self):
        payload = self.request_payload_for("kimi-k2.6")

        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertNotIn("reasoning_effort", payload)


class FakeDebaterAgent:
    calls = []
    opening_viewpoints = []
    received_graphs = []

    def __init__(self, side, provider, model):
        self.side = side

    def opening_statement(self, viewpoints, max_chars, max_tokens):
        self.calls.append(("opening", self.side, 1, ""))
        self.opening_viewpoints.append((self.side, dict(viewpoints)))
        return SpeechResult(content=f"立论 {self.side}", status="completed")

    def speak(
        self,
        topic,
        viewpoints,
        round_number,
        transcript,
        argument_graph,
        max_chars,
        max_tokens,
    ):
        self.calls.append(("debate", self.side, round_number, transcript))
        self.received_graphs.append(
            (self.side, round_number, json.loads(json.dumps(argument_graph)))
        )
        return SpeechResult(
            content=f"第 {round_number} 轮 {self.side}",
            status="completed",
        )


class FakeSummaryAgent:
    calls = []

    def __init__(self, provider, model):
        self.provider = provider
        self.model = model

    def summarize(
        self,
        topic,
        round_number,
        round_speeches,
        existing_graph,
        max_tokens,
    ):
        self.calls.append(
            (self.provider, self.model, round_number, list(round_speeches))
        )
        return SummaryResult(nodes=[], edges=[], status="completed")


class SummaryAgentTests(unittest.TestCase):
    def test_extracts_only_verifiable_nodes_and_valid_relations(self):
        agent = SummaryAgent.__new__(SummaryAgent)

        class FakeClient:
            @staticmethod
            def complete(_messages, max_tokens):
                self.assertEqual(max_tokens, 2400)
                return CompletionResult(
                    content=json.dumps(
                        {
                            "decision": "update",
                            "reason": "",
                            "addNodes": [
                                {
                                    "key": "a_support",
                                    "side": "affirmative",
                                    "kind": "support_evidence",
                                    "text": "技术会提高生产效率",
                                    "sourceSpeechId": "speech_a",
                                    "sourceQuote": "技术会提高生产效率",
                                },
                                {
                                    "key": "n_rebuttal",
                                    "side": "negative",
                                    "kind": "rebuttal_evidence",
                                    "text": "效率提升不等于收益普惠",
                                    "sourceSpeechId": "speech_n",
                                    "sourceQuote": "效率提升不等于收益普惠",
                                },
                                {
                                    "key": "invented",
                                    "side": "negative",
                                    "kind": "support_evidence",
                                    "text": "发言中不存在的材料",
                                    "sourceSpeechId": "speech_n",
                                    "sourceQuote": "并不存在的原文",
                                },
                            ],
                            "addEdges": [
                                {
                                    "from": "a_support",
                                    "to": "node_old",
                                    "type": "supports",
                                },
                                {
                                    "from": "n_rebuttal",
                                    "to": "a_support",
                                    "type": "rebuts",
                                },
                                {
                                    "from": "invented",
                                    "to": "a_support",
                                    "type": "supports",
                                },
                                {
                                    "from": "node_old",
                                    "to": "node_old_2",
                                    "type": "rebuts",
                                },
                            ],
                            "deleteNodeIds": ["node_old_2"],
                            "deleteEdgeIds": [],
                        },
                        ensure_ascii=False,
                    ),
                    finish_reason="stop",
                )

        agent.client = FakeClient()
        result = agent.summarize(
            topic="测试辩题",
            round_number=2,
            round_speeches=[
                {
                    "id": "speech_a",
                    "side": "affirmative",
                    "content": "技术会提高生产效率，并创造新的可能。",
                },
                {
                    "id": "speech_n",
                    "side": "negative",
                    "content": "效率提升不等于收益普惠，需要区分两者。",
                },
            ],
            existing_graph={
                "nodes": [
                    {"id": "node_old", "side": "affirmative", "kind": "core_argument"},
                    {"id": "node_old_2", "side": "negative", "kind": "core_argument"},
                ],
                "edges": [],
            },
            max_tokens=2400,
        )

        self.assertEqual([node["key"] for node in result.nodes], ["a_support", "n_rebuttal"])
        self.assertEqual(
            result.edges,
            [
                {"from": "a_support", "to": "node_old", "type": "supports"},
                {"from": "n_rebuttal", "to": "a_support", "type": "rebuts"},
            ],
        )
        self.assertEqual(result.deleted_node_ids, [])

    def test_retries_an_invalid_opening_tree_once(self):
        agent = SummaryAgent.__new__(SummaryAgent)
        invalid = {
            "decision": "update",
            "reason": "",
            "addNodes": [
                {
                    "key": "a_view",
                    "side": "affirmative",
                    "kind": "viewpoint",
                    "text": "正方观点",
                    "sourceSpeechId": "speech_a",
                    "sourceQuote": "正方观点",
                },
                {
                    "key": "n_view",
                    "side": "negative",
                    "kind": "viewpoint",
                    "text": "反方观点",
                    "sourceSpeechId": "speech_n",
                    "sourceQuote": "反方观点",
                },
            ],
            "addEdges": [],
            "deleteNodeIds": [],
            "deleteEdgeIds": [],
        }
        valid_nodes = []
        for side, speech_id, quote, prefix in (
            ("affirmative", "speech_a", "正方观点", "a"),
            ("negative", "speech_n", "反方观点", "n"),
        ):
            valid_nodes.append(
                {
                    "key": f"{prefix}_view",
                    "side": side,
                    "kind": "viewpoint",
                    "text": quote,
                    "sourceSpeechId": speech_id,
                    "sourceQuote": quote,
                }
            )
            for index in (1, 2):
                valid_nodes.append(
                    {
                        "key": f"{prefix}_core_{index}",
                        "side": side,
                        "kind": "core_argument",
                        "text": f"{quote}核心{index}",
                        "sourceSpeechId": speech_id,
                        "sourceQuote": quote,
                    }
                )
        valid = {
            "decision": "update",
            "reason": "",
            "addNodes": valid_nodes,
            "addEdges": [
                {"from": f"{prefix}_core_{index}", "to": f"{prefix}_view", "type": "supports"}
                for prefix in ("a", "n")
                for index in (1, 2)
            ],
            "deleteNodeIds": [],
            "deleteEdgeIds": [],
        }

        class FakeClient:
            calls = 0

            @classmethod
            def complete(cls, _messages, max_tokens):
                cls.calls += 1
                self.assertEqual(max_tokens, 2400)
                payload = invalid if cls.calls == 1 else valid
                return CompletionResult(content=json.dumps(payload, ensure_ascii=False), finish_reason="stop")

        agent.client = FakeClient()
        result = agent.summarize(
            topic="测试辩题",
            round_number=1,
            round_speeches=[
                {"id": "speech_a", "side": "affirmative", "content": "正方观点"},
                {"id": "speech_n", "side": "negative", "content": "反方观点"},
            ],
            existing_graph={"nodes": [], "edges": []},
            max_tokens=2400,
        )

        self.assertEqual(FakeClient.calls, 2)
        self.assertEqual(len(result.nodes), 6)
        self.assertEqual(len(result.edges), 4)

    def test_refuses_an_off_topic_round_without_graph_changes(self):
        agent = SummaryAgent.__new__(SummaryAgent)

        class FakeClient:
            @staticmethod
            def complete(_messages, max_tokens):
                self.assertEqual(max_tokens, 2400)
                return CompletionResult(
                    content=json.dumps(
                        {
                            "decision": "refuse",
                            "reason": "本轮讨论与既有核心论点没有明确逻辑关系",
                            "addNodes": [],
                            "addEdges": [],
                            "deleteNodeIds": [],
                            "deleteEdgeIds": [],
                        },
                        ensure_ascii=False,
                    ),
                    finish_reason="stop",
                )

        agent.client = FakeClient()
        result = agent.summarize(
            topic="测试辩题",
            round_number=2,
            round_speeches=[
                {"id": "speech_a", "side": "affirmative", "content": "讨论别的话题"},
                {"id": "speech_n", "side": "negative", "content": "继续讨论别的话题"},
            ],
            existing_graph={"nodes": [], "edges": []},
            max_tokens=2400,
        )

        self.assertEqual(result.decision, "refuse")
        self.assertTrue(result.reason)
        self.assertEqual(result.nodes, [])
        self.assertEqual(result.edges, [])

    def test_holds_the_graph_without_ending_when_evidence_resources_are_full(self):
        agent = SummaryAgent.__new__(SummaryAgent)

        class FakeClient:
            @staticmethod
            def complete(_messages, max_tokens):
                self.assertEqual(max_tokens, 2400)
                return CompletionResult(
                    content=json.dumps(
                        {
                            "decision": "hold",
                            "reason": "论据资源已满，本轮没有比现有节点更值得替换的论据",
                            "addNodes": [],
                            "addEdges": [],
                            "deleteNodeIds": [],
                            "deleteEdgeIds": [],
                        },
                        ensure_ascii=False,
                    ),
                    finish_reason="stop",
                )

        agent.client = FakeClient()
        result = agent.summarize(
            topic="测试辩题",
            round_number=3,
            round_speeches=[
                {"id": "speech_a", "side": "affirmative", "content": "补充讨论核心论点"},
                {"id": "speech_n", "side": "negative", "content": "回应核心论点"},
            ],
            existing_graph={
                "nodes": (
                    [
                        {"id": f"support_{index}", "side": "affirmative", "kind": "support_evidence"}
                        for index in range(SummaryAgent.EVIDENCE_LIMITS["support_evidence"])
                    ]
                    + [
                        {"id": f"rebuttal_{index}", "side": "negative", "kind": "rebuttal_evidence"}
                        for index in range(SummaryAgent.EVIDENCE_LIMITS["rebuttal_evidence"])
                    ]
                ),
                "edges": [],
            },
            max_tokens=2400,
        )

        self.assertEqual(result.decision, "hold")
        self.assertEqual(result.nodes, [])
        self.assertEqual(result.edges, [])

    def test_enforces_separate_support_and_rebuttal_resource_pools(self):
        existing_nodes = [
            {"id": "a_core", "side": "affirmative", "kind": "core_argument"},
            {"id": "n_core", "side": "negative", "kind": "core_argument"},
        ]
        existing_nodes.extend(
            {
                "id": f"support_{index}",
                "side": "affirmative",
                "kind": "support_evidence",
            }
            for index in range(SummaryAgent.EVIDENCE_LIMITS["support_evidence"])
        )
        existing_nodes.extend(
            {
                "id": f"rebuttal_{index}",
                "side": "negative",
                "kind": "rebuttal_evidence",
            }
            for index in range(9)
        )

        nodes, edges, _, _ = SummaryAgent._validate_update(
            {
                "addNodes": [
                    {
                        "key": "new_support",
                        "side": "affirmative",
                        "kind": "support_evidence",
                        "text": "新增支持",
                        "sourceSpeechId": "speech_a",
                        "sourceQuote": "新增支持",
                    },
                    {
                        "key": "new_rebuttal",
                        "side": "affirmative",
                        "kind": "rebuttal_evidence",
                        "text": "新增反驳",
                        "sourceSpeechId": "speech_a",
                        "sourceQuote": "新增反驳",
                    },
                ],
                "addEdges": [
                    {"from": "new_support", "to": "a_core", "type": "supports"},
                    {"from": "new_rebuttal", "to": "n_core", "type": "rebuts"},
                ],
                "deleteNodeIds": [],
                "deleteEdgeIds": [],
            },
            round_number=2,
            round_speeches=[
                {
                    "id": "speech_a",
                    "side": "affirmative",
                    "content": "新增支持，同时提出新增反驳。",
                }
            ],
            existing_graph={"nodes": existing_nodes, "edges": []},
        )

        self.assertEqual([node["key"] for node in nodes], ["new_rebuttal"])
        self.assertEqual(
            edges,
            [{"from": "new_rebuttal", "to": "n_core", "type": "rebuts"}],
        )

    def test_accepts_quote_when_speech_only_wraps_it_in_markdown(self):
        nodes, edges, _, _ = SummaryAgent._validate_update(
            {
                "addNodes": [
                    {
                        "key": "a_support",
                        "side": "affirmative",
                        "kind": "support_evidence",
                        "text": "这是一项关键依据",
                        "sourceSpeechId": "speech_a",
                        "sourceQuote": "这是一项关键依据",
                    }
                ],
                "addEdges": [
                    {"from": "a_support", "to": "a_core", "type": "supports"}
                ],
                "deleteNodeIds": [],
                "deleteEdgeIds": [],
            },
            round_number=2,
            round_speeches=[
                {
                    "id": "speech_a",
                    "side": "affirmative",
                    "content": "**这是一项关键依据**，能支撑此前的核心论点。",
                }
            ],
            existing_graph={
                "nodes": [
                    {"id": "a_core", "side": "affirmative", "kind": "core_argument"}
                ],
                "edges": [],
            },
        )

        self.assertEqual([node["key"] for node in nodes], ["a_support"])
        self.assertEqual(edges, [{"from": "a_support", "to": "a_core", "type": "supports"}])


class ViewpointAgentTests(unittest.TestCase):
    def test_generates_two_short_viewpoints_from_json(self):
        agent = ViewpointAgent.__new__(ViewpointAgent)

        class FakeClient:
            @staticmethod
            def complete(_messages, max_tokens):
                self.assertEqual(max_tokens, 400)
                return CompletionResult(
                    content='```json\n{"affirmative":"技术利大于弊","negative":"技术弊大于利"}\n```',
                    finish_reason="stop",
                )

        agent.client = FakeClient()
        result = agent.generate("讨论技术影响", max_tokens=400)

        self.assertEqual(result.affirmative, "技术利大于弊")
        self.assertEqual(result.negative, "技术弊大于利")

    def test_rejects_viewpoints_over_fifty_characters(self):
        agent = ViewpointAgent.__new__(ViewpointAgent)

        class FakeClient:
            @staticmethod
            def complete(_messages, max_tokens):
                return CompletionResult(
                    content=json.dumps(
                        {"affirmative": "正" * 26, "negative": "反" * 25},
                        ensure_ascii=False,
                    ),
                    finish_reason="stop",
                )

        agent.client = FakeClient()
        with self.assertRaisesRegex(DebateAgentError, "超过 50 字"):
            agent.generate("测试", max_tokens=400)


class DebateRunnerTests(unittest.TestCase):
    def test_debater_keeps_complete_provider_text_over_target_length(self):
        agent = DebaterAgent.__new__(DebaterAgent)
        agent.side = "affirmative"
        agent.side_label = "正方"
        captured_messages = []

        class FakeClient:
            @staticmethod
            def complete(messages, max_tokens):
                self.assertEqual(max_tokens, 1600)
                captured_messages.extend(messages)
                return CompletionResult(content="完整发言" * 200, finish_reason="stop")

        agent.client = FakeClient()
        result = agent.speak(
            topic="测试辩题",
            viewpoints={"affirmative": "支持", "negative": "反对"},
            round_number=1,
            transcript="",
            argument_graph={
                "nodes": [],
                "edges": [],
                "updatedThroughRound": 1,
                "resources": {
                    "supportEvidence": {"used": 1, "limit": 4, "remaining": 3},
                    "rebuttalEvidence": {"used": 2, "limit": 10, "remaining": 8},
                },
            },
            max_chars=600,
            max_tokens=1600,
        )

        self.assertEqual(result.content, "完整发言" * 200)
        self.assertEqual(result.status, "completed")
        self.assertIn('"supportEvidence":{"used":1,"limit":4,"remaining":3}', captured_messages[1]["content"])

    def test_alternates_side_order_and_sends_latest_graph_to_both_debaters(self):
        stop_event = threading.Event()
        pause_event = threading.Event()
        record = {
            "topic": "测试辩题",
            "status": "running",
            "phase": "opening",
            "currentRound": 1,
            "affirmative": {"provider": "kimi", "model": "test"},
            "negative": {"provider": "deepseek", "model": "test"},
            "summarizer": {"provider": "kimi", "model": "summary-test"},
            "viewpoints": {"affirmative": "正方观点", "negative": "反方观点"},
            "speeches": [],
            "roundSummaries": [],
            "argumentGraph": {"nodes": [], "edges": [], "updatedThroughRound": 0},
        }
        FakeDebaterAgent.calls = []
        FakeDebaterAgent.opening_viewpoints = []
        FakeDebaterAgent.received_graphs = []
        FakeSummaryAgent.calls = []

        def load_record(_record_id):
            return record

        def mark_turn(_record_id, round_number, side, phase):
            record["currentRound"] = round_number
            record["currentSpeaker"] = side
            record["phase"] = phase

        def save_speech(_record_id, round_number, side, result, phase):
            record["speeches"].append(
                {
                    "id": f"speech_{round_number}_{side}",
                    "round": round_number,
                    "side": side,
                    "phase": phase,
                    "content": result.content,
                }
            )

        def save_summary(_record_id, round_number, result):
            record["roundSummaries"].append(
                {"round": round_number, "status": result.status}
            )
            record["argumentGraph"] = {
                "nodes": [{"id": f"graph_after_round_{round_number}"}],
                "edges": [],
                "updatedThroughRound": round_number,
            }
            if len(record["roundSummaries"]) == 3:
                stop_event.set()

        def advance_phase(_record_id, phase, round_number):
            record["phase"] = phase
            record["currentRound"] = round_number
            record["currentSpeaker"] = None

        runner = DebateRunner(
            record_id="test",
            stop_event=stop_event,
            pause_event=pause_event,
            load_record=load_record,
            mark_turn=mark_turn,
            save_speech=save_speech,
            save_summary=save_summary,
            advance_phase=advance_phase,
            mark_paused=lambda *_args: None,
            mark_error=lambda *_args: self.fail("runner should not fail"),
            mark_stopped=lambda *_args: None,
        )
        runner.turn_pause = 0

        with patch("debate_agent.DebaterAgent", FakeDebaterAgent), patch(
            "debate_agent.SummaryAgent", FakeSummaryAgent
        ):
            runner.run()

        self.assertEqual(
            [(phase, side, round_number) for phase, side, round_number, _ in FakeDebaterAgent.calls],
            [
                ("opening", "affirmative", 1),
                ("opening", "negative", 1),
                ("debate", "negative", 2),
                ("debate", "affirmative", 2),
                ("debate", "affirmative", 3),
                ("debate", "negative", 3),
            ],
        )
        self.assertEqual(
            [round_number for _, _, round_number, _ in FakeSummaryAgent.calls],
            [1, 2, 3],
        )
        self.assertEqual(
            [(speech["side"], speech["round"]) for speech in FakeSummaryAgent.calls[0][3]],
            [("affirmative", 1), ("negative", 1)],
        )
        self.assertEqual(
            [viewpoints for _, viewpoints in FakeDebaterAgent.opening_viewpoints],
            [record["viewpoints"], record["viewpoints"]],
        )
        self.assertEqual(FakeDebaterAgent.calls[0][3], "")
        self.assertEqual(FakeDebaterAgent.calls[1][3], "")
        self.assertIn("立论阶段 · 正方", FakeDebaterAgent.calls[3][3])
        self.assertEqual(record["speeches"][0]["phase"], "opening")
        self.assertEqual(record["speeches"][2]["phase"], "debate")
        self.assertEqual(
            [
                (side, round_number, graph["updatedThroughRound"])
                for side, round_number, graph in FakeDebaterAgent.received_graphs
            ],
            [
                ("negative", 2, 1),
                ("affirmative", 2, 1),
                ("affirmative", 3, 2),
                ("negative", 3, 2),
            ],
        )

    def test_pause_finishes_current_speaker_before_waiting(self):
        stop_event = threading.Event()
        pause_event = threading.Event()
        paused = threading.Event()
        negative_saved = threading.Event()
        calls = []
        record = {
            "topic": "测试暂停",
            "status": "running",
            "phase": "opening",
            "currentRound": 1,
            "affirmative": {"provider": "kimi", "model": "test"},
            "negative": {"provider": "deepseek", "model": "test"},
            "summarizer": {"provider": "kimi", "model": "summary-test"},
            "viewpoints": {"affirmative": "正方观点", "negative": "反方观点"},
            "speeches": [],
            "argumentGraph": {"nodes": [], "edges": [], "updatedThroughRound": 0},
        }

        class PausingAgent:
            def __init__(self, side, provider, model):
                self.side = side

            def opening_statement(self, **_kwargs):
                calls.append(self.side)
                if self.side == "affirmative":
                    pause_event.set()
                return SpeechResult(content=self.side, status="completed")

        def save_speech(_record_id, round_number, side, result, phase):
            record["speeches"].append(
                {"round": round_number, "side": side, "phase": phase, "content": result.content}
            )
            if side == "negative":
                negative_saved.set()
                stop_event.set()

        def mark_paused(_record_id):
            record["status"] = "paused"
            paused.set()

        runner = DebateRunner(
            record_id="test",
            stop_event=stop_event,
            pause_event=pause_event,
            load_record=lambda _record_id: record,
            mark_turn=lambda *_args: None,
            save_speech=save_speech,
            save_summary=lambda *_args: None,
            advance_phase=lambda *_args: None,
            mark_paused=mark_paused,
            mark_error=lambda *_args: self.fail("runner should not fail"),
            mark_stopped=lambda *_args: None,
        )
        runner.turn_pause = 0

        with patch("debate_agent.DebaterAgent", PausingAgent):
            thread = threading.Thread(target=runner.run)
            thread.start()
            self.assertTrue(paused.wait(1))
            self.assertEqual(calls, ["affirmative"])
            self.assertEqual(len(record["speeches"]), 1)

            record["status"] = "running"
            pause_event.clear()
            self.assertTrue(negative_saved.wait(1))
            thread.join(timeout=1)

        self.assertEqual(calls, ["affirmative", "negative"])


if __name__ == "__main__":
    unittest.main()
