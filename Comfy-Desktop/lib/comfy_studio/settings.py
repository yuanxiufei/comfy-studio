"""面板里能填的那几项模型配置：落一份文件，**环境变量永远说了算**。

面板上模型没配好时只会回一句 ``-32603 没有配置模型：请设置 COMFY_STUDIO_LLM_MODEL`` ——
用户被告知了，却没有任何地方能补救：这三项只在环境变量里，而宿主是桌面壳自己拉起来的进程，
用户改不了它的环境。这一层就是那个补口：面板能把值存下来，下次启动照样生效。

**谁优先**：环境变量 > 这份文件。文件是"环境变量没给"时的兜底，所以
:meth:`SettingsStore.apply_to_env` 只在环境变量为空时才往 ``os.environ`` 里写。
于是 :meth:`comfy_studio.agent.llm.LLMConfig.from_env` 一行都不用改 —— 它仍是读模型配置的
唯一事实源，这里不另造一份"配置该从哪读"的逻辑（两份迟早对不上，而对不上是静默的）。

**存哪**：与记忆、对话存档同一份用户数据目录（``memory_home()``，``--memory-dir`` 改它）
下的 ``settings.json``。都是"这个工作台在你用户目录里的数据"。

**存什么**：那三个键（键名与环境变量同名：``COMFY_STUDIO_LLM_MODEL`` /
``COMFY_STUDIO_LLM_BASE_URL`` / ``COMFY_STUDIO_LLM_API_KEY``）—— 一眼看得出哪个是哪个 ——
外加一个 ``extra_sources``（见下）。除此之外一律不认：这不是"随手往配置里塞东西"的口子。

**额外的模型源**：环境变量那一组只描述得了**一条**源（三个固定键就是一条源的形状）。要让
另一家的模型也摆进面板的模型切换里（本机 Ollama 与云端 DeepSeek 并列可选），得有个地方装
"另外几条源"，那就是 ``extra_sources``：一组对象，每条是
``{"name": 给人看的名, "base_url": 地址, "api_key": 密钥, "model": 这条源的默认模型}``。

它与那三个键形状不同（一组对象 ≠ 一个名字一个值），所以**不进环境变量**（``apply_to_env``
只管那三项），"环境变量优先"对它也就不适用 —— 额外的源只从这份文件来，没有第二处能给出它。

**密钥**：写进去、存下来，但**从不回显**（:meth:`SettingsStore.status` 只报有还是没有）。
面板上没有"把密钥读回来看看"这种需求，而多一个能把它读出来的口子，就多一份它被写进日志、
截图、报错信息的机会。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: 落盘的文件名。
SETTINGS_FILENAME = "settings.json"

#: 面板能填的那三项，键名就是环境变量名。
MODEL_KEY = "COMFY_STUDIO_LLM_MODEL"
BASE_URL_KEY = "COMFY_STUDIO_LLM_BASE_URL"
API_KEY = "COMFY_STUDIO_LLM_API_KEY"

#: 认的键（顺序就是面板上从上到下那一列）。
SETTING_KEYS = (MODEL_KEY, BASE_URL_KEY, API_KEY)

#: 额外的模型源（除环境变量那一条之外的并列来源），值是**一组对象**而不是字符串。
#: 不在 :data:`SETTING_KEYS` 里：那三个键是"环境变量的形状"，装不下"一个地址带一把密钥"。
EXTRA_SOURCES_KEY = "extra_sources"

#: 切换模型时"来源"与"模型名"之间的分隔符，例如 ``DeepSeek::deepseek-v4-pro``。
#: 源的名字里不许出现它 —— 出现了拆出来的源名就永远是错的，而这种错一路都是静的。
SOURCE_SEPARATOR = "::"


class SettingsError(RuntimeError):
    """这份配置不成立（文件读不了、写不进去、值不是字符串、塞了不认的键）。"""


@dataclass(frozen=True)
class ModelSource:
    """一条**额外的**模型源：一个给人看的名、一个地址、一把密钥（可没有）、一个默认模型（可空）。

    名字既是它在面板下拉里的分组标题，也是切换时 ``名字::模型名`` 的前半段 —— 所以它必须
    非空、且不含 :data:`SOURCE_SEPARATOR`（校验在 :func:`_parse_sources`）。
    """

    name: str
    base_url: str
    api_key: str = ""
    model: str = ""

    def to_json(self) -> dict[str, Any]:
        """给面板看的形状：密钥只说有还是没有（与 :meth:`LlmSettings.to_json` 同一套口径）。"""
        return {
            "name": self.name,
            "base_url": self.base_url,
            "model": self.model,
            "has_key": bool(self.api_key),
        }

    def as_raw(self) -> dict[str, str]:
        """落盘的形状。这里密钥**是要写出去的**（面板读回来只会有 ``has_key``）；空的那两项
        不落盘，读回来就是空串 —— 与那三个键"存空 = 没这一项"同一套语义。
        """
        raw = {"name": self.name, "base_url": self.base_url}
        if self.api_key:
            raw["api_key"] = self.api_key
        if self.model:
            raw["model"] = self.model
        return raw


@dataclass(frozen=True)
class LlmSettings:
    """文件里存下来的那些配置：默认那条源的三个键 + 额外的几条源。

    三个键空串 = 这一项没存（照旧用环境变量或默认值）；``extra_sources`` 空元组 = 一条额外源都没挂。
    """

    model: str = ""
    base_url: str = ""
    api_key: str = ""
    extra_sources: tuple[ModelSource, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.model or self.base_url or self.api_key or self.extra_sources)

    def as_env(self) -> dict[str, str]:
        """折成 ``{环境变量名: 值}``，空的那几项不出现。

        ``extra_sources`` 不在这里：环境变量只表达得了"一条源"，额外的那些只从文件来。
        """
        pairs = {MODEL_KEY: self.model, BASE_URL_KEY: self.base_url, API_KEY: self.api_key}
        return {key: value for key, value in pairs.items() if value}

    def to_json(self) -> dict[str, Any]:
        """给面板看的形状：密钥只说有还是没有。"""
        return {
            "model": self.model,
            "base_url": self.base_url,
            "has_key": bool(self.api_key),
            "extra_sources": [source.to_json() for source in self.extra_sources],
        }


class SettingsStore:
    """一份 ``settings.json``。目录由调用方给（与记忆 / 存档同一个数据目录）。"""

    def __init__(
        self,
        directory: str | os.PathLike[str],
        filename: str = SETTINGS_FILENAME,
    ) -> None:
        self.directory = Path(directory).expanduser()
        self.path = self.directory / filename
        #: 哪几个键的**值来自文件**（:meth:`apply_to_env` 注入成功的那些）。没它的话，
        #: 注入之后环境变量里也有值了，"面板该显示 env 还是 file"就再也分不出来。
        self._from_file: set[str] = set()

    # ---- 读 -------------------------------------------------------------

    def load(self) -> LlmSettings:
        """读回来。**文件不在**是正常状态（还没填过），回一份空的；坏了则明说。"""
        if not self.path.is_file():
            return LlmSettings()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as err:
            raise SettingsError(f"读不了 {self.path}: {err}（删掉它就会回到只用环境变量）") from err
        if not isinstance(raw, dict):
            raise SettingsError(f"{self.path} 里不是一份配置对象：删掉它就会回到只用环境变量")

        values: dict[str, str] = {}
        for key in SETTING_KEYS:
            value = raw.get(key)
            if value is None:
                continue
            if not isinstance(value, str):
                raise SettingsError(f"{self.path} 的 {key} 不是字符串")
            values[key] = value
        return LlmSettings(
            model=values.get(MODEL_KEY, ""),
            base_url=values.get(BASE_URL_KEY, ""),
            api_key=values.get(API_KEY, ""),
            extra_sources=_parse_sources(self.path, raw.get(EXTRA_SOURCES_KEY)),
        )

    # ---- 写 -------------------------------------------------------------

    def save(self, values: dict[str, Any]) -> LlmSettings:
        """把面板给的那几项存下来（空串 = 这一项存空，等于交还给环境变量）。

        认的键只有 :data:`SETTING_KEYS` 那三个加 :data:`EXTRA_SOURCES_KEY` 这一个：别的键
        写进来既不认也不留，免得这份文件慢慢长成一个"什么都能塞"的杂物抽屉。
        ``extra_sources`` 给空数组 = 一条额外源都不挂（与"空串交还环境变量"同一套语义）。
        """
        unknown = [key for key in values if key not in SETTING_KEYS and key != EXTRA_SOURCES_KEY]
        if unknown:
            known = "、".join((*SETTING_KEYS, EXTRA_SOURCES_KEY))
            raise SettingsError(f"这份配置只认 {known}，给的是 {unknown}")

        current = self.load()
        merged: dict[str, str] = {
            MODEL_KEY: current.model,
            BASE_URL_KEY: current.base_url,
            API_KEY: current.api_key,
        }
        sources = current.extra_sources
        for key, value in values.items():
            if key == EXTRA_SOURCES_KEY:
                # 与读盘走同一套校验：写进去的东西必须读得回来，否则这文件就成了"只写不读"。
                sources = _parse_sources(self.path, value)
                continue
            if not isinstance(value, str):
                raise SettingsError(f"{key} 必须是字符串")
            merged[key] = value.strip()

        payload: dict[str, Any] = {key: value for key, value in merged.items() if value}
        if sources:
            payload[EXTRA_SOURCES_KEY] = [source.as_raw() for source in sources]
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
            # 先写同伴再换名：写到一半断电时留下的是那个 .tmp，这个仍是完整的旧文件。
            temp = self.path.with_name(self.path.name + ".tmp")
            temp.write_text(text, encoding="utf-8")
            os.replace(temp, self.path)
        except OSError as err:
            raise SettingsError(f"存不进 {self.path}: {err}") from err
        return self.load()

    # ---- 生效 -----------------------------------------------------------

    def apply_to_env(self) -> list[str]:
        """把文件里那几项注入本进程的环境变量，回被注入的键；**已有的不覆盖**。

        这就是"环境变量优先"的落点：值已经在环境里了，文件那条只在它为空时补位。
        """
        self._from_file = set()
        applied: list[str] = []
        for key, value in self.load().as_env().items():
            if os.environ.get(key):
                continue
            os.environ[key] = value
            self._from_file.add(key)
            applied.append(key)
        return applied

    # ---- 状态 -----------------------------------------------------------

    def status(self) -> dict[str, Any]:
        """面板要的那些：文件存了什么、哪几项是环境变量给的、哪几项的值来自文件。

        "值来自文件" ≠ "文件里存了值"：文件里存了模型名、环境变量也给了模型名时，真正生效的
        是环境变量那个 —— 面板照实画，别让用户以为改了这儿没用。
        """
        saved: LlmSettings | None = None
        error: str | None = None
        try:
            saved = self.load()
        except SettingsError as err:
            error = str(err)

        exists = self.path.is_file()
        return {
            "path": str(self.path),
            "exists": exists,
            # 文件不在就是"这份文件还没有"，不是"存了一份空的"：空文件是一份空配置，
            # 而不存在等于还没填过 —— 面板照着它决定输入框预填什么。
            "saved": saved.to_json() if (saved is not None and exists) else None,
            "from_file": sorted(self._from_file),
            # 只说"环境变量给没给"，值本身不回显 —— 密钥尤其不该从这里漏出去。
            # 要减掉 _from_file：apply_to_env 之后这些键在 os.environ 里也有值了，不减的话
            # "这份文件正提供模型名"会同时被报成"环境变量给了模型名"，面板就会画出一句
            # "改了不生效"的假警告。
            "from_env": sorted(
                key for key in SETTING_KEYS if os.environ.get(key) and key not in self._from_file
            ),
            "error": error,
        }


def _parse_sources(path: Path, raw: Any) -> tuple[ModelSource, ...]:
    """把 ``extra_sources`` 那一段解析成 :class:`ModelSource`，**形状不对就当场报错**。

    这里一处都不猜：类型不对、名字空着、名字里带了 :data:`SOURCE_SEPARATOR`、同一份文件里两条
    源重名 —— 全部立刻报出来。这些都不会自己变好，而静默接受的下场很具体：切换时选中的是 A、
    请求发去了 B，还查不出为什么。
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise SettingsError(f"{path} 的 {EXTRA_SOURCES_KEY} 必须是数组，给的是 {type(raw).__name__}")

    sources: list[ModelSource] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        where = f"{path} 的 {EXTRA_SOURCES_KEY}[{index}]"
        if not isinstance(item, dict):
            raise SettingsError(f"{where} 不是对象，给的是 {type(item).__name__}")

        fields: dict[str, str] = {}
        for field in ("name", "base_url", "api_key", "model"):
            value = item.get(field)
            if value is None:
                continue
            if not isinstance(value, str):
                raise SettingsError(f"{where} 的 {field} 不是字符串")
            fields[field] = value.strip()

        name = fields.get("name", "")
        if not name:
            raise SettingsError(f"{where} 没有 name：这一条源在下拉里没有名字就选不出来")
        if SOURCE_SEPARATOR in name:
            raise SettingsError(f"{where} 的 name 里不能出现 {SOURCE_SEPARATOR}：切换时靠它分隔源与模型")
        if name in seen:
            raise SettingsError(f"{where} 的 name 与前面一条重复（{name}）：重名的源分不清是哪一个")
        seen.add(name)

        base_url = fields.get("base_url", "")
        if not base_url:
            raise SettingsError(f"{where} 没有 base_url：一条源没有地址就什么都问不了")

        sources.append(
            ModelSource(
                name=name,
                base_url=base_url.rstrip("/"),
                api_key=fields.get("api_key", ""),
                model=fields.get("model", ""),
            )
        )
    return tuple(sources)


__all__ = [
    "API_KEY",
    "BASE_URL_KEY",
    "EXTRA_SOURCES_KEY",
    "MODEL_KEY",
    "SETTINGS_FILENAME",
    "SETTING_KEYS",
    "SOURCE_SEPARATOR",
    "LlmSettings",
    "ModelSource",
    "SettingsError",
    "SettingsStore",
]
