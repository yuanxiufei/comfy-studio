"""漫剧原文（``manju/novel/``）的读写：面板「管理小说」那一页的后端。

面板要干的事就四件，一件一个方法（都是宿主进程的 RPC，见 :mod:`comfy_studio.server`）：

``novels/list``     原文目录里有哪些小说（名字、大小、改于何时）
``novels/read``     读一篇的正文（按字符分页，一页页往下翻）
``novels/chapters`` 把一篇切成章节（面板左栏那棵目录树，点一章跳到那一章）
``novels/search``   在原文里找一串字，回它出现的位置（面板据此跳过去）
``novels/import``   把本机一份 txt/md 接进原文目录（导入第一本时会把目录建出来）
``novels/delete``   删掉一篇（面板先问一次再调它）

**目录从哪来**：漫剧那份业务数据住在引擎侧（``ComfyUI/custom_nodes/comfy_studio/manju/``），
原文在它的 ``novel/`` 下 —— 落点见 :data:`MANJU_REL`，与 ``.codebuddy/agents/_build.py`` 里那份
指的是同一个地方。桌面侧只知道 ``--comfyui-dir``，所以默认 =

``<comfyui-dir>/custom_nodes/comfy_studio/manju/novel``（:func:`default_novel_dir`），

``--novel-dir`` / ``COMFY_STUDIO_NOVEL_DIR`` 可以改。换机器、换检出，这条**仓库内相对路径**
照样成立；代码里不写盘符，也不去猜别的位置。

**只管原文目录**：素材与产出是 :mod:`comfy_studio.localfiles` 的地盘（input/output），
两边过同一套越界检查（:func:`comfy_studio.localfiles.is_within`），谁也走不出自己的目录。

**认编码、但只认两种，且认不出就明说**：中文网文十有八九是 GB18030（GBK/GB2312 的超集）
而不是 UTF-8，只按 UTF-8 读等于读不了用户自己的书。所以 :func:`decode_text` 先严格试 UTF-8
（几万个字节全是合法 UTF-8，基本可以排除"其实是别的编码"），不成再试 gb18030 —— 而 gb18030
**几乎什么字节都能解出来**（连二进制也照解），所以解完还要验一下是不是人话（不像正文的字符占比、
中文占比，见 :data:`GARBAGE_RATIO` / :data:`CJK_RATIO`）：验不过就明确报错，绝不把一屏乱码
当正文交出去。繁体 Big5 不在候选里（GB18030 与 Big5 共用字节区间，纯靠统计分不开，认错了
给的是"看着像字其实不是"的东西），会作为错误报出来并说清该怎么办。分页按**字符**而不是字节：
一页四千个汉字在面板里刚好一屏，而"第几字节"对人没有任何意义。
"""

from __future__ import annotations

import codecs
import os
import re
import shutil
from collections import OrderedDict
from pathlib import Path
from typing import Any

from .localfiles import is_within

#: 漫剧业务数据在引擎检出里的相对落点（相对 ``--comfyui-dir``）。
MANJU_REL = Path("custom_nodes") / "comfy_studio" / "manju"

#: 原文就放在业务数据根下的这一层。
NOVEL_SUBDIR = "novel"

#: 认得出是原文的后缀。别的文件在列表里也照报（标成 ``text: false``），但不许当原文导进来。
TEXT_SUFFIXES = (".txt", ".md")

#: 一次给面板多少字：一屏看得完，又不至于把这次 RPC 的回话撑大。
DEFAULT_READ_CHARS = 4000

#: 面板一次最多能要多少字（``chars`` 的上限）。
MAX_READ_CHARS = 40000

#: 超过这个大小的原文不读：分页得先把整篇解码出来，几十兆的文件在面板里翻页会卡成幻灯片。
#: 中文小说通常几兆，这条线留得很宽；超了就明确报错，不做静默截断半篇。
MAX_TEXT_BYTES = 32 * 1024 * 1024

#: 列表默认最多给几行、最多能给几行。
DEFAULT_LIST_LIMIT = 200
MAX_LIST_LIMIT = 1000

#: 判编码时最多看解出来的多少个字。乱码与正常中文的区别，开头一小段就足够看出来，
#: 没必要为了判它把几十兆的整篇再扫一遍。
SNIFF_CHARS = 64 * 1024

