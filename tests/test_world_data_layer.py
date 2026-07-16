"""World 数据层单元测试：WorldStage 在场映射与 SharedTranscript 场景分片。"""

import asyncio
import unittest

from GensokyoAI.world import (
    USER_OCCUPANT_ID,
    DirectorAction,
    DirectorDecision,
    SharedTranscript,
    SpeakerKind,
    WorldStage,
    WorldStateSnapshot,
)


class WorldStageTests(unittest.TestCase):
    def test_characters_in_excludes_user(self):
        stage = WorldStage(
            {
                "marisa": "scarlet_devil_mansion",
                "patchouli": "scarlet_devil_mansion",
                USER_OCCUPANT_ID: "scarlet_devil_mansion",
                "reimu": "hakurei_shrine",
            }
        )

        chars = stage.characters_in("scarlet_devil_mansion")
        self.assertEqual(chars, ["marisa", "patchouli"])
        self.assertNotIn(USER_OCCUPANT_ID, chars)

    def test_visible_actor_ids_excludes_self_and_offscene(self):
        stage = WorldStage(
            {
                "marisa": "scarlet_devil_mansion",
                "patchouli": "scarlet_devil_mansion",
                "reimu": "hakurei_shrine",
                USER_OCCUPANT_ID: "scarlet_devil_mansion",
            }
        )

        # 用户视角：同场的 marisa / patchouli 可见，reimu 不在场
        visible = stage.visible_actor_ids(USER_OCCUPANT_ID)
        self.assertEqual(visible, ["marisa", "patchouli"])
        # 角色视角：排除自己
        self.assertEqual(stage.visible_actor_ids("marisa"), ["patchouli"])
        # 不在场占位无可见角色
        self.assertEqual(stage.visible_actor_ids("unknown"), [])

    def test_move_together_is_atomic(self):
        async def scenario():
            stage = WorldStage({"marisa": "magic_forest", USER_OCCUPANT_ID: "magic_forest"})
            await stage.move_together(["marisa", USER_OCCUPANT_ID], "scarlet_devil_mansion")
            return stage

        stage = asyncio.run(scenario())
        self.assertEqual(stage.scene_of("marisa"), "scarlet_devil_mansion")
        self.assertEqual(stage.scene_of(USER_OCCUPANT_ID), "scarlet_devil_mansion")
        # 移动后原场景已无人
        self.assertEqual(stage.characters_in("magic_forest"), [])

    def test_concurrent_moves_do_not_corrupt_state(self):
        async def scenario():
            stage = WorldStage()
            # 100 个并发移动，锁保证每次写入原子、最终状态自洽
            await asyncio.gather(*(stage.move(f"a{i}", f"scene{i % 3}") for i in range(100)))
            return stage

        stage = asyncio.run(scenario())
        total = sum(len(stage.characters_in(f"scene{s}")) for s in range(3))
        self.assertEqual(total, 100)


class SharedTranscriptTests(unittest.TestCase):
    def _mansion_transcript(self) -> SharedTranscript:
        t = SharedTranscript()
        t.add(
            scene_id="scarlet_devil_mansion",
            speaker_kind=SpeakerKind.CHARACTER,
            speaker_id="marisa",
            speaker_name="雾雨魔理沙",
            content="你看，这就是红魔馆地下大图书馆",
        )
        t.add(
            scene_id="magic_forest",
            speaker_kind=SpeakerKind.CHARACTER,
            speaker_id="alice",
            speaker_name="爱丽丝",
            content="魔法森林里的秘密不该被外人知道",
        )
        return t

    def test_transcript_is_partitioned_by_scene(self):
        t = self._mansion_transcript()

        mansion = t.history("scarlet_devil_mansion")
        forest = t.history("magic_forest")

        # 红魔馆的剧本不含魔法森林的内容（防穿帮核心）
        self.assertEqual(len(mansion), 1)
        self.assertEqual(len(forest), 1)
        self.assertIn("图书馆", mansion[0].content)
        self.assertNotIn("魔法森林", "".join(e.content for e in mansion))

    def test_render_marks_system_events_distinctly(self):
        t = SharedTranscript()
        t.add(
            scene_id="s",
            speaker_kind=SpeakerKind.SYSTEM,
            speaker_id="system",
            speaker_name="系统",
            content="魔理沙从魔法森林来到红魔馆",
        )
        t.add(
            scene_id="s",
            speaker_kind=SpeakerKind.CHARACTER,
            speaker_id="marisa",
            speaker_name="魔理沙",
            content="到了！",
        )

        rendered = t.render_for_scene("s")
        self.assertIn("（魔理沙从魔法森林来到红魔馆）", rendered)
        self.assertIn("魔理沙：到了！", rendered)

    def test_history_limit_returns_recent(self):
        t = SharedTranscript()
        for i in range(10):
            t.add(
                scene_id="s",
                speaker_kind=SpeakerKind.CHARACTER,
                speaker_id="a",
                speaker_name="A",
                content=f"line{i}",
            )
        recent = t.history("s", limit=3)
        self.assertEqual([e.content for e in recent], ["line7", "line8", "line9"])

    def test_max_entries_per_scene_trims_oldest(self):
        t = SharedTranscript(max_entries_per_scene=5)
        for i in range(8):
            t.add(
                scene_id="s",
                speaker_kind=SpeakerKind.CHARACTER,
                speaker_id="a",
                speaker_name="A",
                content=f"line{i}",
            )
        kept = t.history("s")
        self.assertEqual(len(kept), 5)
        # 最旧的 line0..line2 被截断
        self.assertEqual(kept[0].content, "line3")
        self.assertEqual(kept[-1].content, "line7")

    def test_counts_reports_per_scene(self):
        t = self._mansion_transcript()
        self.assertEqual(t.counts(), {"scarlet_devil_mansion": 1, "magic_forest": 1})


class DirectorTypeTests(unittest.TestCase):
    def test_director_decision_defaults(self):
        decision = DirectorDecision(action=DirectorAction.WAIT_USER)
        self.assertIs(decision.action, DirectorAction.WAIT_USER)
        self.assertIsNone(decision.next_actor_id)
        self.assertFalse(decision.fallback_applied)

    def test_world_state_snapshot_holds_stage_and_roster(self):
        snap = WorldStateSnapshot(
            world_id="gensokyo",
            current_actor_id="marisa",
            waiting_for_user=False,
            stage={"marisa": "sdm", USER_OCCUPANT_ID: "sdm"},
            roster={"marisa": "雾雨魔理沙"},
        )
        self.assertEqual(snap.world_id, "gensokyo")
        self.assertEqual(snap.stage["marisa"], "sdm")
        self.assertFalse(snap.waiting_for_user)


if __name__ == "__main__":
    unittest.main()
