import threading
import unittest
from unittest.mock import patch

from debate_agent import CompletionResult, DebaterAgent, DebateRunner, SpeechResult


class FakeDebaterAgent:
    calls = []

    def __init__(self, side, provider, model):
        self.side = side

    def speak(self, topic, round_number, transcript, max_chars, max_tokens):
        self.calls.append((self.side, round_number, transcript))
        return SpeechResult(
            content=f"第 {round_number} 轮 {self.side}",
            status="completed",
        )


class DebateRunnerTests(unittest.TestCase):
    def test_debater_keeps_complete_provider_text_over_target_length(self):
        agent = DebaterAgent.__new__(DebaterAgent)
        agent.side = "affirmative"
        agent.side_label = "正方"

        class FakeClient:
            @staticmethod
            def complete(_messages, max_tokens):
                self.assertEqual(max_tokens, 1600)
                return CompletionResult(content="完整发言" * 200, finish_reason="stop")

        agent.client = FakeClient()
        result = agent.speak(
            topic="测试辩题",
            round_number=1,
            transcript="",
            max_chars=600,
            max_tokens=1600,
        )

        self.assertEqual(result.content, "完整发言" * 200)
        self.assertEqual(result.status, "completed")

    def test_repeats_the_same_affirmative_negative_round(self):
        stop_event = threading.Event()
        pause_event = threading.Event()
        record = {
            "topic": "测试辩题",
            "status": "running",
            "currentRound": 1,
            "affirmative": {"provider": "kimi", "model": "test"},
            "negative": {"provider": "deepseek", "model": "test"},
            "speeches": [],
        }
        FakeDebaterAgent.calls = []

        def load_record(_record_id):
            return record

        def mark_turn(_record_id, round_number, side):
            record["currentRound"] = round_number
            record["currentSpeaker"] = side

        def save_speech(_record_id, round_number, side, result):
            record["speeches"].append(
                {"round": round_number, "side": side, "content": result.content}
            )
            if len(record["speeches"]) == 4:
                stop_event.set()

        runner = DebateRunner(
            record_id="test",
            stop_event=stop_event,
            pause_event=pause_event,
            load_record=load_record,
            mark_turn=mark_turn,
            save_speech=save_speech,
            mark_paused=lambda *_args: None,
            mark_error=lambda *_args: self.fail("runner should not fail"),
            mark_stopped=lambda *_args: None,
        )
        runner.turn_pause = 0

        with patch("debate_agent.DebaterAgent", FakeDebaterAgent):
            runner.run()

        self.assertEqual(
            [(side, round_number) for side, round_number, _ in FakeDebaterAgent.calls],
            [
                ("affirmative", 1),
                ("negative", 1),
                ("affirmative", 2),
                ("negative", 2),
            ],
        )
        self.assertIn("第 1 轮 · 正方", FakeDebaterAgent.calls[1][2])
        self.assertNotIn("phase", record["speeches"][0])

    def test_pause_finishes_current_speaker_before_waiting(self):
        stop_event = threading.Event()
        pause_event = threading.Event()
        paused = threading.Event()
        negative_saved = threading.Event()
        calls = []
        record = {
            "topic": "测试暂停",
            "status": "running",
            "currentRound": 1,
            "affirmative": {"provider": "kimi", "model": "test"},
            "negative": {"provider": "deepseek", "model": "test"},
            "speeches": [],
        }

        class PausingAgent:
            def __init__(self, side, provider, model):
                self.side = side

            def speak(self, **_kwargs):
                calls.append(self.side)
                if self.side == "affirmative":
                    pause_event.set()
                return SpeechResult(content=self.side, status="completed")

        def save_speech(_record_id, round_number, side, result):
            record["speeches"].append(
                {"round": round_number, "side": side, "content": result.content}
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