#: 整篇解好的正文缓存几篇。翻页、看目录、搜索都要整篇解码，而一篇六兆多的原文每翻一页重解
#: 一遍就是几秒的卡顿；缓存换篇时把旧的丢掉，别把书库长期占在内存里。
#: 键里带 (路径, 大小, 改于何时)：文件被外面改了（编辑、重导一份）就自然失效，不会给出旧内容。
CACHE_MAX_ENTRIES = 2

#: 章节标题长什么样：**整行基本就是一个标题**才算。正文里"第 3 章里说过"这种句子极常见，
#: 不要求"整行独占"就会切出一堆假章节，那种目录比没有目录更没用。
#: 认的是中文网文里最常见的几种写法（第X章/节/回/卷/集 + 可选标题，另有 Chapter N）。
CHAPTER_RE = re.compile(
    r"^(?:第\s*[0-9０-９零〇一二三四五六七八九十百千万两]{1,12}\s*[章节回卷篇集]"
    r"|Chapter\s+[0-9]{1,4}\b)"
    r"[\s:：.、\-—－]*[^\n，。！？；：]{0,30}$",
    re.IGNORECASE,
)

#: 标题行最长多少个字。超出这个长度就不像标题，而像"以'第一章'开头的一整段正文"。
CHAPTER_TITLE_CHARS = 60

#: 目录默认最多给几章、最多能给几章（两万章够长篇小说用了）。
DEFAULT_CHAPTER_LIMIT = 5000
MAX_CHAPTER_LIMIT = 20000

#: 搜索默认最多回几处、最多能回几处，以及每处给前后各多少个字做上下文。
DEFAULT_SEARCH_LIMIT = 100
MAX_SEARCH_LIMIT = 1000
SEARCH_WINDOW = 24

#: 解出来的字里"不像正文"的（控制符、私用区、代理区）超过这个比例就判为乱码 —— 只看得见的
#: 三种，认不出的码位（Python 的解码器不会往外吐）不在其中。留得很紧：正常中文原文里这些字符
#: 基本是零，出现万分之几就已经不是文字了。
GARBAGE_RATIO = 0.0002

#: 解出来的字里中日韩汉字与中文标点至少得占这么多 —— 防的是"把二进制文件当小说读出来一堆怪字"。
#: 真正的原文（哪怕夹着英文、符号、空白）远高于这条线。
CJK_RATIO = 0.05


class NovelsError(RuntimeError):
    """原文读写不成立（目录里没有这一篇、认不出编码、太大了……）。"""


def _garbage_ratio(text: str) -> float:
    """这段字里"不像正文"的字符占多少（0~1）。"""
    if not text:
        return 0.0
    bad = 0
    for char in text:
        code = ord(char)
        if char in "\t\r\n":
            continue
        if code < 0x20 or 0x7F <= code <= 0x9F:  # 控制符
            bad += 1
        elif 0xE000 <= code <= 0xF8FF:  # 私用区：错编码最容易往这儿落
            bad += 1
        elif 0xD800 <= code <= 0xDFFF or code > 0x10FFFF:  # 代理区/越界
            bad += 1
    return bad / len(text)


def _cjk_ratio(text: str) -> float:
    """这段字里中日韩汉字与中文标点占多少（0~1）。"""
    if not text:
        return 0.0
    cjk = 0
    for char in text:
        code = ord(char)
        if (
            0x3400 <= code <= 0x4DBF  # 扩展 A
            or 0x4E00 <= code <= 0x9FFF  # 基本区
            or 0xF900 <= code <= 0xFAFF  # 兼容汉字
            or 0x3000 <= code <= 0x303F  # 中文标点
            or 0xFF00 <= code <= 0xFFEF  # 全角
        ):
            cjk += 1
    return cjk / len(text)


def _snippet(text: str, start: int, end: int, window: int = SEARCH_WINDOW) -> str:
    """命中处前后那一段（给面板显示用）：折掉换行，两头该省略的地方标出来。

    这种片段是给"这条是不是我要找的"看的，所以宁可两头都带一点上下文，
    也不要把命中处裁到只剩几个字。
    """
    left = max(0, start - window)
    right = min(len(text), end + window)
    piece = text[left:right].replace("\r", " ").replace("\n", " ").strip()
    return ("…" if left > 0 else "") + piece + ("…" if right < len(text) else "")


