"""核心层单元测试 —— 不依赖模型、不依赖网络，秒级跑完。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path, PureWindowsPath

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.subtitles import Cue, cues_from_segments, metrics, parse_srt, write_srt


class TestSRT(unittest.TestCase):
    SAMPLE = """1
00:00:00,200 --> 00:00:01,910
好本期视频的话是

2
00:00:01,910 --> 00:00:04,320
上期有人说要做一个字幕工具
"""

    def test_parse_basic(self):
        cues = parse_srt(self.SAMPLE)
        self.assertEqual(len(cues), 2)
        self.assertAlmostEqual(cues[0].start, 0.2)
        self.assertAlmostEqual(cues[1].end, 4.32)
        self.assertEqual(cues[0].text, "好本期视频的话是")

    def test_parse_crlf_and_bom(self):
        raw = "\ufeff" + self.SAMPLE.replace("\n", "\r\n")
        cues = parse_srt(raw)
        self.assertEqual(len(cues), 2)

    def test_parse_dot_decimal(self):
        raw = "1\n00:00:01.500 --> 00:00:02.000\n测试\n"
        cues = parse_srt(raw)
        self.assertEqual(len(cues), 1)
        self.assertAlmostEqual(cues[0].start, 1.5)

    def test_roundtrip(self):
        import tempfile

        cues = parse_srt(self.SAMPLE)
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.srt"
            write_srt(cues, p)
            again = parse_srt(p.read_text(encoding="utf-8"))
        self.assertEqual(len(again), len(cues))
        for a, b in zip(cues, again):
            self.assertAlmostEqual(a.start, b.start, places=2)
            self.assertEqual(a.text, b.text)

    def test_metrics_detects_no_punct(self):
        cues = parse_srt(self.SAMPLE)
        m = metrics(cues)
        self.assertFalse(m["has_punct"])
        self.assertEqual(m["cues"], 2)
        self.assertGreater(m["cps"], 0)

    def test_metrics_detects_overlap(self):
        cues = [Cue(1, 0.0, 2.0, "a"), Cue(2, 1.0, 3.0, "b")]
        self.assertEqual(metrics(cues)["overlap"], 1)

    def test_cues_from_segments_skips_empty(self):
        segs = [
            {"start": 0.0, "end": 1.0, "text": "有内容"},
            {"start": 1.0, "end": 2.0, "text": "   "},
            {"start": 2.0, "end": 3.0, "text": "又有"},
        ]
        cues = cues_from_segments(segs)
        self.assertEqual(len(cues), 2)


class TestEngines(unittest.TestCase):
    def test_registry_populated(self):
        from core.asr import list_engines

        names = {e.name for e in list_engines()}
        self.assertIn("funasr", names)
        self.assertIn("whisper", names)
        self.assertIn("jianying", names)

    def test_jianying_off_by_default(self):
        """私有接口引擎必须默认关闭 —— 这是安全约束，不是偏好。"""
        import os

        from core.asr import get_engine

        os.environ.pop("LYCOSUB_ENABLE_JIANYING", None)
        ok, reason = get_engine("jianying").available()
        self.assertFalse(ok)
        self.assertIn("未启用", reason)

    def test_describe_shape(self):
        from core.asr import list_engines

        for e in list_engines():
            d = e.describe()
            for key in ("name", "label", "kind", "available", "reason"):
                self.assertIn(key, d)


class TestRender(unittest.TestCase):
    def test_filter_path_escaping_windows(self):
        from core.render.burn import _escape_filter_path

        # 直接用 PureWindowsPath 构造，绕开 p.resolve() 的平台差异：
        # 在 Linux CI 上 Path("C:/x") 没有盘符，转义分支根本不会触发
        # （这正是这个测试曾经在 CI 失败的原因）。
        p = PureWindowsPath("C:/tmp/a b.srt")
        out = _escape_filter_path(p)
        # Windows 盘符冒号必须被转义，否则 ffmpeg 会当成滤镜选项分隔符
        self.assertIn("\\:", out)
        self.assertTrue(out.startswith("C\\:"))
        self.assertNotIn("\\", out.replace("\\:", ""))

    def test_filter_path_escaping_posix(self):
        from core.render.burn import _escape_filter_path

        # POSIX 路径没有盘符，不该被转义
        p = Path("/tmp/a b.srt")
        out = _escape_filter_path(p)
        self.assertNotIn("\\:", out)

    def test_quality_map(self):
        from core.render.burn import QUALITY_CRF

        self.assertEqual(QUALITY_CRF["ultra"], 18)
        self.assertLess(QUALITY_CRF["ultra"], QUALITY_CRF["low"])


if __name__ == "__main__":
    unittest.main()
