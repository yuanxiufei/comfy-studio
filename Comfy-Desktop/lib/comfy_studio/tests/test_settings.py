"""``comfy_studio.settings`` 的单元测试（纯本地：临时目录当用户数据目录，不起子进程）。

跑法（引擎 venv 的 python，cwd 在 Comfy-Desktop/lib）::

    <仓库>/ComfyUI/.venv/Scripts/python.exe -m unittest comfy_studio.tests.test_settings -v

后一组 ``SettingsRpcTest`` 把宿主那一层也钉住：面板那个 ``agent/settings`` 读得到什么、写完
是不是真的落了盘又进了环境、参数不对回哪个码。**"环境变量优先"这条尤其要钉**：它错了的表现
是"用户在面板里改了地址，宿主却照样连老地方"，而那种错一路都是静的。
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from comfy_studio.agent.llm import LLMConfig
from comfy_studio.mcp import McpHub
from comfy_studio.rpc import INTERNAL_ERROR, INVALID_PARAMS, RpcError
from comfy_studio.server import StudioHost
from comfy_studio.settings import (
    API_KEY,
    BASE_URL_KEY,
    MODEL_KEY,
    SETTINGS_FILENAME,
    SETTING_KEYS,
    SettingsError,
    SettingsStore,
)
from comfy_studio.skills import SkillCatalog


class _EnvIsolatedTest(unittest.TestCase):
    """把那三个环境变量暂时清空：它们在本机多半真的设着，不清就会串进来。"""

    def setUp(self) -> None:
        super().setUp()
        self._env = mock.patch.dict(os.environ, {}, clear=False)
        self._env.start()
        for key in SETTING_KEYS:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        self._env.stop()
        super().tearDown()


class SettingsStoreTest(_EnvIsolatedTest):
    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-settings-")
        self.dir = Path(self._tmp.name)
        self.store = SettingsStore(self.dir)

    def tearDown(self) -> None:
        self._tmp.cleanup()
        super().tearDown()

    # ---- 读 -------------------------------------------------------------

    def test_missing_file_is_a_state_not_an_error(self) -> None:
        # 还没填过是正常状态：不是错误，也不该凭空造一份出来。
        settings = self.store.load()
        self.assertTrue(settings.empty)
        self.assertFalse(self.store.path.exists())

    def test_status_of_missing_file(self) -> None:
        status = self.store.status()
        self.assertFalse(status["exists"])
        self.assertIsNone(status["saved"])
        self.assertIsNone(status["error"])
        self.assertEqual(status["from_file"], [])
        self.assertEqual(status["from_env"], [])

    def test_broken_file_says_what_to_do(self) -> None:
        self.store.path.write_text("{ 这不是 json", encoding="utf-8")
        with self.assertRaises(SettingsError) as err:
            self.store.load()
        # 只说"读不了"没用：得告诉人能怎么办（删掉它）。
        self.assertIn("删掉", str(err.exception))

    def test_file_that_is_not_an_object_is_refused(self) -> None:
        self.store.path.write_text("[1, 2, 3]", encoding="utf-8")
        with self.assertRaises(SettingsError):
            self.store.load()

    def test_non_string_value_is_refused(self) -> None:
        self.store.path.write_text(json.dumps({MODEL_KEY: 12}), encoding="utf-8")
        with self.assertRaises(SettingsError):
            self.store.load()

    # ---- 写 -------------------------------------------------------------

    def test_save_then_load_round_trip(self) -> None:
        self.store.save({MODEL_KEY: "qwen2.5:7b", BASE_URL_KEY: "http://127.0.0.1:11434/v1"})
        settings = self.store.load()
        self.assertEqual(settings.model, "qwen2.5:7b")
        self.assertEqual(settings.base_url, "http://127.0.0.1:11434/v1")
        self.assertEqual(settings.api_key, "")
        # 落盘的就是那三个键名（与环境变量同名），一眼看得出哪个是哪个。
        raw = json.loads(self.store.path.read_text(encoding="utf-8"))
        self.assertEqual(sorted(raw), sorted([MODEL_KEY, BASE_URL_KEY]))

    def test_key_is_stored_but_never_echoed(self) -> None:
        self.store.save({MODEL_KEY: "m", API_KEY: "sk-别回显我"})
        self.assertEqual(self.store.load().api_key, "sk-别回显我")
        status = self.store.status()
        self.assertTrue(status["saved"]["has_key"])
        # 状态里不许出现密钥的值：这条断言就是"不回显"的看门人。
        self.assertNotIn("sk-别回显我", json.dumps(status, ensure_ascii=False))

    def test_save_only_touches_the_keys_it_is_given(self) -> None:
        self.store.save({MODEL_KEY: "m", BASE_URL_KEY: "http://a", API_KEY: "k"})
        self.store.save({BASE_URL_KEY: "http://b"})
        settings = self.store.load()
        self.assertEqual(settings.model, "m")
        self.assertEqual(settings.base_url, "http://b")
        self.assertEqual(settings.api_key, "k")

    def test_empty_string_clears_one_key(self) -> None:
        self.store.save({MODEL_KEY: "m", API_KEY: "k"})
        self.store.save({API_KEY: ""})
        self.assertEqual(self.store.load().api_key, "")
        self.assertEqual(self.store.load().model, "m")

    def test_unknown_key_is_refused(self) -> None:
        with self.assertRaises(SettingsError) as err:
            self.store.save({"COMFY_STUDIO_别的什么": "x"})
        self.assertIn("只认", str(err.exception))
        self.assertFalse(self.store.path.exists())

    def test_non_string_value_is_refused_on_save(self) -> None:
        with self.assertRaises(SettingsError):
            self.store.save({MODEL_KEY: 7})  # type: ignore[dict-item]

    def test_save_values_are_trimmed(self) -> None:
        self.store.save({MODEL_KEY: "  m  "})
        self.assertEqual(self.store.load().model, "m")

    def test_save_leaves_no_temp_behind(self) -> None:
        self.store.save({MODEL_KEY: "m"})
        self.assertEqual([p.name for p in self.dir.iterdir()], [SETTINGS_FILENAME])

    def test_save_creates_the_directory(self) -> None:
        nested = SettingsStore(self.dir / "还没有" / "这两层")
        nested.save({MODEL_KEY: "m"})
        self.assertTrue(nested.path.is_file())

    # ---- 生效 -----------------------------------------------------------

    def test_apply_to_env_injects_when_env_is_empty(self) -> None:
        self.store.save({MODEL_KEY: "qwen2.5:7b", API_KEY: "sk-1"})
        applied = self.store.apply_to_env()
        self.assertEqual(set(applied), {MODEL_KEY, API_KEY})
        self.assertEqual(os.environ[MODEL_KEY], "qwen2.5:7b")
        self.assertEqual(os.environ[API_KEY], "sk-1")
        # 注入之后 LLMConfig.from_env() 就能直接建起来了：它是配置的唯一事实源。
        self.assertEqual(LLMConfig.from_env().model, "qwen2.5:7b")

    def test_env_wins_over_the_file(self) -> None:
        self.store.save({MODEL_KEY: "文件里的", BASE_URL_KEY: "http://文件里的"})
        os.environ[MODEL_KEY] = "环境里的"
        applied = self.store.apply_to_env()
        self.assertEqual(applied, [BASE_URL_KEY])
        self.assertEqual(os.environ[MODEL_KEY], "环境里的")
        self.assertEqual(LLMConfig.from_env().model, "环境里的")

    def test_status_tells_file_from_env(self) -> None:
        # 文件给模型名、环境变量给地址：注入之后两者都要认得出来，否则面板会画反。
        self.store.save({MODEL_KEY: "文件里的"})
        os.environ[BASE_URL_KEY] = "http://环境里的"
        self.store.apply_to_env()
        status = self.store.status()
        self.assertEqual(status["from_file"], [MODEL_KEY])
        self.assertEqual(status["from_env"], [BASE_URL_KEY])

    def test_broken_file_raises_on_apply(self) -> None:
        self.store.path.write_text("不是 json", encoding="utf-8")
        with self.assertRaises(SettingsError):
            self.store.apply_to_env()


class SettingsRpcTest(_EnvIsolatedTest):
    """宿主那一层：``agent/settings`` 读得到啥、写完是不是真生效、参数不对回哪个码。"""

    def setUp(self) -> None:
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(prefix="comfy-studio-settings-rpc-")
        self.dir = Path(self._tmp.name)
        self.store = SettingsStore(self.dir)
        self.hub = McpHub([], extra_clients=[])
        self.catalog = SkillCatalog(self.hub)
        self.host = StudioHost(self.hub, self.catalog, settings=self.store)
        self.bare = StudioHost(self.hub, self.catalog)

    def tearDown(self) -> None:
        self._tmp.cleanup()
        super().tearDown()

    def _settings(self, params: dict) -> dict:
        return asyncio.run(self.host.agent_settings(params, None))

    def test_method_is_registered(self) -> None:
        self.assertIn("agent/settings", self.host.server.methods)

    def test_host_without_store_says_so(self) -> None:
        with self.assertRaises(RpcError) as err:
            asyncio.run(self.bare.agent_settings({}, None))
        self.assertEqual(err.exception.code, INTERNAL_ERROR)
        self.assertIn("环境变量", str(err.exception))

    def test_read_reports_not_configured_yet(self) -> None:
        # 三样都没有时，读这一档**不是错误**：它的用途正是"把没配好的填上"。
        status = self._settings({})
        self.assertFalse(status["configured"])
        self.assertIsNone(status["model"])
        self.assertIn(MODEL_KEY, status["error"])
        self.assertEqual(status["path"], str(self.store.path))

    def test_write_lands_on_disk_and_takes_effect(self) -> None:
        result = self._settings({MODEL_KEY: "qwen2.5:7b", BASE_URL_KEY: "http://127.0.0.1:11434/v1"})
        self.assertTrue(result["saved"])
        self.assertTrue(result["configured"])
        self.assertEqual(result["model"], "qwen2.5:7b")
        # 落盘了
        self.assertEqual(json.loads(self.store.path.read_text(encoding="utf-8"))[MODEL_KEY], "qwen2.5:7b")
        # 也当场生效了：环境变量 + LLMConfig 这一条链子上都是它
        self.assertEqual(os.environ[MODEL_KEY], "qwen2.5:7b")
        self.assertEqual(LLMConfig.from_env().model, "qwen2.5:7b")
        # 面板要能看出"这份文件正提供模型名"（否则用户以为改了没用）
        self.assertIn(MODEL_KEY, result["from_file"])
        self.assertEqual(result["from_env"], [])

    def test_write_reports_no_session_to_switch(self) -> None:
        result = self._settings({MODEL_KEY: "m"})
        self.assertEqual(result["applied"], [])
        self.assertEqual(result["skipped"], [])

    def test_write_with_non_string_is_invalid_params(self) -> None:
        with self.assertRaises(RpcError) as err:
            self._settings({MODEL_KEY: 12})
        self.assertEqual(err.exception.code, INVALID_PARAMS)

    def test_write_ignores_keys_that_are_not_ours(self) -> None:
        # 面板多塞了别的东西：不认也不留，更不许把它写进文件。
        result = self._settings({MODEL_KEY: "m", "别的什么": "x"})
        self.assertTrue(result["saved"])
        self.assertEqual(sorted(json.loads(self.store.path.read_text(encoding="utf-8"))), [MODEL_KEY])

    def test_read_reports_broken_file_without_raising(self) -> None:
        # 文件坏了也是"读得到的状态"：读这一档必须回得来，否则面板上连表单都打不开、
        # 用户就没有任何办法把坏文件换掉。
        self.store.path.write_text("不是 json", encoding="utf-8")
        status = self._settings({})
        self.assertIn("删掉", status["file_error"])
        self.assertIsNone(status["saved"])


if __name__ == "__main__":
    unittest.main()