def decode_text(raw: bytes, name: str) -> tuple[str, str]:
    """把原文的字节解成文字，回 ``(text, 用的编码)``；认不出来抛 :class:`NovelsError`。

    编码是**判**出来的，不是猜的：UTF-8 先严格解一遍（几万个字节都合法就认它），不成再看
    gb18030 —— 但 gb18030 是"什么都能解"的那种超集，所以解出来必须过两道验（
    :func:`_garbage_ratio` / :func:`_cjk_ratio`），验不过就明确报错。宁可说"读不了"，
    也不能把一屏乱码当正文交出去 —— 后者看着像面板坏了，用户只会反复点。

    这条判法的代价写在明处：**整篇 UTF-8 只错个别字节**的文件会落到 gb18030 那一档。解出来的
    仍是同一篇字（那个坏字节变成一个怪字），比整篇拒读更接近用户要的；``encoding`` 会如实说
    用的是哪一种，所以"这字怎么看着不对"有出处可查。
    """
    if raw.startswith(codecs.BOM_UTF8):
        # 记事本"另存为 UTF-8"会带 BOM：那三个字节不是正文的第一个字，得剥掉。
        try:
            return raw.decode("utf-8-sig"), "utf-8"
        except UnicodeDecodeError as err:
            raise NovelsError(
                f"{name} 开头是 UTF-8 BOM，第 {err.start} 字节起却不是合法 UTF-8：文件坏了或被改过"
            ) from err
    if raw.startswith(codecs.BOM_UTF16_LE) or raw.startswith(codecs.BOM_UTF16_BE):
        # 记事本"另存为 Unicode"：BOM 自己指明字节序，不用猜。
        try:
            return raw.decode("utf-16"), "utf-16"
        except UnicodeDecodeError as err:
            raise NovelsError(
                f"{name} 开头是 UTF-16 BOM，第 {err.start} 字节起读不下去：文件坏了或被改过"
            ) from err

    try:
        return raw.decode("utf-8"), "utf-8"
    except UnicodeDecodeError as utf8_error:
        # 只把位置记下来：except 块一出去，``utf8_error`` 这个名字就被解绑了（Python 3 的规矩），
        # 后面还要用它去定位"到底哪一段让 UTF-8 解不过去"。
        utf8_start = utf8_error.start

    try:
        text = raw.decode("gb18030")
    except UnicodeDecodeError as gb_error:
        raise NovelsError(
            f"{name} 认不出编码：试过 utf-8（第 {utf8_start} 字节起）与 gb18030"
            f"（第 {gb_error.start} 字节起）都不成。面板不猜第三种编码 —— 猜错了给你一屏乱码，"
            "比直说读不了更糟；繁体 Big5 的原文请先转成 UTF-8 再导进来"
        ) from gb_error

    # 判定就看"让 UTF-8 解不过去的那一段"：那里才是有信息量的地方（前面若是一大段 ASCII，
    # 解成什么编码都一样，拿它当依据等于没看）。原文按 GBK 写时这一段满是汉字，正好露馅。
    start = max(0, utf8_start - 1024)
    sample = text[start : start + SNIFF_CHARS]
    garbage = _garbage_ratio(sample)
    cjk = _cjk_ratio(sample)
    if garbage > GARBAGE_RATIO or cjk < CJK_RATIO:
        raise NovelsError(
            f"{name} 用 gb18030 解出来的不是正文（不像正文的字符占 {garbage:.2%}、"
            f"中文占 {cjk:.2%}）：它多半不是文本文件，或者用的不是 utf-8 / gb18030"
        )
    return text, "gb18030"


def default_novel_dir(comfyui_dir: str | os.PathLike[str]) -> Path:
    """默认原文目录：``<comfyui-dir>/custom_nodes/comfy_studio/manju/novel``。"""
    return Path(comfyui_dir).expanduser().resolve() / MANJU_REL / NOVEL_SUBDIR


class NovelLibrary:
    """原文目录上的四个动作。目录由调用方给（``--novel-dir`` 或默认落点），这里不猜。"""

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        # 目录还不存在是**合法状态**：这个检出从没导入过原文，或者干脆不是这份仓库。
        # 那不是"出错"，是"这里还没有书"——面板据此说人话（见 :meth:`list`）。
        self.directory = Path(directory).expanduser().resolve()
        #: 最近解好的正文（LRU，见 :data:`CACHE_MAX_ENTRIES`）：翻页、看目录、搜索共用它。
        self._cache: OrderedDict[tuple[str, int, int], tuple[str, str]] = OrderedDict()

    # ---- list -----------------------------------------------------------

    def list(self, name: str | None = None, limit: int = DEFAULT_LIST_LIMIT) -> dict[str, Any]:
        """原文目录里有哪些小说，按**名字**排。

        这座目录是书库，不是信息流：稳定比"最近改过的在前"有用 —— 用户是来找《某某》的，
        而每改一次文件就把列表搅乱，找起来反而费劲。

        ``exists: false`` 不是错误（目录还没建、或这个检出里没有漫剧数据）：面板照这个说
        "还没有原文，导入一本就有了"，而不是把它画成一次失败。
        非 txt/md 的文件也照报（``text: false``）：明明躺在那个目录里却一行不显示，
        用户只会以为面板坏了。
        """
        root = self.directory
        if not root.is_dir():
            return {
                "dir": str(root),
                "exists": False,
                "matched": 0,
                "returned": 0,
                "truncated": False,
                "limit": limit,
                "novels": [],
            }

        needle = name.strip().lower() if isinstance(name, str) and name.strip() else None
        found: list[dict[str, Any]] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(root).as_posix()
            if any(part.startswith(".") for part in rel.split("/")):
                # 隐藏项不是原文，不占列表（.gitkeep、.DS_Store 这类）——**文件和目录一视同仁**：
                # 只挡文件名的话，`.私藏/秘本.txt` 会绕过这一条漏进书库，而"隐藏"对它和对
                # .gitkeep 是同一个意思。
                continue
            if needle is not None and needle not in rel.lower():
                continue
            try:
                info = path.stat()
            except OSError:
                # 名字读到了、属性读不到（正被别的程序锁着）：跳过这一行，不整表报错。
                continue
            found.append(
                {
                    "name": rel,
                    "path": str(path),
                    "bytes": info.st_size,
                    "mtime": info.st_mtime,
                    "text": path.suffix.lower() in TEXT_SUFFIXES,
                }
            )
        found.sort(key=lambda item: item["name"].lower())
        return {
            "dir": str(root),
            "exists": True,
            "matched": len(found),
            "returned": min(len(found), limit),
            "truncated": len(found) > limit,
            "limit": limit,
            "novels": found[:limit],
        }

    # ---- read -----------------------------------------------------------

    def read(self, name: str, offset: int = 0, chars: int = DEFAULT_READ_CHARS) -> dict[str, Any]:
        """读一篇原文的一页。

        ``offset`` 是第几个字（0 起），``chars`` 是这一页最多几个字；返回里的 ``next_offset``
        可以直接当下一趟的 ``offset``（``at_end`` 为真说明到头了）。
        ``offset`` 超过总字数时按末尾算（回来的是空的一页，且 ``offset`` 报的是真正用的那个），
        不做静默取整：面板下一次就自然会停住。

        每次都要把整篇解码出来 —— 这两种编码都是变长编码，按字节跳过去对不齐字符 —— 所以对文件
        大小有条线（:data:`MAX_TEXT_BYTES`）：超了明确报错，不截半篇假装读完了。回来里带
        ``encoding``：面板会把它写在状态行上，好让"这字怎么看着不对"有个出处可查。
        """
        if offset < 0:
            raise NovelsError(f"offset 不能是负数，给的是 {offset}")
        if chars < 1:
            raise NovelsError(f"chars 不能小于 1，给的是 {chars}")

        path = self._resolve(name)
        if not path.is_file():
            raise NovelsError(f"原文目录里没有这一篇: {name}")
        if path.suffix.lower() not in TEXT_SUFFIXES:
            raise NovelsError(
                f"{path.name} 不是原文（只认 {'、'.join(TEXT_SUFFIXES)}）：面板读不了这种格式"
            )
        try:
            size = path.stat().st_size
        except OSError as err:
            raise NovelsError(f"读不了 {path}: {err}") from err
        if size > MAX_TEXT_BYTES:
            raise NovelsError(
                f"{path.name} 有 {size / 1024 / 1024:.1f} MB，超过面板翻页的上限 "
                f"{MAX_TEXT_BYTES / 1024 / 1024:.0f} MB：用编辑器看原文，或先切成几篇"
            )

        # 编码是判出来的（见 decode_text），整篇解一次之后还会被缓存住（见 _text）：
        # 中文网文多是 GB18030，只认 UTF-8 等于读不了用户的书。
        text, encoding = self._text(path, name)

        total = len(text)
        start = min(offset, total)
        window = text[start : start + chars]
        next_offset = start + len(window)
        return {
            "name": name,
            "path": str(path),
            "bytes": size,
            "mtime": path.stat().st_mtime,
            "encoding": encoding,
            "total_chars": total,
            "offset": start,
            "chars": len(window),
            "requested_chars": chars,
            "next_offset": next_offset,
            "at_end": next_offset >= total,
            "text": window,
        }

    # ---- chapters -------------------------------------------------------

    def chapters(self, name: str, limit: int = DEFAULT_CHAPTER_LIMIT) -> dict[str, Any]:
        """把一篇切成章节：面板左栏那棵目录树。

        切法就是 :data:`CHAPTER_RE` 那条 —— **整行基本是个标题**才算一章，所以正文里提到
        "第 3 章"的地方不会变成分界。标题一条都没认出来时，整篇算一章并在 ``message`` 里
        说明白：硬凑一份目录，比直说"这篇切不出来"更耽误人。

        每章带 ``offset``：面板拿它直接调 :meth:`read`，跳章就是跳字符。
        """
        if limit < 1:
            raise NovelsError(f"limit 不能小于 1，给的是 {limit}")
        path = self._resolve(name)
        if not path.is_file():
            raise NovelsError(f"原文目录里没有这一篇: {name}")
        text, encoding = self._text(path, name)
        total = len(text)

        found: list[dict[str, Any]] = []
        offset = 0
        for line in text.splitlines(keepends=True):
            stripped = line.strip()
            if stripped and len(stripped) <= CHAPTER_TITLE_CHARS and CHAPTER_RE.match(stripped):
                found.append({"title": stripped, "offset": offset})
            offset += len(line)

        heads = found
        if found:
            # 第一章之前通常还有书名、作者、简介：单独给一条，免得那段文字没有入口跳过去。
            if found[0]["offset"] > 0:
                heads = [{"title": "开头（章节之前）", "offset": 0}] + found
        else:
            heads = [{"title": "全文", "offset": 0}]

        window = heads[:limit]
        chapters: list[dict[str, Any]] = []
        for index, head in enumerate(window):
            start = head["offset"]
            # 末章的结尾就是全篇结尾：拿"下一章的开头"当结尾，等于把它自己的标题也算进去。
            end = window[index + 1]["offset"] if index + 1 < len(window) else total
            chapters.append(
                {
                    "index": index + 1,
                    "title": head["title"],
                    "offset": start,
                    "chars": max(0, end - start),
                }
            )
        return {
            "name": name,
            "path": str(path),
            "encoding": encoding,
            "total_chars": total,
            "count": len(heads),
            "returned": len(chapters),
            "truncated": len(heads) > limit,
            "limit": limit,
            "chapters": chapters,
            "message": "" if found else "这篇没切出章节（整行标题一条也没认出来）：按页码翻，或搜一串字跳过去",
        }

    # ---- search ---------------------------------------------------------

    def search(
        self, name: str, needle: str, limit: int = DEFAULT_SEARCH_LIMIT
    ) -> dict[str, Any]:
        """在原文里找一串字，回它出现的位置（面板点一下就跳到那儿）。

        只看字面，不分词、不忽略大小写：用户是从记得的那句话里挑几个字来跳转的，
        把"张 三"当"张三"、或把大小写当同一回事，都会给出他没要的位置。
        """
        query = str(needle)
        if query.strip() == "":
            raise NovelsError("要搜的字符串不能是空白")
        if limit < 1:
            raise NovelsError(f"limit 不能小于 1，给的是 {limit}")
        if limit > MAX_SEARCH_LIMIT:
            raise NovelsError(f"limit 最多 {MAX_SEARCH_LIMIT}，给的是 {limit}")
        path = self._resolve(name)
        if not path.is_file():
            raise NovelsError(f"原文目录里没有这一篇: {name}")
        text, encoding = self._text(path, name)

        hits: list[dict[str, Any]] = []
        start = 0
        while len(hits) < limit:
            at = text.find(query, start)
            if at < 0:
                break
            hits.append({"offset": at, "snippet": _snippet(text, at, at + len(query))})
            start = at + len(query)
        # 还要再试着找一处，才知道是"就这么多"还是"被 limit 截了"：多扫一次比谎报总数便宜。
        truncated = bool(hits) and len(hits) >= limit and text.find(query, start) >= 0
        return {
            "name": name,
            "path": str(path),
            "encoding": encoding,
            "total_chars": len(text),
            "query": query,
            "matched": len(hits),
            "truncated": truncated,
            "limit": limit,
            "matches": hits,
        }

    # ---- import ---------------------------------------------------------

    def import_file(
        self, path: str, name: str | None = None, overwrite: bool = False
    ) -> dict[str, Any]:
        """把本机一份 txt/md 接进原文目录（导第一本时顺手把目录建出来）。

        同名怎么办：**默认不覆盖**，直接回一条 ``imported: false`` / ``reason: "exists"``
        （不是异常 —— 这是"要你确认一下"，不是出错），面板据此把「覆盖导入」那个按钮露出来；
        带 ``overwrite=True`` 再来一次才真的替换。

        这里有意不学 :mod:`comfy_studio.localfiles` 的 ``name (1).ext``：那座库要的是
        "同一份素材接两次不重复占地方"，而书库里同一本书来两份，只会让人拿不准该用哪一本
        去改编。其余不成立的情况（源文件不在、不是 txt/md、拷不动）照旧抛 :class:`NovelsError`。
        """
        source = Path(path).expanduser()
        if not source.exists():
            raise NovelsError(f"本地文件不存在: {source}")
        if not source.is_file():
            raise NovelsError(f"这是个目录，不是文件: {source}")
        real = Path(os.path.realpath(source))
        if not real.is_file():
            raise NovelsError(f"跟随链接之后仍然不是文件: {source} -> {real}")

        if name is not None and Path(name).name != name:
            raise NovelsError(f"name 只能是文件名，不能带路径: {name}")
        target_name = name if name else real.name
        if Path(target_name).suffix.lower() not in TEXT_SUFFIXES:
            raise NovelsError(
                f"接得了的只有 {'、'.join(TEXT_SUFFIXES)} 原文，这个是 {target_name}"
            )

        root = self.directory
        created_dir = not root.is_dir()
        root.mkdir(parents=True, exist_ok=True)
        dest = root / target_name
        if not is_within(root, dest):
            raise NovelsError(f"目标路径跑到原文目录外面了: {dest}")

        replaced = dest.exists()
        if replaced and not overwrite:
            size = dest.stat().st_size
            return {
                "imported": False,
                "reason": "exists",
                "name": target_name,
                "path": str(dest),
                "bytes": size,
                "source": str(real),
                "overwritten": False,
                "created_dir": False,
                "message": (
                    f"原文目录里已经有 {target_name} 了（{size} 字节）："
                    "要换成你这份就带 overwrite 再来一次"
                ),
            }
        if replaced and os.path.realpath(dest) == os.path.realpath(real):
            # 源和目标就是同一个文件：拷下去等于把它清空（copy2 同源同目标），拦下来。
            raise NovelsError(f"这就是原文目录里的那一份，不用再导一次: {dest}")

        try:
            shutil.copy2(real, dest)
        except OSError as err:
            raise NovelsError(f"拷不进去: {err}") from err
        return {
            "imported": True,
            "reason": "",
            "message": "",
            "name": target_name,
            "path": str(dest),
            "bytes": dest.stat().st_size,
            "source": str(real),
            "overwritten": replaced,
            "created_dir": created_dir,
        }

    # ---- delete ---------------------------------------------------------

    def delete(self, name: str) -> dict[str, Any]:
        """删掉一篇原文。

        真删，不挪回收站：这是用户在面板上点了两下才走到的动作，宿主不该替人留后手还假装
        删了。返回删掉的是哪个文件、多大，好让面板把这句话说完整（说得出就只能删对）。
        """
        path = self._resolve(name)
        if not path.is_file():
            raise NovelsError(f"原文目录里没有这一篇: {name}")
        try:
            size = path.stat().st_size
            path.unlink()
        except OSError as err:
            raise NovelsError(f"删不掉 {path}: {err}") from err
        return {"name": name, "path": str(path), "bytes": size, "deleted": True}

    # ---- 内部 -----------------------------------------------------------

    def _text(self, path: Path, name: str) -> tuple[str, str]:
        """整篇解好的正文，回 ``(text, 编码)``。翻页、目录、搜索都从这里拿。

        解一遍要几百毫秒到几秒（得把整篇读完再判编码），而用户是一页一页翻的 —— 所以
        最近读过的几篇留着（:data:`CACHE_MAX_ENTRIES`）。缓存键里带 (路径, 大小, 改于何时)：
        文件被外面改了（编辑、重导一份）就自然失效，不会拿旧内容糊弄人。
        上面那条大小线也在这里判：目录、搜索与分页走同一个门，免得"能翻页却搜不了"。
        """
        try:
            info = path.stat()
        except OSError as err:
            raise NovelsError(f"读不了 {path}: {err}") from err
        if info.st_size > MAX_TEXT_BYTES:
            raise NovelsError(
                f"{path.name} 有 {info.st_size / 1024 / 1024:.1f} MB，超过面板翻页的上限 "
                f"{MAX_TEXT_BYTES / 1024 / 1024:.0f} MB：用编辑器看原文，或先切成几篇"
            )

        key = (str(path), info.st_size, info.st_mtime_ns)
        hit = self._cache.get(key)
        if hit is not None:
            self._cache.move_to_end(key)
            return hit
        try:
            raw = path.read_bytes()
        except OSError as err:
            raise NovelsError(f"读不了 {path}: {err}") from err
        text, encoding = decode_text(raw, name)
        self._cache[key] = (text, encoding)
        while len(self._cache) > CACHE_MAX_ENTRIES:
            self._cache.popitem(last=False)
        return text, encoding

    def _resolve(self, name: str) -> Path:
        """把面板给的名字（``list`` 里那一列）还原成目录里的路径，并挡住越界。

        只收**相对名字**：绝对路径进来就拒。面板拿到的名字本来就来自 :meth:`list`，
        收绝对路径等于把"能删哪个文件"的决定权交回给调用方。
        隐藏项同样拒：:meth:`list` 里不出现的东西，不该能从这条路上读到 —— 而 :meth:`delete`
        走的正是同一条路，``.git/config`` 这种名字落在原文目录里是**真文件**，不拦就是能删。
        """
        raw = str(name).strip().replace("\\", "/")
        if raw == "":
            raise NovelsError("name 必须是非空字符串")
        if raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
            raise NovelsError(f"name 只能是原文目录里的相对名字: {name}")
        target = self.directory / raw
        if not is_within(self.directory, target):
            raise NovelsError(f"这个名字跑到原文目录外面去了: {name}")
        # 越界先判（`../x` 归上面那条管，报错才说得准），隐藏项后判。
        if any(part.startswith(".") for part in raw.split("/")):
            raise NovelsError(f"name 不能指向隐藏项（列表里没有它）: {name}")
        return target


def resolve_novel(library: NovelLibrary, name: str) -> str:
    """按名字取一份原文的路径；比不中就报错，并**列出现在有什么**。

    名字拿去比 :meth:`NovelLibrary.list` 的 ``name`` 那一列，**不自己拼路径**：越界那类
    （``../``、绝对路径、隐藏项）由 :meth:`NovelLibrary._resolve` 统一挡，在这儿再实现一遍
    就是两份规则，早晚分家。名字是面板给的，也是对话里的流水线工具给的 —— 两个入口共用
    这一条，免得"哪种名字算存在"两边各有一套。
    """
    listing = library.list(limit=MAX_LIST_LIMIT)
    entries = listing.get("novels", [])
    names = [entry.get("name") for entry in entries]
    for entry in entries:
        if entry.get("name") != name:
            continue
        if not entry.get("text"):
            raise NovelsError(f"{name!r} 不是 txt/md，读不了")
        return str(entry.get("path"))
    known = "、".join(str(item) for item in names if item) or "（一本都没有）"
    raise NovelsError(f"原文库里没有 {name!r}；现在有的是：{known}")


__all__ = [
    "CACHE_MAX_ENTRIES",
    "CHAPTER_RE",
    "CHAPTER_TITLE_CHARS",
    "CJK_RATIO",
    "DEFAULT_CHAPTER_LIMIT",
    "DEFAULT_LIST_LIMIT",
    "DEFAULT_READ_CHARS",
    "DEFAULT_SEARCH_LIMIT",
    "GARBAGE_RATIO",
    "MANJU_REL",
    "MAX_CHAPTER_LIMIT",
    "MAX_LIST_LIMIT",
    "MAX_READ_CHARS",
    "MAX_SEARCH_LIMIT",
    "MAX_TEXT_BYTES",
    "NOVEL_SUBDIR",
    "NovelLibrary",
    "NovelsError",
    "SEARCH_WINDOW",
    "SNIFF_CHARS",
    "TEXT_SUFFIXES",
    "decode_text",
    "default_novel_dir",
    "resolve_novel",
]
