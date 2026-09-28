let cachedScript: string | null = null

/**
 * Canvas-side conversation panel for comfy-studio.
 *
 * Injected into the hosted frontend like the MCP sidebar / terminal scripts: it
 * adds a sidebar button and a right-hand drawer, then talks to the desktop-side
 * comfy-studio host over `window.__comfyDesktop2.ComfyStudio` (main-spawned
 * python, see `lib/comfy_studio`). All the actual work — MCP servers, skill
 * catalog, the LLM loop — happens in that host; this file is just the surface.
 *
 * Turn model: one turn at a time. `agent/event` notifications carry a session id
 * rather than a turn id, so the drawer paints events only while one of its turns
 * is in flight, and only those of the session it talks to. `final` is deliberately
 * left unpainted: the same text comes back as the request result, and painting
 * both would duplicate it.
 *
 * Rendering: an event is a node and each kind draws itself. The host's stream is
 * coarse — narration, tool call, tool result — not token-by-token, so nothing
 * here fakes a token stream. A tool result pairs with its call by the `id` both
 * events carry, so it updates the card that call opened instead of appending a
 * second row; long arguments and results fold behind a button.
 *
 * The header carries a model picker (`agent/models` for the catalog, then
 * `agent/model` to switch). Switching is disabled mid-turn: the host replaces the
 * HTTP client behind each idle session, and doing that under a turn in flight
 * would cut it off.
 *
 * Right below it sits the agent picker (`agent/agents` for the catalog, then
 * `agent/agent` to switch) — the same shape for a different question: which
 * persona is answering. It only swaps the role paragraph of the system prompt
 * (lib/comfy_studio/agent/catalog.py), so the tool table and the transcript stay
 * where they are and the next turn picks it up; entries the host could not read
 * are drawn as disabled rows with the reason in their tooltip instead of quietly
 * disappearing from the list.
 *
 * Under it sits the session row: one conversation is one `session_id`, so the row
 * offers the host's list (`agent/sessions`), switching to another one (repainted
 * from that conversation's archive), starting a new one (the panel picks the id)
 * and closing the current one (`agent/close` — frees the slot, keeps the archive,
 * unlike `agent/reset`, which clears the conversation itself). Unreadable archives
 * are listed as an unpickable row instead of being dropped, and with `--no-history`
 * closing really does discard the conversation, so it takes a second click. All
 * three controls are disabled while a turn is in flight: the answer is painted onto
 * the conversation that asked, so moving away mid-turn would paint it onto another
 * one. The only panel state that outlives a reload is which `session_id` it was on.
 *
 * A turn in flight can be stopped from the composer (`agent/cancel`). Stopping is
 * not a failure: the host still answers `agent/chat` normally, with `cancelled:
 * true`, and the history stays paired so the next message just continues the
 * conversation. That is why the answer paints a muted `已停止` row rather than an
 * error, and why the transport-level rejection path below stays for real failures
 * only.
 *
 * Coming back: this surface and the host have separate lifetimes, so a reload here
 * (new canvas, reloaded page) would show an empty drawer even though the host still
 * holds the conversation — and a host restart would lose it entirely if not for the
 * on-disk archive (`lib/comfy_studio/history.py`). Opening the drawer therefore asks
 * `agent/history` once and repaints itself with the same painters the live events
 * use, so resuming looks exactly like never having left. Only an empty drawer is
 * filled: anything already painted came from this screen's own turn.
 *
 * Where it keeps things: opening the drawer also asks `host/info` for one line under
 * the status — the memory file and the archive directory, spelled out in its tooltip.
 * It is also where the states that look like bugs but are not get said out loud: a
 * host started with `--no-memory` / `--no-history`, and a memory file that cannot be
 * read (`memory_error`), which fails *every* turn because the persona is rebuilt from
 * memory each time. Nothing is guessed — a field the host did not report is reported
 * as unknown.
 *
 * Canvas: the host's `canvas__*` tools need the live graph, which only this page
 * has, so the shell reaches back with `executeJavaScript` and calls
 * `window.__comfyStudioChat.canvasCall(op, args)` here. Every op is a thin wrapper
 * over the ComfyUI frontend's own `window.comfyAPI.app.app`, and a missing global
 * is reported as an error rather than as an empty graph.
 *
 * Review: `review__ask_user` (see `lib/comfy_studio/review.py`) parks the host's
 * turn until a human answers, and the only human in reach is the one looking at
 * this drawer. The event paints a question card; submitting it posts
 * `agent/answer`. An answer that arrives after the host stopped waiting comes
 * back as `delivered: false` — late, not wrong — so the card just says so.
 *
 * Plan: `plan__submit` (see `lib/comfy_studio/plan.py`) is the same round trip
 * one step earlier — a raw idea gets broken into a checklist and parked until
 * the user nods. The card paints the steps plus two buttons (`就按这个来` /
 * `改一下` + a line of feedback) and posts `agent/plan_result`. `plan__progress`
 * is the one-way sibling: it ticks a step in whichever checklist the current
 * turn painted, so nothing needs to wait on a notification.
 */
const STUDIO_CHAT_MAIN_JS = `
var STATE = window.__comfyStudioChat;
var bridge = window.__comfyDesktop2.ComfyStudio;

var BTN_ID = 'comfy-desktop-studio-chat-btn';
var DRAWER_ID = 'comfy-desktop-studio-chat';
var LOG_ID = 'comfy-desktop-studio-chat-log';
var STATUS_ID = 'comfy-desktop-studio-chat-status';
var INPUT_ID = 'comfy-desktop-studio-chat-input';
var SEND_ID = 'comfy-desktop-studio-chat-send';
var STOP_ID = 'comfy-desktop-studio-chat-stop';
var MODEL_ID = 'comfy-desktop-studio-chat-model';
// 模型下拉里 option 的值是"来源::模型名"（如 DeepSeek::deepseek-v4-pro）：同一个名字换一家地址
// 就未必成立，所以切换必须把来源一起带上。这两个值与宿主 settings.py 的 SOURCE_SEPARATOR、
// server.py 的 DEFAULT_SOURCE 是同一份约定，改那边这里要跟着改。
var MODEL_SOURCE_SEP = '::';
var MODEL_SOURCE_DEFAULT = 'default';
var AGENT_ID = 'comfy-desktop-studio-chat-agent';
var SKILL_ID = 'comfy-desktop-studio-chat-skill';
var SKILL_RUN_ID = 'comfy-desktop-studio-chat-skill-run';
// 渲染目标那一行（引擎侧那 12 张生产工作流，见宿主 lib/comfy_studio/renders/catalog.py）：
// 下拉 + 参数区 + 跑一遍。参数区里摆的是**必填且没默认值的那些**，参考图输入框按需插在里面
// （只有引擎报 referenceImages 的目标才摆，见 fillRenderArgs）。
var RENDER_ID = 'comfy-desktop-studio-chat-render';
var RENDER_RUN_ID = 'comfy-desktop-studio-chat-render-run';
var RENDER_ARGS_ID = 'comfy-desktop-studio-chat-render-args';
// 每个必填参数一个输入框，id 是前缀 + 参数名：取回来时按同一套名字找（见 renderArgValues）。
var RENDER_ARG_PREFIX = 'comfy-desktop-studio-chat-render-arg-';
var RENDER_IMAGES_ID = 'comfy-desktop-studio-chat-render-images';
var SESSION_ID = 'comfy-desktop-studio-chat-session';
var SESSION_NEW_ID = 'comfy-desktop-studio-chat-session-new';
var SESSION_CLOSE_ID = 'comfy-desktop-studio-chat-session-close';
// 「清空」是与「关掉」不同的一件事：关掉只腾会话位（对话留在存档里），清空是把这一段说过的话
// 与它的存档一起抹掉（宿主 agent/reset，见 lib/comfy_studio/server.py 的 agent_reset）。
var SESSION_RESET_ID = 'comfy-desktop-studio-chat-session-reset';
var STORAGE_ID = 'comfy-desktop-studio-chat-storage';
var TABS_ID = 'comfy-desktop-studio-chat-tabs';
var CHAT_VIEW_ID = 'comfy-desktop-studio-chat-view';
var NOVEL_VIEW_ID = 'comfy-desktop-studio-novel-view';
var NOVEL_LIST_ID = 'comfy-desktop-studio-novel-list';
var NOVEL_HINT_ID = 'comfy-desktop-studio-novel-hint';
var NOVEL_FORM_ID = 'comfy-desktop-studio-novel-form';
// 导入弹窗里那份提示行：它盖住了页顶那条，所以同一句话要在卡片里再说一遍（见 importHint）。
var NOVEL_FORM_HINT_ID = 'comfy-desktop-studio-novel-form-hint';
var NOVEL_PATH_ID = 'comfy-desktop-studio-novel-path';
var NOVEL_READER_ID = 'comfy-desktop-studio-novel-reader';
var NOVEL_PAGER_ID = 'comfy-desktop-studio-novel-pager';
// 正文左边那一栏：这一篇的章节目录 / 全文搜索结果（见 loadChapters 与 searchNovel）。
var NOVEL_BODY_ID = 'comfy-desktop-studio-novel-body';
var NOVEL_MAIN_ID = 'comfy-desktop-studio-novel-main';
var NOVEL_SIDE_ID = 'comfy-desktop-studio-novel-side';
var NOVEL_SIDE_HEAD_ID = 'comfy-desktop-studio-novel-side-head';
var NOVEL_SIDE_LIST_ID = 'comfy-desktop-studio-novel-side-list';
var NOVEL_SEARCH_ID = 'comfy-desktop-studio-novel-search';
// 顶上那个「目录」开关，以及搜索结果旁边那个「返回目录」。
var NOVEL_TOC_ID = 'comfy-desktop-studio-novel-toc';
var NOVEL_TOC_BACK_ID = 'comfy-desktop-studio-novel-toc-back';
// 项目管理那一页（见 buildProjectView）：一剧一目录，格子与阶段进度全由宿主
// projects/tree 给（它读的是 manju 工作流里那份 src/project.py），这一页一份都不抄。
var PROJECT_VIEW_ID = 'comfy-desktop-studio-project-view';
var PROJECT_HINT_ID = 'comfy-desktop-studio-project-hint';
var PROJECT_FORM_ID = 'comfy-desktop-studio-project-form';
var PROJECT_FORM_NAME_ID = 'comfy-desktop-studio-project-form-name';
var PROJECT_FORM_EPISODES_ID = 'comfy-desktop-studio-project-form-episodes';
var PROJECT_FORM_NOVEL_ID = 'comfy-desktop-studio-project-form-novel';
var PROJECT_FORM_UPGRADE_ID = 'comfy-desktop-studio-project-form-upgrade';
// 弹窗里那份提示行：它盖住了页顶那条，所以同一句话要在卡片里再说一遍（见 projectHint）。
var PROJECT_FORM_HINT_ID = 'comfy-desktop-studio-project-form-hint';
var PROJECT_LIST_ID = 'comfy-desktop-studio-project-list';
var PROJECT_MAIN_ID = 'comfy-desktop-studio-project-main';
var PROJECT_HEAD_ID = 'comfy-desktop-studio-project-head';
var PROJECT_SHELVES_ID = 'comfy-desktop-studio-project-shelves';
var PROJECT_READER_ID = 'comfy-desktop-studio-project-reader';
var PROJECT_PAGER_ID = 'comfy-desktop-studio-project-pager';
// 对话里的"找字"（见 buildFindRow）：只在这一段对话里找，不碰「管理小说」那页的正文搜索。
var FIND_ID = 'comfy-desktop-studio-chat-find';
var FIND_COUNT_ID = 'comfy-desktop-studio-chat-find-count';
var FIND_PREV_ID = 'comfy-desktop-studio-chat-find-prev';
var FIND_NEXT_ID = 'comfy-desktop-studio-chat-find-next';
var FIND_CLEAR_ID = 'comfy-desktop-studio-chat-find-clear';
// 项目管理页的两处检索（见 buildProjectFind / buildProjectFileFind）：一处筛项目名，
// 一处只在**已经读出来的那一页正文**里找字。两处能力边界不同，界面上要分开说：
// 筛项目走的是宿主 projects/list 的 name 子串过滤（同 projects.py 的 list(query)），
// 是"在整个项目目录里找"；页内找字宿主没有对应口子（projects/read 只接 offset/chars），
// 所以它只在这一页里算，跟「管理小说」那页的全文搜索不是一回事。
var PROJECT_FIND_ID = 'comfy-desktop-studio-project-find';
var PROJECT_FIND_COUNT_ID = 'comfy-desktop-studio-project-find-count';
var PROJECT_OVERVIEW_ID = 'comfy-desktop-studio-project-overview';
var PROJECT_FILE_FIND_ID = 'comfy-desktop-studio-project-file-find';
var PROJECT_FILE_FIND_COUNT_ID = 'comfy-desktop-studio-project-file-find-count';
var PROJECT_FILE_FIND_PREV_ID = 'comfy-desktop-studio-project-file-find-prev';
var PROJECT_FILE_FIND_NEXT_ID = 'comfy-desktop-studio-project-file-find-next';
var PROJECT_FILE_FIND_CLEAR_ID = 'comfy-desktop-studio-project-file-find-clear';
// 「管理小说」页的批量那一栏（见 buildNovelBatch 与 deletePicked）。
var NOVEL_BATCH_ID = 'comfy-desktop-studio-novel-batch';
var NOVEL_BATCH_ALL_ID = 'comfy-desktop-studio-novel-batch-all';
var NOVEL_BATCH_NONE_ID = 'comfy-desktop-studio-novel-batch-none';
var NOVEL_BATCH_DELETE_ID = 'comfy-desktop-studio-novel-batch-delete';
// 「管理小说」与「项目管理」这两页**占满窗口**的那一层（见 buildViewsOverlay）。
// 它们是"翻资料"的地方 —— 一篇原文、一列落点、一份分镜表都要地方，
// 挤在抽屉那条窄缝里读长文，人只会把抽屉拖宽到盖住整页，那还不如一开始就占满。
var VIEWS_ID = 'comfy-desktop-studio-views';
var VIEWS_TITLE_ID = 'comfy-desktop-studio-views-title';
var VIEWS_BACK_ID = 'comfy-desktop-studio-views-back';
// 「流水线」那一页（见 buildPipelineView）：把 S0–S7 接到随包那七位智能体上，一段一段跑。
// 这一页**一条规则都不抄**：阶段、谁做、落点、要不要引擎侧渲染，全来自宿主 pipeline/plan
// 那一趟回话（形状由 lib/comfy_studio/pipeline.py 的 plan_payload 定，与对话里
// pipeline__plan 同一份）—— 面板自己写一张阶段表，就会出现"面板说还差 S4、模型说跑完了"。
var PIPELINE_VIEW_ID = 'comfy-desktop-studio-pipeline-view';
var PIPELINE_HINT_ID = 'comfy-desktop-studio-pipeline-hint';
var PIPELINE_OVERVIEW_ID = 'comfy-desktop-studio-pipeline-overview';
var PIPELINE_LIST_ID = 'comfy-desktop-studio-pipeline-list';
var PIPELINE_PROJECT_ID = 'comfy-desktop-studio-pipeline-project';
var PIPELINE_NOVEL_ID = 'comfy-desktop-studio-pipeline-novel';
var PIPELINE_EPISODES_ID = 'comfy-desktop-studio-pipeline-episodes';
var PIPELINE_FROM_ID = 'comfy-desktop-studio-pipeline-from';
var PIPELINE_TO_ID = 'comfy-desktop-studio-pipeline-to';
var PIPELINE_FORCE_ID = 'comfy-desktop-studio-pipeline-force';
// 跑之前那张确认卡（见 askPipelineRun）：这一页要按段调模型、动辄十几分钟，按下去之前
// 把人话摆出来 —— 跑几段、跳几段、哪几段跑完还得引擎侧渲染。
var PIPELINE_FORM_ID = 'comfy-desktop-studio-pipeline-form';
var PIPELINE_FORM_HINT_ID = 'comfy-desktop-studio-pipeline-form-hint';
var PIPELINE_FORM_TEXT_ID = 'comfy-desktop-studio-pipeline-form-text';
// 输入框上方那一栏引用卡（见 paintQuotes / composeQuotes：引用原文那条通道）。
var QUOTE_BAR_ID = 'comfy-desktop-studio-quote-bar';
// 抽屉左沿那只调宽的手（见 installResizeGrip）。
var GRIP_ID = 'comfy-desktop-studio-chat-grip';
// 模型行右边那个「配置…」按钮与它下面那张表单（见 buildModelForm / saveSettings）。
var MODEL_CONFIG_ID = 'comfy-desktop-studio-model-config';
var MODEL_FORM_ID = 'comfy-desktop-studio-model-form';
var MODEL_FORM_HINT_ID = 'comfy-desktop-studio-model-form-hint';
var MODEL_FORM_MODEL_ID = 'comfy-desktop-studio-model-form-model';
var MODEL_FORM_URL_ID = 'comfy-desktop-studio-model-form-url';
var MODEL_FORM_KEY_ID = 'comfy-desktop-studio-model-form-key';
var MODEL_FORM_PATH_ID = 'comfy-desktop-studio-model-form-path';
var MODEL_FORM_SAVE_ID = 'comfy-desktop-studio-model-form-save';
var MODEL_FORM_CLEAR_ID = 'comfy-desktop-studio-model-form-clear';
var MODEL_FORM_CANCEL_ID = 'comfy-desktop-studio-model-form-cancel';

// 这三个键名就是宿主认的环境变量名（宿主那边见 lib/comfy_studio/settings.py）：
// 面板写进去的值最后落成它们，用户想改回环境变量也知道该设哪个名字。
var MODEL_ENV = 'COMFY_STUDIO_LLM_MODEL';
var BASE_URL_ENV = 'COMFY_STUDIO_LLM_BASE_URL';
var API_KEY_ENV = 'COMFY_STUDIO_LLM_API_KEY';

var MUTED = 'var(--content-fg,#9b9b9b)';
var FG = 'var(--fg-color,#e5e5e5)';
var SURFACE = 'var(--interface-panel-surface, var(--comfy-menu-bg,#202020))';
var BORDER = 'var(--border-color,#4e4e4e)';
var INPUT_BG = 'var(--comfy-input-bg,#333)';

var STYLE_ID = 'comfy-desktop-studio-chat-style';

// 消息区的样式走一张 <style>，不走内联：一行/一张卡的状态是会变的
// （工具从"运行中"到"完成/失败"），内联只能靠改 style 一条条追，而
// [data-state=...] 这种选择器写不出来。这跟参考实现里 data-streaming /
// data-state 驱动样式的约定是一回事。
// 全部规则都收在 #DRAWER_ID 下面，不往托管页面上撒全局类名。
var CHAT_CSS =
  '@keyframes cs-pulse{0%,100%{opacity:.25}50%{opacity:1}}' +
  '#' + DRAWER_ID + '{--cs-radius:6px;--cs-mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;}' +
  // 抽屉宽窄由人拖：左沿这条 6px 就是那只手（见 installResizeGrip）。够抓，又不占正文。
  '#' + DRAWER_ID + ' .cs-grip{position:absolute;left:0;top:0;bottom:0;width:6px;' +
  'cursor:col-resize;background:transparent;touch-action:none;}' +
  '#' + DRAWER_ID + ' .cs-grip:hover{background:' + BORDER + ';opacity:.6;}' +
  '#' + DRAWER_ID + ' .cs-grip[data-drag="1"]{background:' + BORDER + ';opacity:1;}' +
  // 面板里的模型配置表单（见 buildModelForm / saveSettings）：收起时只剩模型行右边一个按钮。
  '#' + DRAWER_ID + ' .cs-model-form{display:none;flex-direction:column;gap:6px;padding:0 12px 8px;}' +
  '#' + DRAWER_ID + ' .cs-model-form[data-open="1"]{display:flex;}' +
  '#' + DRAWER_ID + ' .cs-model-field{display:flex;align-items:center;gap:6px;}' +
  '#' + DRAWER_ID + ' .cs-model-label{color:' + MUTED + ';font-size:11px;white-space:nowrap;}' +
  '#' + DRAWER_ID + ' .cs-model-input{flex:1;min-width:0;box-sizing:border-box;padding:2px 6px;' +
  'border-radius:4px;border:1px solid ' + BORDER + ';background:' + INPUT_BG + ';color:' + FG + ';' +
  'font:inherit;font-size:11px;}' +
  '#' + DRAWER_ID + ' .cs-model-hint{color:' + MUTED + ';font-size:11px;}' +
  '#' + DRAWER_ID + ' .cs-model-hint[data-tone="error"]{color:#ff8080;}' +
  '#' + DRAWER_ID + ' .cs-model-actions{display:flex;gap:6px;}' +
  '#' + DRAWER_ID + ' .cs-model-btn{border:1px solid ' + BORDER + ';border-radius:4px;' +
  'background:transparent;color:' + MUTED + ';cursor:pointer;font:inherit;font-size:11px;padding:2px 8px;}' +
  '#' + DRAWER_ID + ' .cs-model-btn:hover{background:' + INPUT_BG + ';color:' + FG + ';}' +
  // 「管理小说」「项目管理」占满窗口的那一层（见 buildViewsOverlay）：
  // fixed 是**这里的关键**（相对视口铺满，不是相对抽屉），z-index 高过抽屉自己的 2000，
  // 底色用同一块背景板 —— 换成纯黑会在页面上撕出一块"洞"。
  '#' + DRAWER_ID + ' .cs-views{position:fixed;inset:0;z-index:2001;display:none;' +
  'flex-direction:column;box-sizing:border-box;background:' + SURFACE + ';color:' + FG + ';}' +
  '#' + DRAWER_ID + ' .cs-views[data-open="1"]{display:flex;}' +
  '#' + DRAWER_ID + ' .cs-views-head{flex:0 0 auto;display:flex;align-items:center;gap:6px;' +
  'padding:8px 12px;border-bottom:1px solid ' + BORDER + ';}' +
  '#' + DRAWER_ID + ' .cs-views-title{flex:1;min-width:0;color:' + FG + ';font-size:13px;' +
  'font-weight:600;word-break:break-all;}' +
  '#' + DRAWER_ID + ' .cs-views-back{border:1px solid ' + BORDER + ';border-radius:4px;' +
  'background:transparent;color:' + MUTED + ';cursor:pointer;font:inherit;font-size:12px;' +
  'padding:3px 8px;white-space:nowrap;}' +
  '#' + DRAWER_ID + ' .cs-views-back:hover{background:' + INPUT_BG + ';color:' + FG + ';}' +
  '#' + DRAWER_ID + ' .cs-row{white-space:pre-wrap;word-break:break-word;padding:6px 8px;border-radius:var(--cs-radius);}' +
  '#' + DRAWER_ID + ' .cs-user{align-self:flex-end;max-width:85%;background:var(--comfy-input-bg,#3a3a3a);}' +
  '#' + DRAWER_ID + ' .cs-agent{align-self:flex-start;max-width:90%;background:transparent;}' +
  // 最终答案是这一轮的主角（narration 只是过程中的话），给它加一条左侧标记
  '#' + DRAWER_ID + ' .cs-agent[data-variant="final"]{border-left:2px solid ' + BORDER + ';padding-left:8px;}' +
  '#' + DRAWER_ID + ' .cs-error{align-self:stretch;color:#ff8080;border:1px solid #ff808055;background:#ff80800f;}' +
  // 停下的一轮不是错误：一条灰色括注就够，别用错误那条红边框把人吓一跳
  '#' + DRAWER_ID + ' .cs-stopped{align-self:flex-start;color:' + MUTED + ';font-size:12px;' +
  'border-left:2px solid ' + BORDER + ';padding-left:8px;}' +
  '#' + DRAWER_ID + ' .cs-pending{align-self:flex-start;display:flex;align-items:center;gap:6px;color:' + MUTED + ';font-size:12px;}' +
  '#' + DRAWER_ID + ' .cs-pending .cs-dot{animation:cs-pulse 1.2s ease-in-out infinite;}' +
  // "强制复位"那颗小按钮：等太久之后才摆出来（见 offerForceReset）。
  '#' + DRAWER_ID + ' .cs-pending .cs-force-reset{border:1px solid ' + BORDER + ';border-radius:4px;' +
  'background:transparent;color:' + MUTED + ';cursor:pointer;font:inherit;font-size:11px;padding:1px 6px;}' +
  '#' + DRAWER_ID + ' .cs-pending .cs-force-reset:hover{background:' + INPUT_BG + ';color:' + FG + ';}' +
  // flex:0 0 auto 跟目录行那条是同一个道理：对话流是 flex 列（见 buildDrawer 里的 log 内联样式），
  // 而这张卡上有 overflow:hidden（圆角要裁掉子元素边角），它的 automatic minimum size 因此被算成 0
  // —— 一轮里工具卡一多，几张卡就会被一起压扁，字被裁掉。卡片不参与收缩，高度由内容自己定。
  '#' + DRAWER_ID + ' .cs-tool{flex:0 0 auto;align-self:stretch;border:1px solid ' + BORDER + ';padding:0;overflow:hidden;}' +
  '#' + DRAWER_ID + ' .cs-tool-head{display:flex;align-items:center;gap:6px;width:100%;box-sizing:border-box;' +
  'border:none;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer;padding:6px 8px;}' +
  '#' + DRAWER_ID + ' .cs-tool-head:hover{background:' + INPUT_BG + ';}' +
  '#' + DRAWER_ID + ' .cs-dot{flex:none;width:7px;height:7px;border-radius:50%;background:' + MUTED + ';}' +
  '#' + DRAWER_ID + ' .cs-tool[data-state="running"] .cs-dot{background:#e0b400;animation:cs-pulse 1.2s ease-in-out infinite;}' +
  '#' + DRAWER_ID + ' .cs-tool[data-state="done"] .cs-dot{background:#3fa34d;}' +
  '#' + DRAWER_ID + ' .cs-tool[data-state="error"] .cs-dot{background:#d9534f;}' +
  '#' + DRAWER_ID + ' .cs-tool-name{font-family:var(--cs-mono);font-size:12px;}' +
  '#' + DRAWER_ID + ' .cs-tool-server{color:' + MUTED + ';font-size:11px;}' +
  '#' + DRAWER_ID + ' .cs-tool-state{margin-left:auto;color:' + MUTED + ';font-size:11px;white-space:nowrap;}' +
  '#' + DRAWER_ID + ' .cs-tool[data-state="error"] .cs-tool-state{color:#ff8080;}' +
  '#' + DRAWER_ID + ' .cs-tool-body{border-top:1px solid ' + BORDER + ';padding:6px 8px;}' +
  '#' + DRAWER_ID + ' .cs-tool[data-collapsed="1"] .cs-tool-body{display:none;}' +
  '#' + DRAWER_ID + ' .cs-block-label{color:' + MUTED + ';font-size:11px;margin:4px 0 2px;}' +
  '#' + DRAWER_ID + ' .cs-block{margin:0;font-family:var(--cs-mono);font-size:11px;white-space:pre-wrap;' +
  'word-break:break-word;max-height:220px;overflow:auto;}' +
  '#' + DRAWER_ID + ' .cs-block-more{border:1px solid ' + BORDER + ';border-radius:4px;background:transparent;' +
  'color:' + MUTED + ';cursor:pointer;font:inherit;font-size:11px;padding:1px 6px;margin-top:4px;}' +
  // 审核节点：agent 停下来问用户。问句是主角，给一条琥珀色边，跟工具卡的灰边分开；
  // 答完的状态（已答 / 没赶上 / 没送到）用 data-state 换边色，不再靠改内联样式。
  '#' + DRAWER_ID + ' .cs-ask{align-self:stretch;display:flex;flex-direction:column;gap:6px;' +
  'border:1px solid #e0b40055;background:#e0b4000f;}' +
  '#' + DRAWER_ID + ' .cs-ask-q{font-weight:600;}' +
  '#' + DRAWER_ID + ' .cs-ask-options{display:flex;flex-wrap:wrap;gap:6px;}' +
  '#' + DRAWER_ID + ' .cs-ask-option{border:1px solid ' + BORDER + ';border-radius:4px;background:transparent;' +
  'color:inherit;cursor:pointer;font:inherit;font-size:12px;padding:3px 8px;}' +
  '#' + DRAWER_ID + ' .cs-ask-option:hover{background:' + INPUT_BG + ';}' +
  '#' + DRAWER_ID + ' .cs-ask-form{display:flex;gap:6px;}' +
  '#' + DRAWER_ID + ' .cs-ask-input{flex:1;min-width:0;box-sizing:border-box;border:1px solid ' + BORDER + ';' +
  'border-radius:4px;background:' + INPUT_BG + ';color:inherit;font:inherit;font-size:12px;padding:4px 6px;}' +
  '#' + DRAWER_ID + ' .cs-ask-send{border:1px solid ' + BORDER + ';border-radius:4px;background:transparent;' +
  'color:inherit;cursor:pointer;font:inherit;font-size:12px;padding:3px 10px;}' +
  '#' + DRAWER_ID + ' .cs-ask-note{color:' + MUTED + ';font-size:11px;}' +
  '#' + DRAWER_ID + ' .cs-ask[data-state="answered"]{border-color:#3fa34d55;background:#3fa34d0f;}' +
  '#' + DRAWER_ID + ' .cs-ask[data-state="failed"]{border-color:#d9534f55;background:#d9534f0f;}' +
  '#' + DRAWER_ID + ' .cs-ask[data-state="stale"]{border-color:' + BORDER + ';background:transparent;}' +
  // 已经在送、或已经有答案了，就把输入收起来：留着会让人以为还能再答一次
  '#' + DRAWER_ID + ' .cs-ask[data-state="sending"] .cs-ask-form,' +
  '#' + DRAWER_ID + ' .cs-ask[data-state="sending"] .cs-ask-options,' +
  '#' + DRAWER_ID + ' .cs-ask[data-state="answered"] .cs-ask-form,' +
  '#' + DRAWER_ID + ' .cs-ask[data-state="answered"] .cs-ask-options,' +
  '#' + DRAWER_ID + ' .cs-ask[data-state="stale"] .cs-ask-form,' +
  '#' + DRAWER_ID + ' .cs-ask[data-state="stale"] .cs-ask-options{display:none;}' +
  // 灵感输入：agent 把一句想法拆出来的多步清单。蓝边，跟工具卡的灰边、问句的琥珀边分开。
  // 一整张卡的态度放 data-state，单步的进展放那一步的 data-step-state。
  '#' + DRAWER_ID + ' .cs-plan{align-self:stretch;display:flex;flex-direction:column;gap:6px;' +
  'border:1px solid #4a7fd055;background:#4a7fd00f;}' +
  '#' + DRAWER_ID + ' .cs-plan-goal{font-weight:600;}' +
  '#' + DRAWER_ID + ' .cs-plan-steps{margin:0;padding-left:20px;display:flex;flex-direction:column;gap:3px;}' +
  '#' + DRAWER_ID + ' .cs-plan-step{font-size:12px;}' +
  '#' + DRAWER_ID + ' .cs-plan-step[data-step-state="running"]{color:#e0b400;}' +
  '#' + DRAWER_ID + ' .cs-plan-step[data-step-state="done"]{color:' + MUTED + ';}' +
  '#' + DRAWER_ID + ' .cs-plan-step[data-step-state="failed"]{color:#ff8080;}' +
  '#' + DRAWER_ID + ' .cs-plan-step[data-step-state="skipped"]{color:' + MUTED + ';text-decoration:line-through;}' +
  '#' + DRAWER_ID + ' .cs-plan-tool,' +
  '#' + DRAWER_ID + ' .cs-plan-detail,' +
  '#' + DRAWER_ID + ' .cs-plan-progress,' +
  '#' + DRAWER_ID + ' .cs-plan-note,' +
  '#' + DRAWER_ID + ' .cs-plan-notes{color:' + MUTED + ';font-size:11px;}' +
  '#' + DRAWER_ID + ' .cs-plan-actions{display:flex;gap:6px;}' +
  '#' + DRAWER_ID + ' .cs-plan-ok,' +
  '#' + DRAWER_ID + ' .cs-plan-change{border:1px solid ' + BORDER + ';border-radius:4px;background:transparent;' +
  'color:inherit;cursor:pointer;font:inherit;font-size:12px;padding:3px 8px;}' +
  '#' + DRAWER_ID + ' .cs-plan-ok:hover,' +
  '#' + DRAWER_ID + ' .cs-plan-change:hover{background:' + INPUT_BG + ';}' +
  '#' + DRAWER_ID + ' .cs-plan-change{color:' + MUTED + ';}' +
  '#' + DRAWER_ID + ' .cs-plan-feedback{display:none;flex-direction:column;gap:6px;}' +
  '#' + DRAWER_ID + ' .cs-plan[data-state="editing"] .cs-plan-feedback{display:flex;}' +
  '#' + DRAWER_ID + ' .cs-plan-input{box-sizing:border-box;width:100%;border:1px solid ' + BORDER + ';' +
  'border-radius:4px;background:' + INPUT_BG + ';color:inherit;font:inherit;font-size:12px;' +
  'padding:4px 6px;resize:vertical;}' +
  '#' + DRAWER_ID + ' .cs-plan[data-state="approved"]{border-color:#3fa34d55;background:#3fa34d0f;}' +
  '#' + DRAWER_ID + ' .cs-plan[data-state="rejected"]{border-color:#e0b40055;}' +
  '#' + DRAWER_ID + ' .cs-plan[data-state="failed"]{border-color:#d9534f55;background:#d9534f0f;}' +
  '#' + DRAWER_ID + ' .cs-plan[data-state="stale"]{border-color:' + BORDER + ';background:transparent;}' +
  // 态度送出去之后就把按钮和表单收起来：留着会让人以为还能再表一次态
  '#' + DRAWER_ID + ' .cs-plan:not([data-state="waiting"]):not([data-state="editing"]) .cs-plan-actions,' +
  '#' + DRAWER_ID + ' .cs-plan:not([data-state="waiting"]):not([data-state="editing"]) .cs-plan-feedback{display:none;}' +
  // 页签：抽屉就这么大地方，索性把"对话"和"管理小说"摆成两页，各占满剩下的高度。
  // 当前是哪一页交给 data-active，别用内联样式写死（跟上面 data-state 那套一个约定）。
  '#' + DRAWER_ID + ' .cs-tabs{display:flex;gap:6px;padding:0 12px 8px;}' +
  '#' + DRAWER_ID + ' .cs-tab{border:1px solid ' + BORDER + ';border-radius:4px;background:transparent;' +
  'color:' + MUTED + ';cursor:pointer;font:inherit;font-size:12px;padding:3px 10px;}' +
  '#' + DRAWER_ID + ' .cs-tab[data-active="true"]{color:' + FG + ';background:' + INPUT_BG + ';}' +
  // 书库那一页：一行一排按钮，列表和正文各滚各的 —— 挤进一个滚动区里，翻正文就会把
  // 列表顶出屏幕，回头还得先滚回去才知道自己在读哪一本。
  '#' + DRAWER_ID + ' .cs-novel-bar{display:flex;align-items:center;gap:6px;padding:0 12px 8px;}' +
  '#' + DRAWER_ID + ' .cs-novel-btn{border:1px solid ' + BORDER + ';border-radius:4px;' +
  'background:transparent;color:inherit;cursor:pointer;font:inherit;font-size:12px;padding:3px 8px;}' +
  '#' + DRAWER_ID + ' .cs-novel-btn:hover{background:' + INPUT_BG + ';}' +
  '#' + DRAWER_ID + ' .cs-novel-btn[data-tone="danger"]{color:' + MUTED + ';}' +
  // "删到第二步"是真的会删文件，所以那一下给红边：按钮长什么样就说明这一下有多重。
  '#' + DRAWER_ID + ' .cs-novel-btn[data-armed="true"]{border-color:#d9534f;color:#ff8080;}' +
  // 「目录」是个开关：开着的时候按钮自己也亮着，否则那一栏为什么在那儿就说不清了。
  '#' + DRAWER_ID + ' .cs-novel-btn[data-active="true"]{background:' + INPUT_BG + ';color:' + FG + ';}' +
  '#' + DRAWER_ID + ' .cs-novel-btn:disabled{color:' + MUTED + ';cursor:not-allowed;}' +
  '#' + DRAWER_ID + ' .cs-novel-hint{padding:0 12px 8px;color:' + MUTED + ';font-size:11px;}' +
  '#' + DRAWER_ID + ' .cs-novel-hint[data-tone="error"]{color:#ff8080;}' +
  // 导入表单也压成弹窗（见上面 .cs-popup 那段）：路径是长文本，卡片里给它整行。
  '#' + DRAWER_ID + ' .cs-novel-path{box-sizing:border-box;width:100%;border:1px solid ' + BORDER + ';' +
  'border-radius:4px;background:' + INPUT_BG + ';color:inherit;font:inherit;font-size:12px;padding:4px 6px;}' +
  '#' + DRAWER_ID + ' .cs-novel-list{max-height:38%;overflow-y:auto;padding:0 12px 8px;' +
  'display:flex;flex-direction:column;}' +
  '#' + DRAWER_ID + ' .cs-novel-row{display:flex;flex-direction:column;gap:4px;' +
  'border-bottom:1px solid ' + BORDER + ';padding:6px 0;}' +
  '#' + DRAWER_ID + ' .cs-novel-name{word-break:break-all;}' +
  '#' + DRAWER_ID + ' .cs-novel-row[data-open="true"] .cs-novel-name{font-weight:600;}' +
  '#' + DRAWER_ID + ' .cs-novel-meta{color:' + MUTED + ';font-size:11px;}' +
  '#' + DRAWER_ID + ' .cs-novel-actions{display:flex;gap:6px;}' +
  '#' + DRAWER_ID + ' .cs-novel-empty{color:' + MUTED + ';font-size:12px;padding:6px 0;}' +
  // 正文与左栏（目录）并排：正文那一列自己管翻页行，两边各滚各的。
  '#' + DRAWER_ID + ' .cs-novel-body{flex:1;min-height:0;display:flex;gap:8px;padding:0 12px 8px;}' +
  '#' + DRAWER_ID + ' .cs-novel-main{flex:1;min-width:0;display:flex;flex-direction:column;}' +
  '#' + DRAWER_ID + ' .cs-novel-reader{flex:1;min-height:0;overflow:auto;padding:8px;' +
  'border:1px solid ' + BORDER + ';border-radius:4px;font-size:12px;white-space:pre-wrap;word-break:break-word;}' +
  '#' + DRAWER_ID + ' .cs-novel-pager{display:flex;align-items:center;gap:6px;padding:8px 0;' +
  'color:' + MUTED + ';font-size:11px;}' +
  '#' + DRAWER_ID + ' .cs-novel-pager .cs-novel-pos{margin-left:auto;white-space:nowrap;}' +
  // 左栏自己按比例占，但卡在上限里：抽屉是能被拖宽的（见 installResizeGrip），
  // 目录跟着一起长没什么用 —— 它是导航，行多长都只是眼睛扫一下；正文才需要地方。
  '#' + DRAWER_ID + ' .cs-novel-side{display:none;flex:0 0 auto;flex-direction:column;gap:6px;' +
  'width:38%;max-width:220px;min-width:110px;}' +
  '#' + DRAWER_ID + ' .cs-novel-side[data-open="1"]{display:flex;}' +
  '#' + DRAWER_ID + ' .cs-novel-side-head{display:flex;align-items:center;gap:6px;color:' + MUTED + ';font-size:11px;}' +
  '#' + DRAWER_ID + ' .cs-novel-side-title{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}' +
  '#' + DRAWER_ID + ' .cs-novel-search{display:flex;gap:6px;}' +
  '#' + DRAWER_ID + ' .cs-novel-search input{flex:1;min-width:0;box-sizing:border-box;border:1px solid ' + BORDER + ';' +
  'border-radius:4px;background:' + INPUT_BG + ';color:inherit;font:inherit;font-size:11px;padding:3px 6px;}' +
  '#' + DRAWER_ID + ' .cs-novel-side-list{flex:1;min-height:0;overflow-y:auto;border:1px solid ' + BORDER + ';' +
  'border-radius:4px;padding:4px;display:flex;flex-direction:column;}' +
  // 每一章 / 每一处命中都是一个按钮：整行都能点，不用去瞄那一个"跳"字。
  // flex:0 0 auto 是**必须的**，不是配平的随手一笔：这一栏是 flex 列（见 cs-novel-side-list），
  // 而按钮上那条 overflow:hidden（为了省略号）会让它的 automatic minimum size 被算成 0 ——
  // 于是几百章一起被压进一屏，每行只剩 padding 那几像素，字全被垂直裁掉。一本 272 章的书
  // 就是这么变成一片"看不见的目录"的：栏里明明排着 272 行，屏幕上只有一片虚影。
  // 写死不许收缩，装不下交给那一栏自己滚（overflow-y:auto 就在上一行）。
  '#' + DRAWER_ID + ' .cs-novel-side-row{flex:0 0 auto;display:block;width:100%;text-align:left;border:none;' +
  'background:transparent;color:inherit;cursor:pointer;font:inherit;font-size:11px;padding:3px 4px;' +
  'border-radius:3px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}' +
  '#' + DRAWER_ID + ' .cs-novel-side-row:hover{background:' + INPUT_BG + ';}' +
  '#' + DRAWER_ID + ' .cs-novel-side-row[data-current="true"]{background:' + INPUT_BG + ';font-weight:600;}' +
  '#' + DRAWER_ID + ' .cs-novel-side-meta{display:block;color:' + MUTED + ';font-weight:400;}' +
  // 空态那几行（"打开一篇，这里就是它的目录。"这类）跟章节行同一个容器，一样不许被压。
  '#' + DRAWER_ID + ' .cs-novel-side-list .cs-novel-empty{flex:0 0 auto;font-size:11px;}' +
  // 项目管理那一页：左边是项目（一剧一目录），右边是这部戏的落点 —— 按"围绕剧本"分格
  // （剧本 / 对白配音 / 资产索引台账 / 流程 / 交付 / 素材归档 / 世界观 / 角色服装道具 /
  // 场景表情姿态 / 分镜镜头 / 一致性音频），格子里点开就是文件，底下是读它的地方。
  // 格子一律是**框**：空的那一格也画出来。少显示一格，人就以为这部戏不需要那份资料。
  '#' + DRAWER_ID + ' .cs-proj-bar{display:flex;align-items:center;gap:6px;padding:0 12px 8px;}' +
  '#' + DRAWER_ID + ' .cs-proj-btn{border:1px solid ' + BORDER + ';border-radius:4px;' +
  'background:transparent;color:inherit;cursor:pointer;font:inherit;font-size:12px;padding:3px 8px;}' +
  '#' + DRAWER_ID + ' .cs-proj-btn:hover{background:' + INPUT_BG + ';}' +
  '#' + DRAWER_ID + ' .cs-proj-btn:disabled{color:' + MUTED + ';cursor:not-allowed;}' +
  // 提示行平时是空的（它只说"刚才那件事怎么样了"）：空着还占一行，页顶就永远吊着一条没字的横缝。
  '#' + DRAWER_ID + ' .cs-proj-hint{padding:0 12px 8px;color:' + MUTED + ';font-size:11px;}' +
  '#' + DRAWER_ID + ' .cs-proj-hint:empty{display:none;}' +
  '#' + DRAWER_ID + ' .cs-proj-hint[data-tone="error"]{color:#ff8080;}' +
  '#' + DRAWER_ID + ' .cs-proj-input,#' + DRAWER_ID + ' .cs-proj-select{box-sizing:border-box;width:100%;' +
  'border:1px solid ' + BORDER + ';border-radius:4px;background:' + INPUT_BG + ';color:inherit;' +
  'font:inherit;font-size:12px;padding:4px 6px;}' +
  // 抽屉里"压一层"的表单共用这一套（建项目、导入原文都用它）：absolute 落在 fixed 的抽屉里，
  // inset:0 铺一层暗底，开与关都不动底下的布局 —— 表单不再是页里的一行，不再把下面的格子与
  // 正文挤下去（"正开着表单"这件事不该漏到整页布局上）。开关只有 togglePopup 一个作者。
  '#' + DRAWER_ID + ' .cs-popup{position:absolute;inset:0;z-index:5;display:none;' +
  'align-items:center;justify-content:center;box-sizing:border-box;padding:12px;' +
  'background:rgba(0,0,0,0.45);}' +
  '#' + DRAWER_ID + ' .cs-popup[data-open="1"]{display:flex;}' +
  '#' + DRAWER_ID + ' .cs-popup-card{display:flex;flex-direction:column;gap:8px;width:100%;' +
  'max-width:320px;max-height:100%;overflow-y:auto;box-sizing:border-box;padding:10px;' +
  'border:1px solid ' + BORDER + ';border-radius:6px;background:' + SURFACE + ';' +
  'box-shadow:0 8px 24px rgba(0,0,0,0.45);}' +
  // 这一下会替换掉目录里同名那本时（见 showOverwrite）：卡片自己也变个脸色。跟「删到第二步」
  // 那颗红边按钮是同一个道理 —— 长什么样就说明这一下有多重。
  '#' + DRAWER_ID + ' .cs-popup-card[data-state="confirm"]{border-color:#d9534f;}' +
  '#' + DRAWER_ID + ' .cs-popup-title{color:' + FG + ';font-size:12px;font-weight:600;}' +
  // 字段一列排下来：剧名、集数、原著、补齐落点、建挤在同一行里时，这条窄缝下谁都读不清
  // 自己填的是哪一格。
  '#' + DRAWER_ID + ' .cs-popup-body{display:flex;flex-direction:column;gap:8px;}' +
  '#' + DRAWER_ID + ' .cs-popup-field{display:flex;flex-direction:column;gap:3px;}' +
  '#' + DRAWER_ID + ' .cs-popup-label{color:' + MUTED + ';font-size:11px;}' +
  '#' + DRAWER_ID + ' .cs-popup-check{display:flex;align-items:center;gap:4px;color:' + MUTED + ';font-size:11px;}' +
  // 弹窗里那份"刚才那件事怎么样了"：页顶那条被暗底盖住了，没成的话得在卡片里看得见。
  '#' + DRAWER_ID + ' .cs-popup-hint{color:' + MUTED + ';font-size:11px;line-height:1.4;}' +
  '#' + DRAWER_ID + ' .cs-popup-hint:empty{display:none;}' +
  '#' + DRAWER_ID + ' .cs-popup-hint[data-tone="error"]{color:#ff8080;}' +
  // 换成窄抽屉时按钮折行也别叠在一起（覆盖导入是第三个）。
  '#' + DRAWER_ID + ' .cs-popup-actions{display:flex;flex-wrap:wrap;justify-content:flex-end;gap:6px;}' +
  // 主按钮只有一个：弹窗里"建"/「导入」才是往下走的那步，「取消」是退路。
  '#' + DRAWER_ID + ' .cs-popup-actions [data-primary="1"]{background:' + INPUT_BG + ';font-weight:600;}' +
  '#' + DRAWER_ID + ' .cs-proj-body{flex:1;min-height:0;display:flex;gap:8px;padding:0 12px 8px;}' +
  // 左栏按比例占但卡在上限里：它是导航，一行就那么点信息；地方要留给右边的格子与正文。
  '#' + DRAWER_ID + ' .cs-proj-list{flex:0 0 auto;width:34%;max-width:200px;min-width:110px;' +
  'overflow-y:auto;display:flex;flex-direction:column;}' +
  '#' + DRAWER_ID + ' .cs-proj-row{flex:0 0 auto;display:block;width:100%;text-align:left;border:none;' +
  'border-bottom:1px solid ' + BORDER + ';background:transparent;color:inherit;cursor:pointer;' +
  'font:inherit;font-size:12px;padding:5px 6px;line-height:1.4;}' +
  '#' + DRAWER_ID + ' .cs-proj-row:hover{background:' + INPUT_BG + ';}' +
  // 在读的那一部：底色的同时左沿立一条竖线（不占布局，靠 inset 阴影画）——
  // 只用底色的话，跟 hover 长得一模一样，鼠标一移开就不知道自己在哪一部上。
  '#' + DRAWER_ID + ' .cs-proj-row[data-open="true"]{background:' + INPUT_BG + ';font-weight:600;' +
  'box-shadow:inset 2px 0 0 ' + MUTED + ';}' +
  // 名字可能很长（剧名后面常常跟着版本、集数），允许折行：省略号会把它变成一个认不出的前缀。
  '#' + DRAWER_ID + ' .cs-proj-name{word-break:break-all;}' +
  '#' + DRAWER_ID + ' .cs-proj-meta{display:block;color:' + MUTED + ';font-size:11px;font-weight:400;}' +
  '#' + DRAWER_ID + ' .cs-proj-main{flex:1;min-width:0;display:flex;flex-direction:column;gap:6px;}' +
  '#' + DRAWER_ID + ' .cs-proj-head{color:' + MUTED + ';font-size:11px;line-height:1.5;' +
  'display:flex;flex-direction:column;gap:4px;}' +
  // 剧名一行，路径一行：路径常常比面板还长，跟剧名挤一行会把剧名一起拽断（两行各断各的）。
  '#' + DRAWER_ID + ' .cs-proj-title{color:' + FG + ';font-size:13px;font-weight:600;' +
  'word-break:break-all;}' +
  '#' + DRAWER_ID + ' .cs-proj-path{color:' + MUTED + ';font-size:10px;line-height:1.3;' +
  'word-break:break-all;}' +
  // 阶段：一步一枚小签。做过的填底色 + 勾、没做的虚线空框 —— 勾/空不靠颜色也分得出来。
  '#' + DRAWER_ID + ' .cs-proj-stages{display:flex;flex-wrap:wrap;align-items:center;gap:4px;}' +
  '#' + DRAWER_ID + ' .cs-proj-stages-label{color:' + MUTED + ';}' +
  '#' + DRAWER_ID + ' .cs-proj-stage{border:1px dashed ' + BORDER + ';border-radius:3px;' +
  'padding:0 4px;white-space:nowrap;color:' + MUTED + ';}' +
  '#' + DRAWER_ID + ' .cs-proj-stage[data-done="1"]{border-style:solid;border-color:' + MUTED + ';' +
  'background:' + INPUT_BG + ';color:' + FG + ';}' +
  '#' + DRAWER_ID + ' .cs-proj-stage[data-done="1"]::before{content:"✓ ";}' +
  '#' + DRAWER_ID + ' .cs-proj-stage[data-done="0"]::before{content:"· ";}' +
  // 详情里每一行备注都从 projectNote 出来，四种语气四种颜色 —— 以前四种事都穿同一件红衣服：
  // plain 事实（原著登记）、next 下一步往哪走（那是路标，不是报警）、
  // action 要人去补的（缺落点）、bug 面板自己的毛病（格子跟规范对不上）。
  '#' + DRAWER_ID + ' .cs-proj-note{word-break:break-word;}' +
  '#' + DRAWER_ID + ' .cs-proj-note[data-tone="next"]{color:' + FG + ';}' +
  '#' + DRAWER_ID + ' .cs-proj-note[data-tone="action"]{color:#ff8080;}' +
  '#' + DRAWER_ID + ' .cs-proj-note[data-tone="bug"]{color:#e0b400;}' +
  // 「流水线」那一页（见 buildPipelineView）：一段一张卡 —— 阶段号、名字、谁做、产出落哪儿、
  // 要不要引擎侧渲染，以及这一段现在的归宿（跑着 / 跑过 / 跳过 / 栽了 / 还没跑）。
  // 归宿不只靠颜色表意：状态那一枚签本身就写着字（见 pipeStatusChip），色盲与黑白打印都分得出来。
  '#' + DRAWER_ID + ' .cs-pipe-list{flex:1;min-height:0;overflow-y:auto;display:flex;' +
  'flex-direction:column;gap:6px;padding:0 12px 8px;}' +
  '#' + DRAWER_ID + ' .cs-pipe-stage{border:1px dashed ' + BORDER + ';border-radius:4px;' +
  'padding:6px 8px;display:flex;flex-direction:column;gap:3px;}' +
  '#' + DRAWER_ID + ' .cs-pipe-stage[data-status="running"]{border-style:solid;' +
  'border-color:' + MUTED + ';background:' + INPUT_BG + ';}' +
  '#' + DRAWER_ID + ' .cs-pipe-stage[data-status="done"],' +
  '#' + DRAWER_ID + ' .cs-pipe-stage[data-status="skipped"]{border-style:solid;}' +
  '#' + DRAWER_ID + ' .cs-pipe-stage[data-status="failed"]{border-style:solid;border-color:#ff8080;}' +
  '#' + DRAWER_ID + ' .cs-pipe-head{display:flex;align-items:baseline;gap:6px;flex-wrap:wrap;}' +
  '#' + DRAWER_ID + ' .cs-pipe-code{font-family:var(--cs-mono);color:' + MUTED + ';font-size:11px;}' +
  '#' + DRAWER_ID + ' .cs-pipe-name{color:' + FG + ';font-size:12px;font-weight:600;}' +
  '#' + DRAWER_ID + ' .cs-pipe-meta{color:' + MUTED + ';font-size:11px;line-height:1.45;' +
  'word-break:break-all;}' +
  '#' + DRAWER_ID + ' .cs-pipe-note{color:' + MUTED + ';font-size:11px;line-height:1.45;' +
  'word-break:break-word;}' +
  '#' + DRAWER_ID + ' .cs-pipe-note[data-tone="warn"]{color:#e0b400;}' +
  '#' + DRAWER_ID + ' .cs-pipe-note[data-tone="error"]{color:#ff8080;}' +
  '#' + DRAWER_ID + ' .cs-proj-meter-note{color:' + MUTED + ';}' +
  '#' + DRAWER_ID + ' .cs-proj-shelves{flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;gap:4px;}' +
  '#' + DRAWER_ID + ' .cs-proj-shelf{flex:0 0 auto;border:1px solid ' + BORDER + ';border-radius:4px;' +
  'overflow:hidden;}' +
  '#' + DRAWER_ID + ' .cs-proj-shelf-head{display:flex;align-items:center;gap:6px;width:100%;' +
  'text-align:left;border:none;background:transparent;color:inherit;cursor:pointer;font:inherit;' +
  'font-size:12px;padding:4px 6px;}' +
  '#' + DRAWER_ID + ' .cs-proj-shelf-head:hover{background:' + INPUT_BG + ';}' +
  // 一格有没有东西用一个 6px 的点说，不用 ✅/☐：勾选框摆在最左边，整列看起来像一排待勾的多选框，
  // 而这九行是"去哪一格里找资料"，不是一件件要人去勾的事。
  '#' + DRAWER_ID + ' .cs-proj-shelf-mark{flex:0 0 auto;width:6px;height:6px;border-radius:50%;' +
  'background:' + MUTED + ';}' +
  // 空格子：标题淡 + 虚线框 + 空心点。它不是错误，是"这一格还空着"这句话本身。
  '#' + DRAWER_ID + ' .cs-proj-shelf[data-empty="1"]{border-style:dashed;}' +
  '#' + DRAWER_ID + ' .cs-proj-shelf[data-empty="1"] .cs-proj-shelf-head{color:' + MUTED + ';}' +
  '#' + DRAWER_ID + ' .cs-proj-shelf[data-empty="1"] .cs-proj-shelf-mark{background:transparent;' +
  'border:1px solid ' + BORDER + ';}' +
  // 展开的那一格：边框提亮 + 左沿一条竖线，跟正文里高亮的那一行、左栏在读的那一部一个语言。
  '#' + DRAWER_ID + ' .cs-proj-shelf[data-open="1"]{border-color:' + MUTED + ';' +
  'box-shadow:inset 2px 0 0 ' + MUTED + ';}' +
  '#' + DRAWER_ID + ' .cs-proj-shelf-count{margin-left:auto;color:' + MUTED + ';font-size:10px;' +
  'white-space:nowrap;border:1px solid ' + BORDER + ';border-radius:8px;padding:0 5px;}' +
  '#' + DRAWER_ID + ' .cs-proj-shelf[data-empty="1"] .cs-proj-shelf-count{border-color:transparent;}' +
  '#' + DRAWER_ID + ' .cs-proj-files{display:none;flex-direction:column;border-top:1px solid ' + BORDER + ';' +
  'padding:2px 4px 4px;}' +
  // 一格里的粒度小标题（全剧级 / 分集级，见 projectGroupLabel）：它是**分节线**，不是又一行文件，
  // 所以左沿立一条竖线、字号再小一号 —— 跟文件行（可点、有 hover）一眼分得开。
  '#' + DRAWER_ID + ' .cs-proj-group{display:flex;align-items:baseline;gap:6px;margin:3px 0 1px;' +
  'padding:0 4px 0 6px;border-left:2px solid ' + BORDER + ';color:' + MUTED + ';font-size:10px;' +
  'white-space:nowrap;}' +
  '#' + DRAWER_ID + ' .cs-proj-group-count{margin-left:auto;}' +
  '#' + DRAWER_ID + ' .cs-proj-shelf[data-open="1"] .cs-proj-files{display:flex;}' +
  '#' + DRAWER_ID + ' .cs-proj-file{flex:0 0 auto;display:flex;align-items:baseline;gap:6px;width:100%;' +
  'text-align:left;border:none;border-radius:3px;background:transparent;color:inherit;cursor:pointer;' +
  'font:inherit;font-size:11px;padding:3px 4px;}' +
  '#' + DRAWER_ID + ' .cs-proj-file:hover{background:' + INPUT_BG + ';}' +
  '#' + DRAWER_ID + ' .cs-proj-file[data-open="true"]{background:' + INPUT_BG + ';font-weight:600;}' +
  // 读不了的那种（图片、音频）照样列出来，但灰着、点不动：藏起来更让人摸不着头脑。
  '#' + DRAWER_ID + ' .cs-proj-file[data-read="0"]{color:' + MUTED + ';cursor:not-allowed;}' +
  '#' + DRAWER_ID + ' .cs-proj-file-size{margin-left:auto;color:' + MUTED + ';white-space:nowrap;font-weight:400;}' +
  '#' + DRAWER_ID + ' .cs-proj-reader{flex:0 0 auto;height:26%;min-height:70px;overflow:auto;padding:8px;' +
  'border:1px solid ' + BORDER + ';border-radius:4px;font-size:12px;white-space:pre-wrap;word-break:break-word;}' +
  // 页码那一行允许折行：文件名长起来时（快照名、带集数的稿名）不折就是横向撑破面板。
  '#' + DRAWER_ID + ' .cs-proj-pager{display:flex;align-items:center;gap:6px;flex-wrap:wrap;' +
  'color:' + MUTED + ';font-size:11px;}' +
  '#' + DRAWER_ID + ' .cs-proj-pager .cs-proj-pos{margin-left:auto;word-break:break-all;}' +
  // 正文是一整块长的，读着读着最容易忘"这是哪一份"：文件名从位置信息里拎出来给前景色。
  '#' + DRAWER_ID + ' .cs-proj-pos-rel{color:' + FG + ';font-weight:600;}' +
  '#' + DRAWER_ID + ' .cs-proj-empty{flex:0 0 auto;color:' + MUTED + ';font-size:11px;padding:4px;}' +
  // 引用卡：贴在输入框上方那一栏（待发的），以及压在用户气泡里的那几张（已经发出去的）。
  '#' + DRAWER_ID + ' .cs-quote-bar{display:none;flex-direction:column;gap:4px;}' +
  '#' + DRAWER_ID + ' .cs-quote{border:1px solid ' + BORDER + ';border-radius:4px;padding:4px 6px;' +
  'background:' + INPUT_BG + ';}' +
  '#' + DRAWER_ID + ' .cs-quote-head{display:flex;align-items:center;gap:6px;}' +
  '#' + DRAWER_ID + ' .cs-quote-title{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;' +
  'white-space:nowrap;color:' + MUTED + ';font-size:11px;}' +
  '#' + DRAWER_ID + ' .cs-quote-drop{border:none;background:transparent;color:' + MUTED + ';' +
  'cursor:pointer;font:inherit;font-size:12px;padding:0 4px;}' +
  '#' + DRAWER_ID + ' .cs-quote-drop:hover{color:#ff8080;}' +
  '#' + DRAWER_ID + ' .cs-quote-body{font-size:11px;white-space:pre-wrap;word-break:break-word;' +
  'max-height:120px;overflow:auto;margin-top:2px;}' +
  '#' + DRAWER_ID + ' .cs-quote-more{border:1px solid ' + BORDER + ';border-radius:4px;' +
  'background:transparent;color:' + MUTED + ';cursor:pointer;font:inherit;font-size:11px;' +
  'padding:1px 6px;margin-top:2px;}' +
  // 气泡里那张：气泡本身已经是底色，卡再叠一层底色就成了两块同色砖，只留线。
  '#' + DRAWER_ID + ' .cs-user .cs-quote{background:transparent;}' +
  '#' + DRAWER_ID + ' .cs-user .cs-quote + .cs-user-words{margin-top:4px;}' +
  '#' + DRAWER_ID + ' .cs-user-words{white-space:pre-wrap;word-break:break-word;}' +
  // 跑 skill 的那张卡与它画出来的图。图按抽屉宽度缩，不撑破面板（图是引擎给的 url，
  // 尺寸不可预知）；加载不出来时换成一行字（见 paintSkillImage），不留一个空框。
  '#' + DRAWER_ID + ' .cs-skill-head{display:flex;align-items:center;gap:6px;}' +
  '#' + DRAWER_ID + ' .cs-skill-title{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;' +
  'white-space:nowrap;}' +
  '#' + DRAWER_ID + ' .cs-skill-state{color:' + MUTED + ';font-size:11px;white-space:nowrap;}' +
  '#' + DRAWER_ID + ' [data-kind="skill"][data-state="error"] .cs-skill-state,' +
  // 渲染那张卡复用同一批 class（同一件事的两层，见「一键跑渲染目标」那一节），所以失败配色也得
  // 一起管到它：不然渲染失败时那一行还是灰的，一眼看不出它没跑成。
  '#' + DRAWER_ID + ' [data-kind="render"][data-state="error"] .cs-skill-state{color:#ff8080;}' +
  '#' + DRAWER_ID + ' .cs-skill-body{display:flex;flex-direction:column;gap:6px;margin-top:6px;}' +
  '#' + DRAWER_ID + ' .cs-skill-image{max-width:100%;border:1px solid ' + BORDER + ';' +
  'border-radius:4px;display:block;}' +
  '#' + DRAWER_ID + ' .cs-skill-image-note{color:#ff8080;font-size:11px;word-break:break-all;}' +
  '#' + DRAWER_ID + ' .cs-skill-caption{color:' + MUTED + ';font-size:11px;word-break:break-all;}' +
  // 自己说过的那一行：动作条平时不露面（hover 或者键盘焦点进去才显）—— 出处见 userActions，
  // 与 ComfyUI 官方前端 agent 面板的 UserMessage.vue 同一个做法（opacity 从 0 到 1）。
  '#' + DRAWER_ID + ' .cs-user-actions{display:flex;gap:6px;margin-top:4px;opacity:0;' +
  'transition:opacity .12s;}' +
  '#' + DRAWER_ID + ' .cs-user:hover .cs-user-actions,' +
  '#' + DRAWER_ID + ' .cs-user:focus-within .cs-user-actions{opacity:1;}' +
  '#' + DRAWER_ID + ' .cs-user-action{border:1px solid ' + BORDER + ';border-radius:4px;' +
  'background:transparent;color:' + MUTED + ';cursor:pointer;font:inherit;font-size:11px;' +
  'padding:1px 6px;}' +
  '#' + DRAWER_ID + ' .cs-user-action:hover{color:' + FG + ';}' +
  // 找字那一行（见 buildFindRow）：一行字、几个按钮，命中标记只加在行上（不插 mark）。
  '#' + DRAWER_ID + ' .cs-find{display:flex;align-items:center;gap:6px;padding:0 12px 6px;}' +
  '#' + DRAWER_ID + ' .cs-find input{flex:1;min-width:0;border:1px solid ' + BORDER + ';' +
  'border-radius:4px;background:' + INPUT_BG + ';color:' + FG + ';font:inherit;font-size:12px;' +
  'padding:3px 6px;}' +
  '#' + DRAWER_ID + ' .cs-find-count{color:' + MUTED + ';font-size:11px;white-space:nowrap;' +
  'min-width:52px;}' +
  '#' + DRAWER_ID + ' .cs-find-count[data-tone="error"]{color:#ff8080;}' +
  '#' + DRAWER_ID + ' .cs-find-btn{border:1px solid ' + BORDER + ';border-radius:4px;' +
  'background:transparent;color:' + MUTED + ';cursor:pointer;font:inherit;font-size:11px;' +
  'padding:1px 6px;white-space:nowrap;}' +
  '#' + DRAWER_ID + ' .cs-find-btn:hover{color:' + FG + ';}' +
  '#' + DRAWER_ID + ' .cs-row[data-hit]{outline:1px solid ' + BORDER + ';outline-offset:2px;}' +
  '#' + DRAWER_ID + ' .cs-row[data-hit="current"]{outline:2px solid ' + FG + ';outline-offset:2px;}' +
  // 小说那页：批量那一栏、行里的勾选框、章节占比条。
  '#' + DRAWER_ID + ' .cs-novel-batch{display:flex;align-items:center;gap:6px;flex-wrap:wrap;' +
  'padding:0 12px 6px;}' +
  '#' + DRAWER_ID + ' .cs-novel-batch-count{flex:1;min-width:0;color:' + MUTED + ';font-size:11px;' +
  'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}' +
  '#' + DRAWER_ID + ' .cs-novel-pick{flex:0 0 auto;margin:0;}' +
  '#' + DRAWER_ID + ' .cs-novel-row[data-picked="true"]{background:' + INPUT_BG + ';}' +
  '#' + DRAWER_ID + ' .cs-novel-side-bar{display:block;height:2px;margin-top:3px;' +
  'background:' + BORDER + ';border-radius:2px;overflow:hidden;}' +
  '#' + DRAWER_ID + ' .cs-novel-side-bar-fill{display:block;height:100%;background:' + MUTED + ';}' +
  // 项目那页：阶段进度条（数与条画的是同一对数，见 projectBar）。
  // 类名是 cs-proj-meter，不是 cs-proj-bar —— 上面按钮那一排已经叫 cs-proj-bar 了，
  // 同名的话这条 height:4px + overflow:hidden 会把按钮排压成一条缝（曾经就是）。
  '#' + DRAWER_ID + ' .cs-proj-meter{height:4px;margin:4px 0;background:' + BORDER + ';' +
  'border-radius:2px;overflow:hidden;}' +
  '#' + DRAWER_ID + ' .cs-proj-meter-fill{height:100%;background:' + MUTED + ';}' +
  '#' + DRAWER_ID + ' .cs-proj-row .cs-proj-meter{margin:2px 0 0;}' +
  '#' + DRAWER_ID + ' .cs-proj-novel{display:flex;align-items:center;gap:6px;flex-wrap:wrap;}' +
  // 项目那页的筛项目那一行，与「管理小说」那页的搜索框同一个样子（三页的检索长得一样，
  // 人才不用每换一页重新认一遍）。
  '#' + DRAWER_ID + ' .cs-proj-find{display:flex;align-items:center;gap:6px;padding:0 12px 6px;}' +
  '#' + DRAWER_ID + ' .cs-proj-find input{flex:1;min-width:0;border:1px solid ' + BORDER + ';' +
  'border-radius:4px;background:' + INPUT_BG + ';color:' + FG + ';font:inherit;font-size:12px;' +
  'padding:3px 6px;}' +
  '#' + DRAWER_ID + ' .cs-proj-find-count{color:' + MUTED + ';font-size:11px;white-space:nowrap;' +
  'min-width:42px;}' +
  // 项目页的"页内找字"那一行套用 .cs-find 那套长相（三页一致），但它落在正文区里，
  // 左右不再各让 12px —— 父容器已经让过了，再让一次正文就比上下的块窄一截。
  // 找字 + 正文 + 页码是**一块**（说的是"这一页在读什么"），跟上面的格子分开：加一条上分界线。
  '#' + DRAWER_ID + ' .cs-proj-file-find{padding:6px 0 6px;border-top:1px solid ' + BORDER + ';}' +
  // 跨项目总览那一行：只报数（各个数都出自宿主 projects/list 的行），不画图。
  // 一个数一枚小签：连成一句话时它在这条窄缝里要折三行，还读不出哪几个数是哪件事。
  '#' + DRAWER_ID + ' .cs-proj-overview{padding:0 12px 8px;display:flex;flex-wrap:wrap;' +
  'align-items:center;gap:4px;font-size:11px;}' +
  '#' + DRAWER_ID + ' .cs-proj-chip{border:1px solid ' + BORDER + ';border-radius:10px;' +
  'padding:0 6px;white-space:nowrap;color:' + FG + ';}' +
  // 0 部照样说出来，但淡下去：它是"没有"，不是"有问题"。
  '#' + DRAWER_ID + ' .cs-proj-chip[data-tone="zero"]{color:' + MUTED + ';border-color:transparent;' +
  'background:' + INPUT_BG + ';}' +
  '#' + DRAWER_ID + ' .cs-proj-chip[data-tone="action"]{color:#ff8080;border-color:#7a3a3a;}' +
  '#' + DRAWER_ID + ' .cs-proj-chip[data-tone="warn"]{color:#e0b400;border-color:#6b5b00;}' +
  // 正文页内找字：命中处包一层 <mark>（正文是整块重画的，不是增量卡，所以敢动它的 DOM ——
  // 对话那一页的 [data-hit] 只标行不插字，原因在那儿写着）。
  '#' + DRAWER_ID + ' .cs-proj-hit{background:#6b5b00;color:inherit;border-radius:2px;}' +
  '#' + DRAWER_ID + ' .cs-proj-hit[data-cur="true"]{background:#b58900;color:#1a1a1a;}' +
  // 流水线那页：一段一张卡，纵着排（阶段是有先后的，横排读不出"跑到哪一段了"）。
  // 卡左沿那道色条就是归宿：跑着黄 / 跑过绿 / 栽了红。但签上也写着字（见 pipeChip）——
  // 颜色只是让人一眼扫过去，不是唯一的凭据。
  '#' + DRAWER_ID + ' .cs-pipe-list{flex:1;min-height:0;overflow:auto;display:flex;' +
  'flex-direction:column;gap:6px;padding:0 12px 12px;}' +
  '#' + DRAWER_ID + ' .cs-pipe-stage{border:1px solid ' + BORDER + ';border-left-width:3px;' +
  'border-radius:var(--cs-radius);padding:6px 8px;display:flex;flex-direction:column;gap:4px;}' +
  '#' + DRAWER_ID + ' .cs-pipe-stage[data-status="running"]{border-left-color:#e0b400;}' +
  '#' + DRAWER_ID + ' .cs-pipe-stage[data-status="done"]{border-left-color:#3fa34d;}' +
  '#' + DRAWER_ID + ' .cs-pipe-stage[data-status="failed"]{border-left-color:#d9534f;}' +
  '#' + DRAWER_ID + ' .cs-pipe-head{display:flex;align-items:center;gap:6px;}' +
  '#' + DRAWER_ID + ' .cs-pipe-code{font-family:var(--cs-mono);font-size:12px;color:' + MUTED + ';}' +
  '#' + DRAWER_ID + ' .cs-pipe-name{flex:1;min-width:0;font-size:12px;}' +
  '#' + DRAWER_ID + ' .cs-pipe-meta{color:' + MUTED + ';font-size:11px;word-break:break-word;}' +
  '#' + DRAWER_ID + ' .cs-pipe-note{color:' + MUTED + ';font-size:11px;line-height:1.4;' +
  'word-break:break-word;}' +
  '#' + DRAWER_ID + ' .cs-pipe-note[data-tone="warn"]{color:#e0b400;}' +
  '#' + DRAWER_ID + ' .cs-pipe-note[data-tone="error"]{color:#ff8080;}';

function ensureStyle() {
  if (document.getElementById(STYLE_ID)) return;
  var style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = CHAT_CSS;
  (document.head || document.body).appendChild(style);
}

function message(err) {
  if (!err) return '未知错误';
  if (typeof err === 'string') return err;
  return err.message || String(err);
}

function truncate(text, max) {
  return text.length > max ? text.slice(0, max) + '…（已截断）' : text;
}

// 三页的提示行只有这一个作者：文案由各页自己写（只有它知道刚才那件事的来龙去脉），
// 但"什么语气用什么颜色"在这一处定 —— 不然翻页看到的反馈是三种样子（小说页给 dataset，
// 对话状态行给内联色），改一次要改三处，还改不齐。
function hintLine(id, text, tone) {
  var line = document.getElementById(id);
  if (!line) return null;
  line.textContent = text;
  line.dataset.tone = tone === 'error' ? 'error' : 'info';
  return line;
}

// ---- 弹窗（在抽屉里压一层）-----------------------------------------------
//
// 建项目、导入原文这两张表单都压成弹窗，而不是页里的一行：它们一开就横着推一排控件，把下面
// 的格子与正文全挤下去 —— "正开着表单"这件事漏到了整页布局上。样子在样式表里一条 .cs-popup
// 管全部，这里管的是**脾气**：怎么开关、光标落在哪、怎么退出去。两页共用这一份，不然两个
// 弹窗迟早各长一样（一个能按 Esc 退，另一个不能）。

// 开关只有这一处作者：工具栏那颗按钮、暗底、Esc、以及各页干完活之后的收尾都走它。
//
// 打开时顺手把上一次留下的那句话清掉（多半是"先给这部戏起个名字"），光标放进第一格 ——
// 弹窗一开，人第一件事就是填那一格，别让他再点一下。hintId 是卡片里那份提示行：它也是
// 页顶那条的镜像（见 projectHint / importHint），这里只管把它擦干净。
function togglePopup(layerId, hintId, focusId, open) {
  var layer = document.getElementById(layerId);
  if (!layer) return false;
  var next = open === undefined ? layer.dataset.open !== '1' : !!open;
  layer.dataset.open = next ? '1' : '0';
  if (!next) return false;
  hintLine(hintId, '', 'info');
  var first = focusId ? document.getElementById(focusId) : null;
  if (first) first.focus();
  return true;
}

// 搭一层弹窗：暗底、卡片、卡片里的排版顺序都在这儿定死（标题 → body → 提示 → 按钮），
// 调用方只管往 body 与 actions 里塞自己的控件。顺序定死是有理由的：提示行得在按钮上面、
// 在字段下面，各页自己拼迟早会拼出三种样子。
function buildPopup(layerId, hintId, title) {
  var layer = document.createElement('div');
  layer.id = layerId;
  layer.className = 'cs-popup';
  layer.dataset.open = '0';

  var card = document.createElement('div');
  card.className = 'cs-popup-card';
  card.setAttribute('role', 'dialog');
  card.setAttribute('aria-label', title);
  var head = document.createElement('div');
  head.className = 'cs-popup-title';
  head.textContent = title;
  card.appendChild(head);

  var body = document.createElement('div');
  body.className = 'cs-popup-body';
  card.appendChild(body);

  var hint = document.createElement('div');
  hint.id = hintId;
  hint.className = 'cs-popup-hint';
  hint.textContent = '';
  card.appendChild(hint);

  var actions = document.createElement('div');
  actions.className = 'cs-popup-actions';
  card.appendChild(actions);

  // 点暗底、按 Esc 都收得掉：弹窗盖住了页顶那排按钮，想退出去时不该只能去够那颗「取消」。
  // Esc 挂在卡片上，打开时光标就在第一格里，按键从卡片里冒上来。
  layer.addEventListener('click', function (event) {
    if (event.target === layer) togglePopup(layerId, hintId, null, false);
  });
  card.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      // 别让这一按继续冒到 document：那边还有一层 Esc 处理（见 onShortcut），
      // 两边都动手的话，按一下会把弹窗和"我正在看的那一页"一起收走。
      event.stopPropagation();
      togglePopup(layerId, hintId, null, false);
    }
  });

  layer.appendChild(card);
  return { layer: layer, body: body, actions: actions };
}

// 一个字段一行、标签在上控件在下，而且用一个 label 包着：点标签上的字就落进那一格。
// （挤在一行里时，这条窄缝下谁都读不清自己填的是哪一格。）
function popupField(labelText, control) {
  var field = document.createElement('label');
  field.className = 'cs-popup-field';
  var label = document.createElement('span');
  label.className = 'cs-popup-label';
  label.textContent = labelText;
  field.appendChild(label);
  field.appendChild(control);
  return field;
}

// ---- 抽屉 --------------------------------------------------------------

// ---- 宽窄 --------------------------------------------------------------
//
// 抽屉跟托管页面共用一块屏，宽度不该由代码拍死：模型/智能体/会话三行控件、对话正文、原文
// 正文都要挤在同一条竖缝里，而这块屏上最不缺的就是横向空间。所以左沿留一只 6px 的手给
// 人拖，双击在三档之间循环，选过的宽度跟"上次停在哪一段"一样存在浏览器存储里 ——
// 都是"重载之后还想接着用"的那一类，读不到存储就按默认来，不拿默认值冒充用户的选择。
var WIDTH_KEY = 'comfyStudio.width';

//: 三档：够用的窄、读原文的宽、占满整屏。0 表示占满。
var WIDTH_STEPS = [520, 760, 0];
//: 再窄下去三个下拉都看不清自己选了啥，那就不叫能用了。
var MIN_WIDTH = 360;
//: 拖拽的上限：总得给画布留一角。占满那一档不走这条 —— 那是人明说了要它占满。
var MAX_WIDTH_RATIO = 0.72;
var MAX_WIDTH_ABS = 1280;

function viewportWidth() {
  return window.innerWidth || document.documentElement.clientWidth || 1024;
}

function clampWidth(px) {
  var limit = Math.min(MAX_WIDTH_ABS, Math.round(viewportWidth() * MAX_WIDTH_RATIO));
  if (limit < MIN_WIDTH) limit = MIN_WIDTH; // 窗口本身比下限还窄时，以下限为准
  var value = Math.round(px);
  if (!(value > 0)) value = WIDTH_STEPS[0];
  return Math.max(MIN_WIDTH, Math.min(value, limit));
}

// 返回 null = 没记过；0 = 占满那一档。读不到存储也当没记过：这只是个宽度，
// 不值得像"上次停在哪一段"那样在界面上解释一遍。
function readSavedWidth() {
  try {
    var value = window.localStorage.getItem(WIDTH_KEY);
    if (value === 'full') return 0;
    if (value === null) return null;
    var num = parseInt(value, 10);
    return isNaN(num) ? null : num;
  } catch (e) {
    return null;
  }
}

function rememberWidth(px) {
  try {
    window.localStorage.setItem(WIDTH_KEY, px === 0 ? 'full' : String(px));
  } catch (e) {
    // 记不住只会让下次打开回到默认宽，这一屏不受影响，不打扰用户。
  }
}

// 当前宽度（像素，0 = 占满整屏）。同时记进 STATE：状态行与测试都是从这个口看的。
function applyWidth(px, remember) {
  var drawer = document.getElementById(DRAWER_ID);
  var full = px === 0;
  var value = full ? 0 : clampWidth(px);
  STATE.width = value;
  if (drawer) drawer.style.width = full ? '100vw' : value + 'px';
  if (remember) rememberWidth(value);
  return value;
}

function restoreWidth() {
  var saved = readSavedWidth();
  applyWidth(saved === null ? WIDTH_STEPS[0] : saved, false);
}

// 双击那只手：窄 → 宽 → 占满 → 窄。当前是拖出来的杂数时就落到"宽"那一档。
function cycleWidth() {
  var index = 0;
  for (var i = 0; i < WIDTH_STEPS.length; i += 1) {
    if (WIDTH_STEPS[i] === STATE.width) {
      index = i;
      break;
    }
  }
  applyWidth(WIDTH_STEPS[(index + 1) % WIDTH_STEPS.length], true);
}

// 窗口变窄时把宽度收回来：存着的 1280px 落在 900px 的窗口里，会把画布挤没。
// 占满那一档不参与（它本来就跟着视口走）。
function installWidthWatcher() {
  if (STATE.widthWatcher) return;
  STATE.widthWatcher = true;
  window.addEventListener('resize', function () {
    if (STATE.width === 0) return;
    applyWidth(STATE.width, false);
  });
}

function installResizeGrip(drawer) {
  var grip = document.createElement('div');
  grip.id = GRIP_ID;
  grip.className = 'cs-grip';
  grip.title = '拖这里调宽窄；双击在 窄／宽／占满 之间换';
  grip.addEventListener('dblclick', function () {
    cycleWidth();
  });
  grip.addEventListener('pointerdown', function (event) {
    if (event.button !== 0) return;
    var startX = event.clientX;
    var startWidth = drawer.getBoundingClientRect().width;
    grip.dataset.drag = '1';

    // 抽屉贴在右边：指针往左移就是变宽。拖的过程只改宽度不落盘，松手才记 ——
    // 一路拖过去落几十次盘，只是白写浏览器存储。
    var move = function (moveEvent) {
      applyWidth(startWidth + (startX - moveEvent.clientX), false);
    };
    var up = function () {
      grip.dataset.drag = '0';
      document.removeEventListener('pointermove', move);
      document.removeEventListener('pointerup', up);
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
      rememberWidth(STATE.width);
    };

    document.body.style.userSelect = 'none'; // 顺手别把画布上的字选中
    document.body.style.cursor = 'col-resize';
    document.addEventListener('pointermove', move);
    document.addEventListener('pointerup', up);
    if (grip.setPointerCapture) {
      try {
        grip.setPointerCapture(event.pointerId);
      } catch (e) {
        // 拿不到捕获也不碍事：上面两条监听挂在 document 上，照样收得到。
      }
    }
    event.preventDefault();
  });
  drawer.appendChild(grip);
}

function buildDrawer() {
  ensureStyle();
  var drawer = document.createElement('aside');
  drawer.id = DRAWER_ID;
  // 宽度归 applyWidth 管（拖拽/记忆/三档都在它那儿）：内联只留一个默认值，免得脚本刚
  // 建好还没摆之前那一瞬间没有宽度。
  drawer.style.cssText =
    'position:fixed;top:0;right:0;z-index:2000;display:none;flex-direction:column;' +
    'width:' + WIDTH_STEPS[0] + 'px;height:100%;box-sizing:border-box;' +
    'background:' + SURFACE + ';color:' + FG + ';border-left:1px solid ' + BORDER + ';' +
    'font-size:13px;line-height:1.5;';
  // 记着"哪面抽屉是我建的"：快捷键（见 onShortcut）与占满窗口那一层都靠它判断
  // 这一份实例还算不算数 —— 只认 id 的话，宿主刷新网页之后新旧两份会同时上手。
  STATE.drawer = drawer;

  var header = document.createElement('div');
  header.style.cssText =
    'display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid ' + BORDER + ';';

  var title = document.createElement('strong');
  title.textContent = 'comfy-studio';
  title.style.cssText = 'flex:1;font-weight:600;';

  var stop = document.createElement('button');
  stop.type = 'button';
  stop.textContent = '停止宿主';
  stop.title = '杀掉后台的 comfy-studio 宿主进程';
  stop.style.cssText =
    'border:1px solid ' + BORDER + ';border-radius:4px;background:transparent;color:' + MUTED + ';' +
    'cursor:pointer;font-size:11px;padding:2px 6px;';
  stop.addEventListener('click', function () {
    Promise.resolve(bridge.stop()).then(refreshStatus, function (err) {
      setStatus('停止失败: ' + message(err), 'error');
    });
  });

  var close = document.createElement('button');
  close.type = 'button';
  close.textContent = '×';
  close.setAttribute('aria-label', '关闭对话面板');
  close.style.cssText =
    'border:none;border-radius:4px;background:transparent;color:' + MUTED + ';' +
    'cursor:pointer;font-size:18px;line-height:1;padding:0 4px;';
  close.addEventListener('click', function () {
    closeDrawer();
  });

  var controls = document.createElement('div');
  controls.style.cssText = 'display:flex;align-items:center;gap:6px;padding:0 12px 8px;';

  var modelLabel = document.createElement('label');
  modelLabel.textContent = '模型';
  modelLabel.setAttribute('for', MODEL_ID);
  modelLabel.style.cssText = 'color:' + MUTED + ';font-size:11px;white-space:nowrap;';

  var model = document.createElement('select');
  model.id = MODEL_ID;
  model.disabled = true;
  model.title = '正在读宿主的模型列表…';
  model.style.cssText =
    'flex:1;min-width:0;box-sizing:border-box;padding:2px 4px;border-radius:4px;' +
    'border:1px solid ' + BORDER + ';background:' + INPUT_BG + ';color:' + FG + ';' +
    'font:inherit;font-size:11px;';
  model.addEventListener('change', function () {
    switchModel(model.value);
  });

  var modelConfig = document.createElement('button');
  modelConfig.id = MODEL_CONFIG_ID;
  modelConfig.type = 'button';
  modelConfig.textContent = '配置…';
  modelConfig.setAttribute('aria-expanded', 'false');
  modelConfig.title = '模型没配好时每一轮都回 -32603：在这里把模型 / 地址 / 密钥存到这台机器上';
  modelConfig.style.cssText =
    'border:1px solid ' + BORDER + ';border-radius:4px;background:transparent;color:' + MUTED + ';' +
    'cursor:pointer;font-size:11px;padding:2px 6px;white-space:nowrap;';
  modelConfig.addEventListener('click', function () {
    toggleModelForm();
  });

  controls.appendChild(modelLabel);
  controls.appendChild(model);
  controls.appendChild(modelConfig);

  // 智能体那一行：换的是**人设**（提示词里的角色段），不是工具表 —— 宿主那边见
  // lib/comfy_studio/agent/catalog.py。它单独占一行，是因为"谁在答"和"用哪个模型答"是两件
  // 事：挤在同一行里，两个下拉都会窄到看不清。
  var agents = document.createElement('div');
  agents.style.cssText = 'display:flex;align-items:center;gap:6px;padding:0 12px 8px;';

  var agentLabel = document.createElement('label');
  agentLabel.textContent = '智能体';
  agentLabel.setAttribute('for', AGENT_ID);
  agentLabel.style.cssText = 'color:' + MUTED + ';font-size:11px;white-space:nowrap;';

  var agent = document.createElement('select');
  agent.id = AGENT_ID;
  agent.disabled = true;
  agent.title = '正在读宿主的智能体清单…';
  agent.style.cssText = model.style.cssText;
  agent.addEventListener('change', function () {
    switchAgent(agent.value);
  });

  agents.appendChild(agentLabel);
  agents.appendChild(agent);

  // 会话那一行：一段对话 = 一个 session_id（宿主那边也这么认，见 lib/comfy_studio/server.py）。
  // 换一段、新开一段、关掉一段都在这一行里，省得再去翻文件。
  var sessions = document.createElement('div');
  // 这一行现在有四个控件（下拉 + ＋ + 关掉 + 清空）：抽屉被拖到最窄时允许换行，
  // 挤成一条缝的话四个按钮谁的字都看不清。
  sessions.style.cssText =
    'display:flex;align-items:center;gap:6px;flex-wrap:wrap;padding:0 12px 8px;';

  var sessionLabel = document.createElement('label');
  sessionLabel.textContent = '会话';
  sessionLabel.setAttribute('for', SESSION_ID);
  sessionLabel.style.cssText = 'color:' + MUTED + ';font-size:11px;white-space:nowrap;';

  var session = document.createElement('select');
  session.id = SESSION_ID;
  session.disabled = true;
  session.title = '正在读宿主的会话清单…';
  session.style.cssText =
    'flex:1;min-width:0;box-sizing:border-box;padding:2px 4px;border-radius:4px;' +
    'border:1px solid ' + BORDER + ';background:' + INPUT_BG + ';color:' + FG + ';' +
    'font:inherit;font-size:11px;';
  session.addEventListener('change', function () {
    switchSession(session.value);
  });

  var sessionNew = document.createElement('button');
  sessionNew.id = SESSION_NEW_ID;
  sessionNew.type = 'button';
  sessionNew.textContent = '＋';
  sessionNew.title = '新开一段对话（当前这段留在这里，随时能选回来）';
  sessionNew.style.cssText =
    'border:1px solid ' + BORDER + ';border-radius:4px;background:transparent;color:' + MUTED + ';' +
    'cursor:pointer;font-size:11px;padding:2px 6px;';
  sessionNew.addEventListener('click', function () {
    newSession();
  });

  var sessionClose = document.createElement('button');
  sessionClose.id = SESSION_CLOSE_ID;
  sessionClose.type = 'button';
  sessionClose.textContent = '关掉';
  sessionClose.title = '把这段对话从宿主里关掉，腾出会话位（对话留在存档里，随时能选回来）';
  sessionClose.style.cssText =
    'border:1px solid ' + BORDER + ';border-radius:4px;background:transparent;color:' + MUTED + ';' +
    'cursor:pointer;font-size:11px;padding:2px 6px;';
  sessionClose.addEventListener('click', function () {
    closeSession();
  });

  // 「清空」与「关掉」并排，但两件事一点都不同：关掉只腾会话位、对话留着；清空是把说过的话
  // 连存档一起抹掉（宿主 agent/reset，见 lib/comfy_studio/server.py 的 agent_reset）。
  // 抹掉撤不回来，所以按钮文字就得让人一眼分得清是哪个。
  var sessionReset = document.createElement('button');
  sessionReset.id = SESSION_RESET_ID;
  sessionReset.type = 'button';
  sessionReset.textContent = '清空';
  sessionReset.title = '把这一段说过的话连存档一起抹掉（撤不回来）';
  sessionReset.style.cssText =
    'border:1px solid ' + BORDER + ';border-radius:4px;background:transparent;color:' + MUTED + ';' +
    'cursor:pointer;font-size:11px;padding:2px 6px;';
  sessionReset.addEventListener('click', function () {
    resetSession();
  });

  sessions.appendChild(sessionLabel);
  sessions.appendChild(session);
  sessions.appendChild(sessionNew);
  sessions.appendChild(sessionClose);
  sessions.appendChild(sessionReset);

  // 技能那一行：skill 是引擎侧定义好的**参数化工作流**（workflow + 参数表，见
  // lib/comfy_studio/skills/catalog.py），面板这边只有"选一个、按一下"两件事。
  // 一键按 skill 自己声明的默认参数跑，跑出来的图直接画在这一页里（见 runSkill）。
  var skills = document.createElement('div');
  skills.style.cssText = 'display:flex;align-items:center;gap:6px;padding:0 12px 8px;';

  var skillLabel = document.createElement('label');
  skillLabel.textContent = '技能';
  skillLabel.setAttribute('for', SKILL_ID);
  skillLabel.style.cssText = 'color:' + MUTED + ';font-size:11px;white-space:nowrap;';

  var skill = document.createElement('select');
  skill.id = SKILL_ID;
  skill.disabled = true;
  skill.title = '正在读引擎的 skill 目录…';
  skill.style.cssText = model.style.cssText;
  skill.addEventListener('change', function () {
    // 选谁不影响任何在途的事（真跑起来是按下"跑一遍"那一刻），所以只把选择记下来。
    // 不记的话，下一轮对话后重读目录会把下拉悄悄拨回上一个 —— 等于替用户改了选择。
    STATE.skill = skill.value;
  });

  var skillRun = document.createElement('button');
  skillRun.id = SKILL_RUN_ID;
  skillRun.type = 'button';
  skillRun.textContent = '跑一遍';
  skillRun.disabled = true;
  skillRun.title = '按这个 skill 声明的默认参数跑一遍，结果画在这一页里';
  skillRun.style.cssText =
    'border:1px solid ' + BORDER + ';border-radius:4px;background:transparent;color:' + MUTED + ';' +
    'cursor:pointer;font-size:11px;padding:2px 6px;white-space:nowrap;';
  skillRun.addEventListener('click', function () {
    runSkill(skill.value);
  });

  skills.appendChild(skillLabel);
  skills.appendChild(skill);
  skills.appendChild(skillRun);

  // 渲染那一行：与技能同一个形状（选一个、按一下），区别在**必填参数要当场填** ——
  // 渲染目标的必填参数是内容本身（提示词 / 歌词 / 要放大的片子名），引擎没给默认值，面板也不
  // 替它编（理由见下面「一键跑渲染目标」那一节）。下拉样式走与技能同一个来源，不各写一份。
  var renders = buildRenderRow(model.style.cssText);

  var status = document.createElement('div');
  status.id = STATUS_ID;
  status.textContent = '正在查询宿主状态…';
  status.style.cssText = 'padding:0 12px 8px;color:' + MUTED + ';font-size:11px;';

  var storage = document.createElement('div');
  storage.id = STORAGE_ID;
  storage.textContent = '正在看它把记忆和对话存在哪…';
  storage.style.cssText = 'padding:0 12px 8px;color:' + MUTED + ';font-size:11px;';

  var log = document.createElement('div');
  log.id = LOG_ID;
  log.style.cssText = 'flex:1;overflow-y:auto;padding:8px 12px;display:flex;flex-direction:column;gap:6px;';

  // 输入框上方那一栏先摆着（默认不显示，见 paintQuotes）：引用卡贴在这儿，用户一眼
  // 看得见这一轮要带上什么原文，也看得见怎么把它去掉。
  var quoteBar = document.createElement('div');
  quoteBar.id = QUOTE_BAR_ID;
  quoteBar.className = 'cs-quote-bar';

  var composer = document.createElement('div');
  composer.style.cssText = 'display:flex;gap:6px;';

  var input = document.createElement('textarea');
  input.id = INPUT_ID;
  input.rows = 2;
  input.placeholder = '让 agent 跑个 skill，或问它队列/历史（Enter 发送，Shift+Enter 换行）';
  input.style.cssText =
    'flex:1;resize:vertical;box-sizing:border-box;padding:6px 8px;border-radius:4px;' +
    'border:1px solid ' + BORDER + ';background:' + INPUT_BG + ';color:' + FG + ';font:inherit;';
  input.addEventListener('keydown', function (event) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      sendTurn();
    }
  });

  var stopTurn = document.createElement('button');
  stopTurn.id = STOP_ID;
  stopTurn.type = 'button';
  stopTurn.textContent = '停止';
  stopTurn.title = '让这一轮尽快停下：已经跑完的工具结果会留下，会话还能接着说下一句';
  stopTurn.style.cssText =
    'display:none;align-self:flex-end;border:1px solid ' + BORDER + ';border-radius:4px;' +
    'background:transparent;color:#ff8080;cursor:pointer;font:inherit;padding:6px 12px;';
  stopTurn.addEventListener('click', function () {
    cancelTurn();
  });

  var send = document.createElement('button');
  send.id = SEND_ID;
  send.type = 'button';
  send.textContent = '发送';
  send.style.cssText =
    'align-self:flex-end;border:1px solid ' + BORDER + ';border-radius:4px;background:transparent;' +
    'color:' + FG + ';cursor:pointer;font:inherit;padding:6px 12px;';
  send.addEventListener('click', function () {
    sendTurn();
  });

  composer.appendChild(input);
  composer.appendChild(stopTurn);
  composer.appendChild(send);

  // 那一行边框与内边距原本挂在输入框那一行上，现在挂到这一整块上：引用栏在它上面，
  // 边框留在输入框那一行会出现"卡片在框外面"的分界。
  var composerBox = document.createElement('div');
  composerBox.style.cssText =
    'display:flex;flex-direction:column;gap:6px;padding:10px 12px;border-top:1px solid ' + BORDER + ';';
  composerBox.appendChild(quoteBar);
  composerBox.appendChild(composer);
  // 对话那一整套（模型/智能体/会话/状态/日志/输入）收进一页里，好跟"管理小说"那页互相
  // 让位。收进容器不影响下面按 id 取元素的写法：id 还是全局唯一的。
  var chatView = document.createElement('div');
  chatView.id = CHAT_VIEW_ID;
  chatView.style.cssText = 'flex:1;min-height:0;display:none;flex-direction:column;';
  // 三页各自是一个 tabpanel（与 novel/project 那两处对齐）：tab 的 aria-controls 指过来，
  // 屏幕阅读器才知道"按下这个标签，那一整页会变"。
  chatView.setAttribute('role', 'tabpanel');

  header.appendChild(title);
  header.appendChild(stop);
  header.appendChild(close);
  chatView.appendChild(controls);
  chatView.appendChild(buildModelForm());
  chatView.appendChild(agents);
  chatView.appendChild(sessions);
  chatView.appendChild(skills);
  chatView.appendChild(renders);
  chatView.appendChild(status);
  chatView.appendChild(storage);
  // 找字那一行钉在消息区上面（它管的就是下面这一块）：平时不占地方 —— 它一直躺着，
  // 只是没输入就什么都不标（见 paintFind 与 buildFindRow）。
  chatView.appendChild(buildFindRow());
  chatView.appendChild(log);
  chatView.appendChild(composerBox);
  drawer.appendChild(header);
  drawer.appendChild(buildTabs());
  drawer.appendChild(chatView);
  // 另外两页收在占满窗口的那一层里（见 buildViewsOverlay）：抽屉里只留对话。
  drawer.appendChild(buildViewsOverlay());
  document.body.appendChild(drawer);
  // 引用栏的显隐只有 paintQuotes 一个作者：摆上架就先按"一张卡都没有"画一次，
  // 不然空栏的内联状态是空的，跟它实际收着的样子对不上（一眼看不出它现在是开是合）。
  paintQuotes();
  installResizeGrip(drawer);
  restoreWidth();
  installWidthWatcher();
  installShortcuts();
  // 抽屉一建出来就按 STATE.view 摆好（默认「对话」）。这一页不落盘：刷新页面回到对话，
  // 是件正常的事 —— 而"上次我在改小说"并不像"上次聊到哪一段"那样值得跨重载记住。
  switchView(STATE.view);
  return drawer;
}

function setStatus(text, tone) {
  var status = document.getElementById(STATUS_ID);
  if (!status) return;
  status.textContent = text;
  // 语气一并记在 dataset 上（跟另外两页的提示行同一套，见 hintLine）：内联色留着，
  // 因为这一行原本就是靠它上的色，改口径不该顺手把它拆了。
  status.dataset.tone = tone === 'error' ? 'error' : 'info';
  status.style.color = tone === 'error' ? '#ff8080' : MUTED;
}

function setSendEnabled(enabled) {
  var send = document.getElementById(SEND_ID);
  if (!send) return;
  send.disabled = !enabled;
  send.style.opacity = enabled ? '1' : '0.5';
  send.style.cursor = enabled ? 'pointer' : 'not-allowed';
}

// "停止"只在有轮次在飞时露出来：没有在跑的活时它没有意义，摆在那儿只会让人以为
// 有东西卡住了。每次露出来都顺手把 disabled 复位——上一次点击会把它按下去。
//
// 它有第二种身份（detached）：界面已经被强行复位（见 forceResetTurn）、而宿主那一轮
// 还占着这个会话时，面板里已经没有"这一轮"可停了，能停的只剩宿主手里那一份。那时它做的
// 是叫停宿主那一轮，字面也得跟着换 —— 否则用户按下去不知道自己在停什么。
function setStopVisible(visible, detached) {
  var stop = document.getElementById(STOP_ID);
  if (!stop) return;
  stop.style.display = visible ? 'inline-block' : 'none';
  stop.style.opacity = '1';
  stop.disabled = false;
  if (!visible) return;
  stop.textContent = detached ? '叫停宿主那一轮' : '停止';
  stop.title = detached
    ? '面板已经放手，但宿主那一轮还占着这个会话：点它就把它叫停（agent/cancel）'
    : '让这一轮尽快停下：已经跑完的工具结果会留下，会话还能接着说下一句';
}

// 宿主挡下"同一个会话的第二轮"用的就是这个码（见 lib/comfy_studio/server.py 的
// agent_chat：INVALID_PARAMS = -32602）。认码也认字：码是契约，字是给读日志的人看的。
var SESSION_BUSY_CODE = -32602;
function isSessionBusy(error) {
  if (!error) return false;
  if (error.code === SESSION_BUSY_CODE) return true;
  return typeof error.message === 'string' && error.message.indexOf('已有一轮在跑') >= 0;
}

function setModelEnabled(enabled) {
  var model = document.getElementById(MODEL_ID);
  if (!model) return;
  model.disabled = !enabled;
  model.style.opacity = enabled ? '1' : '0.5';
  model.style.cursor = enabled ? 'pointer' : 'not-allowed';
}

// 没候选模型、宿主不可用、或有一轮在飞时，都不该让用户去切模型
function refreshModelEnabled() {
  var model = document.getElementById(MODEL_ID);
  if (!model) return;
  setModelEnabled(!STATE.busy && model.options.length > 0);
}

function setAgentEnabled(enabled) {
  var agent = document.getElementById(AGENT_ID);
  if (!agent) return;
  agent.disabled = !enabled;
  agent.style.opacity = enabled ? '1' : '0.5';
  agent.style.cursor = enabled ? 'pointer' : 'not-allowed';
}

// 没清单、宿主不可用、或有一轮在飞时，都不该让用户去换智能体：人设是在每一轮开头算的，
// 中途换会让"下拉里显示的那个"和"这一轮实际用的那个"对不上（下一轮才按新的来）。
function refreshAgentEnabled() {
  var agent = document.getElementById(AGENT_ID);
  if (!agent) return;
  setAgentEnabled(!STATE.busy && agent.options.length > 0);
}

function setSessionEnabled(enabled) {
  var ids = [SESSION_ID, SESSION_NEW_ID, SESSION_CLOSE_ID, SESSION_RESET_ID];
  for (var i = 0; i < ids.length; i++) {
    var el = document.getElementById(ids[i]);
    if (!el) continue;
    el.disabled = !enabled;
    el.style.opacity = enabled ? '1' : '0.5';
    el.style.cursor = enabled ? 'pointer' : 'not-allowed';
  }
}

// 换/开/关会话都只在没轮次在飞时允许：一轮的回答是画在**当前这一段**上的，
// 中途换走就成了"答到别人家去了"。
function refreshSessionEnabled() {
  setSessionEnabled(!STATE.busy);
}

// ---- 消息节点 ----------------------------------------------------------
//
// 一种事件 = 一种节点，各画各的（跟参考实现里 kind → 渲染器那张表一个意思）。
// 关键的一条：**节点才是唯一真相**，事件来了改已有节点，而不是永无止境地往下
// 追加行。工具调用就是最明显的例子——事件里带 id，调用与它的结果配对成同一张
// 卡：结果回来时改那张卡的状态与正文。早先的写法把两者画成两条互不相干的等宽
// 文本行，靠人脑去对齐 id。

//: 卡里正文默认铺多少字符，超出给一个"展开全部"。
var RESULT_FOLD = 600;
var ARGS_FOLD = 1200;

function logEl() {
  return document.getElementById(LOG_ID);
}

// 用户往上翻着看历史时，别拿新行把他拽回底部。
function scrollLog(log) {
  if (log.scrollHeight - log.scrollTop - log.clientHeight < 40) {
    log.scrollTop = log.scrollHeight;
  }
}

// ---- 自己说过的那一行：复制、改一下重说 --------------------------------------
//
// 只给用户自己发的那一行挂两件事，出处是 ComfyUI 官方前端 agent 面板的
// src/workbench/extensions/agent/components/agent/message/UserMessage.vue：那边同样是 hover 才
// 露出来、同样只有"复制"与"编辑"两件，复制成功把文案换成对勾并保持 2 秒（copiedDuring: 2000），
// 而且「编辑」没有任何"把原话从历史里拿掉"的语义 —— 它只是把原文交回输入框。
//
// 面板这边照抄，同时把一件宿主根本没有的能力说清楚：宿主没有"改掉某一条历史"的口子
// （agent/chat 只接一段话，见 lib/comfy_studio/server.py 的 agent_chat），所以「改一下」＝
// 原话回到输入框，改完发出去是**另起一轮**，原来那一轮还在这一段里。这一句得写在提示行上；
// 不写就等于骗人（用户会以为改掉的是历史里的那一条）。
var COPY_LABEL = '复制';
var COPIED_LABEL = '已复制';
var COPIED_MS = 2000;

function userActions(text) {
  var bar = document.createElement('div');
  bar.className = 'cs-user-actions';
  var copy = document.createElement('button');
  copy.type = 'button';
  copy.className = 'cs-user-action';
  copy.textContent = COPY_LABEL;
  copy.title = '把这一段原样拷到剪贴板';
  copy.addEventListener('click', function () {
    copyUserText(text, copy);
  });
  var edit = document.createElement('button');
  edit.type = 'button';
  edit.className = 'cs-user-action';
  edit.textContent = '改一下';
  edit.title = '把这段话放回输入框改（发出去是另起一轮，原来那一轮还在）';
  edit.addEventListener('click', function () {
    editUserText(text);
  });
  bar.appendChild(copy);
  bar.appendChild(edit);
  return bar;
}

// 复制：先试剪贴板接口，这个环境不给（webview 没授权、或不是安全上下文）就把这一段选亮、
// 让人自己按 Ctrl+C —— 静默失败最坏：用户以为拷上了，粘出来是上一份东西。
function copyUserText(text, button) {
  var done = function () {
    if (!button) return;
    button.textContent = COPIED_LABEL;
    window.setTimeout(function () {
      if (button.textContent === COPIED_LABEL) button.textContent = COPY_LABEL;
    }, COPIED_MS);
  };
  var failed = function () {
    selectRowText(button);
    setStatus('这个环境不让面板写剪贴板：已经帮你把这一段选亮了，按 Ctrl+C 自己拷。', 'error');
  };
  var clipboard = navigator.clipboard;
  if (!clipboard || typeof clipboard.writeText !== 'function') {
    failed();
    return null;
  }
  return Promise.resolve(clipboard.writeText(text)).then(done, failed);
}

// 选中这一行里"人说的话"（不含动作条自己那两个按钮）。选不了就直接算了：
// 那只是一条补救提示，为它再抛一次错更没意思。
function selectRowText(node) {
  var row = node;
  // 反斜杠要写两遍：这一段 JS 住在 TS 模板字符串里，只写一个反斜杠加 s 会被吃掉、变成字面的 s
  // （见 novelToChat 里同一处坑；对拍用例抓过一次：正则成了 (^|s)cs-rows(s|$)，永远不命中）。
  while (row && !(row.className && String(row.className).match(/(^|\\s)cs-row(\\s|$)/))) {
    row = row.parentNode;
  }
  if (!row) return;
  var selection = typeof window.getSelection === 'function' ? window.getSelection() : null;
  if (!selection || typeof document.createRange !== 'function') return;
  var words = row.querySelector('.cs-user-words');
  var range = document.createRange();
  range.selectNodeContents(words || row);
  selection.removeAllRanges();
  selection.addRange(range);
}

// 「改一下」：原话整段回到输入框（带引用块的原话也整段回来 —— 引用标记本来就是文本的一部分，
// 见 composeQuotes / splitQuotes），光标落到末尾。句子回到输入框之后**不自动发送**：
// 发出去是用户的事。
function editUserText(text) {
  var input = document.getElementById(INPUT_ID);
  if (!input) return null;
  input.value = text;
  input.focus();
  if (typeof input.setSelectionRange === 'function') {
    input.setSelectionRange(text.length, text.length);
  }
  setStatus('这段话放回输入框了：改完发出去是另起一轮，原来那一轮还留在这段对话里。');
  return text;
}

// ---- 在这一段对话里找字 ------------------------------------------------------
//
// 三件事先说清：
// ① **只找"说过的话"**（data-kind user/assistant）：工具卡、错误行不参与 —— 在工具回包的
//    JSON 里命中一个词，对"我刚才那句话在哪"没有帮助；
// ② **只标行、不动字**：命中的行打 [data-hit]，当前那一处再打 [data-hit="current"]。
//    往行里插 <mark> 得重建这一行的内容，会把工具卡、图片卡拆掉（那些卡是增量画上去的）；
// ③ 上一处/下一处**环绕**并且**跳过没有命中的行**：这个语义取自 ComfyUI 官方前端
//    src/workbench/extensions/agent/composables/agent/mentionPickerState.ts 的
//    highlighted + highlightMoved(direction, disabled)：那边也是环绕、也是跳过不可选项。
//    官方 agent 面板没有会话内检索（只有那个提及选择器），所以这一行的用法照浏览器 Ctrl+F
//    的通用惯例来：找字 → 看"第几处" → 上一处/下一处 → 清空。
function findRowText(row) {
  // 用户那一行里躺着动作条（复制 / 改一下）：连文本一起找，搜"复制"就会命中每一行。
  // 克隆一份、摘掉动作条再取字，比给行里每个节点分情况拼字稳（引用卡、图片卡都在行里）。
  var copy = row.cloneNode(true);
  var bar = copy.querySelector('.cs-user-actions');
  if (bar && bar.parentNode) bar.parentNode.removeChild(bar);
  return String(copy.textContent || '');
}

function findHitRows(query) {
  var log = logEl();
  var hits = [];
  if (!log || !query) return hits;
  var rows = log.querySelectorAll('[data-kind="user"],[data-kind="assistant"]');
  for (var index = 0; index < rows.length; index += 1) {
    if (findRowText(rows[index]).indexOf(query) >= 0) hits.push(rows[index]);
  }
  return hits;
}

// 画命中标记与计数。scroll=false 时一个像素都不动（列表变长时重算用，见 refreshFind）。
function paintFind(hits, at, scroll) {
  var log = logEl();
  if (log) {
    var marked = log.querySelectorAll('[data-hit]');
    for (var index = 0; index < marked.length; index += 1) delete marked[index].dataset.hit;
  }
  for (var i = 0; i < hits.length; i += 1) {
    hits[i].dataset.hit = i === at ? 'current' : 'true';
  }
  var count = document.getElementById(FIND_COUNT_ID);
  if (count) {
    if (!STATE.find) count.textContent = '';
    else count.textContent = hits.length === 0 ? '没找到' : at + 1 + '/' + hits.length + ' 处';
    count.dataset.tone = STATE.find && hits.length === 0 ? 'error' : 'info';
  }
  if (scroll && at >= 0 && hits[at] && typeof hits[at].scrollIntoView === 'function') {
    hits[at].scrollIntoView({ block: 'center' });
  }
}

// 敲字就重找一遍，并跳到第一处（跟浏览器里找字的手感一致：先看到最上面那一处）。
function runFind(query) {
  STATE.find = query;
  STATE.findHits = findHitRows(query);
  STATE.findAt = STATE.findHits.length > 0 ? 0 : -1;
  paintFind(STATE.findHits, STATE.findAt, true);
  return STATE.findHits.length;
}

// 上一处 / 下一处：环绕（到头了绕回另一端）—— 见上面第 ③ 条。
function moveFind(step) {
  var hits = STATE.findHits || [];
  if (!STATE.find || hits.length === 0) return 0;
  STATE.findAt = ((STATE.findAt + step) % hits.length + hits.length) % hits.length;
  paintFind(hits, STATE.findAt, true);
  return STATE.findAt;
}

// 这一段后来又长了（刚发了一轮、或者刚画完历史）：命中表要重算，但**别把人正在看的那一处
// 挪走** —— 位置夹回范围内就行。不重算的话计数会跟屏幕上对不上。
function refreshFind() {
  if (!STATE.find) return;
  STATE.findHits = findHitRows(STATE.find);
  if (STATE.findAt >= STATE.findHits.length) STATE.findAt = STATE.findHits.length - 1;
  paintFind(STATE.findHits, STATE.findAt, false);
}

function clearFind() {
  STATE.find = '';
  STATE.findHits = [];
  STATE.findAt = -1;
  var box = document.getElementById(FIND_ID);
  if (box) box.value = '';
  paintFind([], -1, false);
}

function buildFindRow() {
  var row = document.createElement('div');
  row.className = 'cs-find';
  var box = document.createElement('input');
  box.id = FIND_ID;
  box.type = 'text';
  box.placeholder = '在这一段对话里找一串字';
  box.title = '只在"你说的话"与"模型的回答"里找（工具结果不参与）；Enter 下一处，Shift+Enter 上一处，Esc 清空';
  box.addEventListener('input', function () {
    runFind(box.value || '');
  });
  box.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') {
      event.preventDefault();
      moveFind(event.shiftKey ? -1 : 1);
    } else if (event.key === 'Escape') {
      event.preventDefault();
      clearFind();
    }
  });
  var count = document.createElement('span');
  count.id = FIND_COUNT_ID;
  count.className = 'cs-find-count';
  var prev = document.createElement('button');
  prev.id = FIND_PREV_ID;
  prev.type = 'button';
  prev.className = 'cs-find-btn';
  prev.textContent = '上一处';
  prev.title = '往上找（到头了绕回最后一处）';
  prev.addEventListener('click', function () {
    moveFind(-1);
  });
  var next = document.createElement('button');
  next.id = FIND_NEXT_ID;
  next.type = 'button';
  next.className = 'cs-find-btn';
  next.textContent = '下一处';
  next.title = '往下找（到头了绕回第一处）';
  next.addEventListener('click', function () {
    moveFind(1);
  });
  var clear = document.createElement('button');
  clear.id = FIND_CLEAR_ID;
  clear.type = 'button';
  clear.className = 'cs-find-btn';
  clear.textContent = '清空';
  clear.title = '清掉找字（标记一起摘掉）';
  clear.addEventListener('click', function () {
    clearFind();
  });
  row.appendChild(box);
  row.appendChild(count);
  row.appendChild(prev);
  row.appendChild(next);
  row.appendChild(clear);
  return row;
}

function makeRow(kind) {
  var row = document.createElement('div');
  row.setAttribute('data-kind', kind);
  row.className = 'cs-row cs-' + kind;
  return row;
}

// 在飞的"正在思考"标记永远占最后一行：新节点插在它前面，它掉到哪儿都还是末尾。
function appendNode(row) {
  var log = logEl();
  if (!log) return null;
  var pending = STATE.pending;
  if (pending && pending.parentNode === log) log.insertBefore(row, pending);
  else log.appendChild(row);
  scrollLog(log);
  // 消息区一变，正在找字的命中表就得跟着重算（没在找字时这一句什么都不做）。
  // 放在这里是因为所有行都从这条路过（工具卡、图片卡也是）；找字期间的行数通常很少，
  // 重算一次比"谁加了行谁自己去报告"少一大堆接线，也不会漏掉某一种行。
  if (STATE.find) refreshFind();
  return row;
}

function addUser(text) {
  var row = makeRow('user');
  var parts = splitQuotes(text);
  // 话本身单独包一层（.cs-user-words），没有引用卡时也包：动作条是挂在同一行里的兄弟节点，
  // 不包的话"把这一段选亮"就会连「复制 改一下」一起选进去 —— 拷出来多两个字，比不拷更坏。
  var words = document.createElement('div');
  words.className = 'cs-user-words';
  if (parts.quotes.length === 0) {
    words.textContent = text;
    row.appendChild(words);
    row.appendChild(userActions(text));
    return appendNode(row);
  }
  // 引用卡压在气泡里，用户自己那句话在它下面当主角：卡说的是"从哪儿摘的"，话才是他要说的。
  // 实时那一条与重开面板后重画的那一条走的是同一个 addUser，所以两种来路画出来一模一样。
  parts.quotes.forEach(function (quote) {
    row.appendChild(quoteCard(quote, null));
  });
  if (parts.text !== '') {
    words.textContent = parts.text;
    row.appendChild(words);
  }
  // 动作条两种来路都挂：重画历史时也挂，不然"重开面板之后那条话就改不了了"。
  row.appendChild(userActions(text));
  return appendNode(row);
}

function addPending() {
  var log = logEl();
  if (!log || STATE.pending) return STATE.pending;
  var row = makeRow('pending');
  var dot = document.createElement('span');
  dot.className = 'cs-dot';
  var label = document.createElement('span');
  label.textContent = '正在思考…';
  row.appendChild(dot);
  row.appendChild(label);
  log.appendChild(row);
  scrollLog(log);
  STATE.pending = row;
  STATE.pendingLabel = label;
  return row;
}

function removePending() {
  var row = STATE.pending;
  STATE.pending = null;
  STATE.pendingLabel = null;
  STATE.forceReset = null;
  if (row && row.parentNode) row.parentNode.removeChild(row);
}

// ---- 一轮在飞时的读数 --------------------------------------------------

// 宿主那边一次模型调用可以等到 180s × 最多 5 次重试（见 lib/comfy_studio/agent/llm.py），
// 这期间**一个字节都不会往面板送** —— 除了它主动报的那句重试通知。而那句通知原先根本没被
// 画出来（见 onEvent）：于是"在重试"和"真卡死"在界面上长得一模一样，都是那个不动的
// "正在思考…"。这里自己走表，把"等了多久"和"正在重试"摆到脸上。
var TURN_TICK_MS = 1000;

// 等过这么多秒还没有任何回应，就把"我自己放下"的按钮摆出来。它是**提示**不是判负：
// 宿主那一轮还攥着这个会话，自动解锁只会让下一句撞上"会话已有一轮在跑"
// （见 lib/comfy_studio/server.py 的 agent_chat）。所以要不要放开，由用户自己按。
var TURN_SOFT_TIMEOUT_S = 300;

function stopTurnClock() {
  if (STATE.turnTimer) {
    window.clearInterval(STATE.turnTimer);
    STATE.turnTimer = null;
  }
  STATE.turnStartedAt = 0;
  STATE.turnNote = '';
  STATE.softWarned = false;
}

function startTurnClock() {
  stopTurnClock();
  STATE.turnStartedAt = Date.now();
  STATE.turnTimer = window.setInterval(paintTurnClock, TURN_TICK_MS);
  paintTurnClock();
}

function turnWaitedSeconds() {
  if (!STATE.turnStartedAt) return 0;
  return Math.floor((Date.now() - STATE.turnStartedAt) / 1000);
}

function paintTurnClock() {
  if (!STATE.busy || !STATE.turnStartedAt) return;
  var label = STATE.pendingLabel;
  if (!label) return;
  var seconds = turnWaitedSeconds();
  var waited = '（已等待 ' + seconds + 's）';
  label.textContent = STATE.turnNote ? STATE.turnNote + waited : '正在思考…' + waited;
  if (seconds >= TURN_SOFT_TIMEOUT_S) offerForceReset();
}

// 等够久了：给一条自己走得掉的路。
function offerForceReset() {
  if (STATE.forceReset || !STATE.pending) return;
  var row = STATE.pending;
  var button = document.createElement('button');
  button.type = 'button';
  button.className = 'cs-force-reset';
  button.textContent = '强制复位界面';
  // 说清它做了什么、没做什么：它只把界面从"一直等下去"里救出来，**不会**叫停宿主那一轮
  // （要停它请点「停止」，那条路才会告诉宿主）。
  button.title = '只把面板从"一直等下去"里救出来：不会叫停宿主那一轮，要停它请点「停止」';
  button.addEventListener('click', forceResetTurn);
  row.appendChild(button);
  STATE.forceReset = button;
  STATE.softWarned = true;
}

function forceResetTurn() {
  if (!STATE.busy) return;
  // 后端那一轮**没有停**（这里没有发 agent/cancel）：只把界面放开，并把这件事说明白 ——
  // 默默放开的话，用户下一句会撞上"会话已有一轮在跑"，那才叫莫名其妙。
  //
  // 收尾（finishTurn → settle）会把 busy 清零、把"停止"键摘掉；可宿主那一轮还在跑，摘掉它
  // 就等于把唯一够得着那一轮的手段一起摘了 —— 文案让用户去点"停止"，而"停止"恰好在这一刻
  // 消失，用户手上只剩"发一句被拒一次"这一条路。所以这次收尾按 detached 走：键留下来，
  // 换成"叫停宿主那一轮"（见 setStopVisible / cancelTurn）。
  if (typeof STATE.finishTurn === 'function') STATE.finishTurn();
  addError(
    '已强行复位界面：宿主那一轮可能还在跑，这个会话暂时发不出新话。' +
      '点「叫停宿主那一轮」把它收掉，或换个会话（它自己跑完也会好）。'
  );
  setStatus('界面已复位（宿主那一轮可能还在跑）', 'error');
}

// variant: final = 这一轮的回答，intermediate = 过程中的话（模型一边要工具一边说的）
function addAssistant(text, variant) {
  var row = makeRow('assistant');
  row.setAttribute('data-variant', variant || 'intermediate');
  row.textContent = text;
  return appendNode(row);
}

// 被停下的一轮：不是失败，也不是回答。留一行说明，好让人知道这一轮为什么没结果。
function addStopped(reason) {
  var row = makeRow('stopped');
  row.textContent = '已停止';
  if (reason) row.title = '原因: ' + reason;
  return appendNode(row);
}

function addError(text, code) {
  var row = makeRow('error');
  row.textContent = text;
  if (typeof code === 'number') {
    row.setAttribute('data-error-code', String(code));
    row.textContent = text + '（错误码 ' + code + '）';
  }
  return appendNode(row);
}

// 一段可能很长的正文：默认折叠，点一下展开全部（原文不动，只改显示）。
function makeBlock(label, text, fold) {
  var wrap = document.createElement('div');
  var head = document.createElement('div');
  head.className = 'cs-block-label';
  head.textContent = label;
  var pre = document.createElement('pre');
  pre.className = 'cs-block';
  pre.textContent = truncate(text, fold);
  wrap.appendChild(head);
  wrap.appendChild(pre);
  if (text.length > fold) {
    var more = document.createElement('button');
    more.type = 'button';
    more.className = 'cs-block-more';
    more.textContent = '展开全部（' + text.length + ' 字符）';
    more.addEventListener('click', function () {
      pre.textContent = text;
      if (more.parentNode) more.parentNode.removeChild(more);
    });
    wrap.appendChild(more);
  }
  return wrap;
}

// ---- 引用原文：卡片与那条通道 ----------------------------------------------
//
// 一次引用 = 一段原文 + 它在哪一篇的哪个字起。面板把它折成一张卡贴在输入框上方，发出去
// 的时候拼进这一轮的话里。两处取舍直说：
//
// ① **文本从宿主来**。卡里的字是 novels/read 给的那一份（认编码、按字符分页都在
//    novels.py 那边），面板不自己读文件、也不改写一个字 —— 位置与文本若不是同一个来路，
//    模型看到的就成了"第 1200 字起，内容是别处的字"。取回来多少字也认宿主报的 chars，
//    面板不自己数（JS 的 length 数的是 UTF-16 单元，跟宿主数的**字符**在个别码位上不是
//    一回事）。
// ② **拼装只有面板一个作者**。宿主 agent/chat 收到的就是一段话，它不知道哪几行是引用
//    —— 这是有意选的：卡里的文本与发出去的字是同一份，用户所见即所发。代价也直说：文件
//    在"做卡"之后被外面改过，发出去的仍是做卡那一刻的原文（与"附上一段引文"本来的含义一致）。

//: 一条消息开头那段引用块的语法。它只有一个作者（composeQuotes）、一个读者
//: （splitQuotes），两端都在这个文件里，所以不必跨语言对齐。形状：整行标记、原文、
//: 整行收尾 —— 人翻历史时也一眼看得出哪儿是引用。
var QUOTE_OPEN_RE = /^\\[引用 (.{1,200}?) (\\d+) (\\d+)\\]$/;
var QUOTE_CLOSE = '[/引用]';

//: 一次最多带几段引用、一段默认取多少字、卡里正文先铺多少字符。
var MAX_QUOTES = 4;
var QUOTE_CHARS = 800;
var QUOTE_FOLD = 160;

function quoteTitle(quote) {
  return '引用 ' + quote.name + ' · 第 ' + quote.offset + ' 字起 ' + quote.chars + ' 字';
}

// 一张引用卡。removable 只在"还没发出去"那一栏里打开：已经进了消息的那张没法去掉。
function quoteCard(quote, options) {
  var more = null;
  var card = document.createElement('div');
  card.className = 'cs-quote';
  var head = document.createElement('div');
  head.className = 'cs-quote-head';
  var label = document.createElement('span');
  label.className = 'cs-quote-title';
  label.textContent = quoteTitle(quote);
  if (quote.total_chars) label.title = quote.name + ' 全篇 ' + quote.total_chars + ' 字';
  head.appendChild(label);
  if (options && options.removable === true) {
    var drop = document.createElement('button');
    drop.type = 'button';
    drop.className = 'cs-quote-drop';
    drop.textContent = '×';
    drop.title = '把这张卡去掉（这段原文就不发了）';
    drop.addEventListener('click', function () {
      dropQuote(options.index);
    });
    head.appendChild(drop);
  }
  var body = document.createElement('div');
  body.className = 'cs-quote-body';
  var text = String(quote.text || '');
  body.textContent = truncate(text, QUOTE_FOLD);
  if (text.length > QUOTE_FOLD) {
    more = document.createElement('button');
    more.type = 'button';
    more.className = 'cs-quote-more';
    more.textContent = '展开全部（' + text.length + ' 字符）';
    more.addEventListener('click', function () {
      body.textContent = text;
      if (more.parentNode) more.parentNode.removeChild(more);
    });
  }
  card.appendChild(head);
  card.appendChild(body);
  if (more) card.appendChild(more);
  return card;
}

// 输入框上方那一栏：这一轮要带上的引用。发出去之后就清掉 —— 它已经进了那条消息里。
function paintQuotes() {
  var bar = document.getElementById(QUOTE_BAR_ID);
  if (!bar) return;
  bar.textContent = '';
  var quotes = STATE.quotes || [];
  bar.style.display = quotes.length ? 'flex' : 'none';
  quotes.forEach(function (quote, index) {
    bar.appendChild(quoteCard(quote, { removable: true, index: index }));
  });
}

function dropQuote(index) {
  var quotes = STATE.quotes || [];
  if (!(index >= 0 && index < quotes.length)) return;
  quotes.splice(index, 1);
  paintQuotes();
}

// 这一段话最终长什么样：开头是引用块，空一行，然后是用户自己的话。
function composeQuotes(text, quotes) {
  var blocks = (quotes || []).map(function (quote) {
    return (
      '[引用 ' + quote.name + ' ' + quote.offset + ' ' + quote.chars + ']\\n' +
      quote.text +
      '\\n' +
      QUOTE_CLOSE
    );
  });
  if (blocks.length === 0) return text;
  var head = blocks.join('\\n\\n');
  return text === '' ? head : head + '\\n\\n' + text;
}

// 反过来：把一条消息拆成"开头的引用块" + 剩下的那句话。
// **认不出来就整条当普通话**：用户自己手打的字也可能长成这个形状，那时他看到的仍是自己
// 的原文（只是多了一张卡），没有坏处；而能画成卡的，只有我们发出去的那一种形状。
function splitQuotes(text) {
  var lines = String(text || '').split('\\n');
  var quotes = [];
  var index = 0;
  while (index < lines.length) {
    var match = QUOTE_OPEN_RE.exec(lines[index]);
    if (!match) break;
    var end = index + 1;
    while (end < lines.length && lines[end] !== QUOTE_CLOSE) end += 1;
    if (end >= lines.length) {
      // 没等到收尾那一行：形状不完整，整条照普通话画（宁可少画一张卡，也不猜到哪里为止）。
      quotes = [];
      index = 0;
      break;
    }
    quotes.push({
      name: match[1],
      offset: Number(match[2]),
      chars: Number(match[3]),
      text: lines.slice(index + 1, end).join('\\n')
    });
    index = end + 1;
    if (lines[index] === '') index += 1; // 块与块、块与正文之间空的那一行
  }
  return { quotes: quotes, text: lines.slice(index).join('\\n') };
}

// 正文里选中的那一段落在原文的哪一段字上。
// 选择框只可能落在正文那**一个**文本节点里（paintNovelPage 用 textContent 铺字），所以
// "页起点 + 节点内的偏移"就是原文位置。选在别处（左栏、提示行、翻页行）一律当没选：
// 猜错位置比不引用糟得多（模型会拿着一处根本不是用户指的地方开工）。
function readerSelection(open) {
  if (typeof window.getSelection !== 'function') return null;
  var reader = document.getElementById(NOVEL_READER_ID);
  var selection = window.getSelection();
  if (!reader || !selection || selection.rangeCount === 0 || selection.isCollapsed) return null;
  var range = selection.getRangeAt(0);
  if (!reader.contains(range.startContainer) || !reader.contains(range.endContainer)) return null;
  if (range.startContainer !== range.endContainer) return null; // 跨节点：本该不会发生，当没选
  var start = Math.min(range.startOffset, range.endOffset);
  var end = Math.max(range.startOffset, range.endOffset);
  if (end <= start) return null;
  return { offset: open.offset + start, chars: end - start };
}

// 「引用」那一下：选中的就引选中的，没选就引这一页的开头一段。两种都会当场说明是哪一种 ——
// 不猜用户想要哪种，也不静默地替他按某一种做。
function quoteFromReader() {
  var open = STATE.novelOpen;
  if (!open) {
    novelHint('先在列表里点一行「读」打开一篇，再引用它里面的原文。', 'info');
    return null;
  }
  var picked = readerSelection(open);
  return quoteRange(
    open.name,
    picked ? picked.offset : open.offset,
    picked ? picked.chars : QUOTE_CHARS,
    picked ? '引用了选中的 ' + picked.chars + ' 字' : '正文里没选中，引用了这一页开头的一段'
  );
}

// 取一段原文做成卡。位置与字数原样交给宿主，回来多少就信多少（见上面第 ① 条）。
function quoteRange(name, offset, chars, note) {
  var quotes = STATE.quotes || (STATE.quotes = []);
  if (quotes.length >= MAX_QUOTES) {
    novelHint('一次最多带 ' + MAX_QUOTES + ' 段引用：先发一轮，或把不要的那张去掉。', 'error');
    return null;
  }
  return Promise.resolve(
    bridge.request('novels/read', { name: name, offset: offset, chars: chars })
  ).then(
    function (response) {
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        novelHint('取不出这段原文: ' + (error.message || '未知错误'), 'error');
        return null;
      }
      var result = response.result || {};
      var text = String(result.text || '');
      if (text.replace(/\\s/g, '') === '') {
        // 空卡不给：发出去的是"这里本来有段原文"，而用户与模型都不知道它是空的。
        // 到全篇末尾、或者那儿一片空行，都是同一种情况 —— 没有可引的原文。
        novelHint('第 ' + offset + ' 字起的这一段只有空白，没有可引的原文，换个位置再引用。', 'error');
        return null;
      }
      quotes.push({
        name: String(result.name || name),
        offset: Number(result.offset) || 0,
        chars: Number(result.chars) || 0,
        total_chars: Number(result.total_chars) || 0,
        text: text
      });
      paintQuotes();
      // 卡片在对话页的输入框上方：不切过去，用户还得自己找它在哪儿。切过去之后把"带上了
      // 什么、能去哪儿去掉"说清（那正是他接着要做的事）。
      switchView('chat');
      var added = quotes[quotes.length - 1];
      setStatus(
        note + '：' + added.name + ' 第 ' + added.offset + ' 字起 ' + added.chars +
          ' 字（卡片在输入框上方，可以去掉）'
      );
      return result;
    },
    function (err) {
      novelHint('取不出这段原文: ' + message(err), 'error');
      return null;
    }
  );
}

// 工具名是 <server>__<tool>；分开显示，好认是哪个 server 报上来的
function splitToolName(name) {
  var at = name.indexOf('__');
  if (at <= 0) return { server: '', tool: name };
  return { server: name.slice(0, at), tool: name.slice(at + 2) };
}

function makeToolCard(params) {
  var name = String((params && params.name) || '未知工具');
  var parts = splitToolName(name);
  var card = makeRow('tool');
  card.setAttribute('data-tool', name);
  card.setAttribute('data-state', 'running');

  var head = document.createElement('button');
  head.type = 'button';
  head.className = 'cs-tool-head';
  head.setAttribute('aria-expanded', 'true');

  var dot = document.createElement('span');
  dot.className = 'cs-dot';
  head.appendChild(dot);

  if (parts.server) {
    var server = document.createElement('span');
    server.className = 'cs-tool-server';
    server.textContent = parts.server;
    head.appendChild(server);
  }
  var label = document.createElement('span');
  label.className = 'cs-tool-name';
  label.textContent = parts.tool;
  head.appendChild(label);

  var state = document.createElement('span');
  state.className = 'cs-tool-state';
  state.textContent = '运行中…';
  head.appendChild(state);

  var body = document.createElement('div');
  body.className = 'cs-tool-body';

  head.addEventListener('click', function () {
    var collapsed = card.getAttribute('data-collapsed') === '1';
    card.setAttribute('data-collapsed', collapsed ? '0' : '1');
    head.setAttribute('aria-expanded', collapsed ? 'true' : 'false');
  });

  card.appendChild(head);
  card.appendChild(body);
  card.csBody = body;
  card.csState = state;
  return card;
}

function addToolCall(params) {
  var card = makeToolCard(params);
  if (params && params.id != null) STATE.cards[String(params.id)] = card;
  if (params && params.arguments) {
    card.csBody.appendChild(makeBlock('参数', JSON.stringify(params.arguments, null, 2), ARGS_FOLD));
  }
  return appendNode(card);
}

// 工具执行失败不算协议错误：宿主把 isError 的结果标成 "ERROR: ..." 文本喂回来
// （见 lib/comfy_studio/mcp/result.py 的 tool_text），这里按同一个约定上红点。
function addToolResult(params) {
  var id = params && params.id != null ? String(params.id) : '';
  var card = id ? STATE.cards[id] : null;
  var orphan = false;
  if (!card) {
    // 结果没配上前面的调用：不静默丢，单独画一张并说明它没配上。
    orphan = true;
    card = makeToolCard(params);
    card.setAttribute('data-orphan', '1');
    card.setAttribute('data-collapsed', '0');
    appendNode(card);
  }
  var text = String((params && params.text) || '');
  var failed = text.indexOf('ERROR:') === 0;
  // 状态与文案只在这一处定：先写一句再被下面盖掉，就白写了。
  card.setAttribute('data-state', failed ? 'error' : 'done');
  card.csState.textContent = (failed ? '失败' : '完成') + (orphan ? '（没等到调用事件）' : '');
  card.csBody.appendChild(makeBlock('结果', text, RESULT_FOLD));
  scrollLog(logEl());
  return card;
}

// ---- 面板里的模型配置 --------------------------------------------------
//
// 模型没配好时每一轮都回 -32603「请设置 COMFY_STUDIO_LLM_MODEL」，而这三项本来只在环境变量
// 里 —— 宿主是桌面壳自己拉起来的进程，用户改不了它的环境，于是"被告知了却没有地方补救"。
// 这一小块把那三个值存进宿主用户目录里的 settings.json（宿主那边见 lib/comfy_studio/settings.py），
// 下次启动自动注入环境变量。**环境变量已经给了值的那些项，在这儿改了也不生效** ——
// 宿主照实回报 from_env / from_file，这里照实画，不让用户以为改了没用。
var modelFormOpen = false;

function modelFormHint(text, tone) {
  var hint = document.getElementById(MODEL_FORM_HINT_ID);
  if (!hint) return;
  hint.textContent = text;
  hint.dataset.tone = tone === 'error' ? 'error' : 'info';
}

function buildModelForm() {
  var form = document.createElement('div');
  form.id = MODEL_FORM_ID;
  form.className = 'cs-model-form';
  form.dataset.open = '0';

  // 左列是给人看的短名，右列的 id 与宿主那两个键名一一对应（见上面的 MODEL_ENV 一组）。
  var fields = [
    [MODEL_FORM_MODEL_ID, '模型', 'text', '服务端认的名字，例如 qwen2.5:7b、gpt-4o-mini'],
    [MODEL_FORM_URL_ID, '地址', 'text', '例如 http://127.0.0.1:11434/v1（本地服务多半要填）'],
    [MODEL_FORM_KEY_ID, '密钥', 'password', '留空 = 不动已经存过的那个']
  ];
  for (var i = 0; i < fields.length; i++) {
    var spec = fields[i];
    var row = document.createElement('div');
    row.className = 'cs-model-field';
    var label = document.createElement('label');
    label.className = 'cs-model-label';
    label.textContent = spec[1];
    label.setAttribute('for', spec[0]);
    var input = document.createElement('input');
    input.id = spec[0];
    input.type = spec[2];
    input.placeholder = spec[3];
    input.className = 'cs-model-input';
    input.setAttribute('autocomplete', 'off');
    input.addEventListener('keydown', function (event) {
      if (event.key === 'Enter') {
        event.preventDefault();
        saveSettings();
      }
    });
    row.appendChild(label);
    row.appendChild(input);
    form.appendChild(row);
  }

  var hint = document.createElement('div');
  hint.id = MODEL_FORM_HINT_ID;
  hint.className = 'cs-model-hint';
  hint.textContent = '正在读这份配置…';

  var path = document.createElement('div');
  path.id = MODEL_FORM_PATH_ID;
  path.className = 'cs-model-hint';

  var actions = document.createElement('div');
  actions.className = 'cs-model-actions';
  var save = document.createElement('button');
  save.id = MODEL_FORM_SAVE_ID;
  save.type = 'button';
  save.className = 'cs-model-btn';
  save.textContent = '保存';
  save.title = '存到这台机器上，下一句就用它';
  save.addEventListener('click', function () {
    saveSettings();
  });
  var clear = document.createElement('button');
  clear.id = MODEL_FORM_CLEAR_ID;
  clear.type = 'button';
  clear.className = 'cs-model-btn';
  clear.textContent = '清掉密钥';
  clear.title = '把已经存过的密钥删掉（本地模型服务多半不需要密钥）';
  clear.addEventListener('click', function () {
    saveSettings(true);
  });
  var cancel = document.createElement('button');
  cancel.id = MODEL_FORM_CANCEL_ID;
  cancel.type = 'button';
  cancel.className = 'cs-model-btn';
  cancel.textContent = '收起';
  cancel.addEventListener('click', function () {
    toggleModelForm(false);
  });
  actions.appendChild(save);
  actions.appendChild(clear);
  actions.appendChild(cancel);

  form.appendChild(hint);
  form.appendChild(actions);
  form.appendChild(path);
  return form;
}

function toggleModelForm(open) {
  var form = document.getElementById(MODEL_FORM_ID);
  var button = document.getElementById(MODEL_CONFIG_ID);
  if (!form) return;
  modelFormOpen = open === undefined ? !modelFormOpen : !!open;
  form.dataset.open = modelFormOpen ? '1' : '0';
  if (button) button.setAttribute('aria-expanded', modelFormOpen ? 'true' : 'false');
  // 每次打开都重读：这份配置在别的窗口里可能刚被改过，也可能宿主刚重启。
  if (modelFormOpen) loadSettings();
}

function loadSettings() {
  if (!modelFormOpen) return Promise.resolve(null);
  modelFormHint('正在读这份配置…');
  return Promise.resolve(bridge.request('agent/settings')).then(
    function (response) {
      if (!response || response.ok !== true) {
        modelFormHint('读不到这份配置: ' + message((response && response.error) || {}), 'error');
        return null;
      }
      var result = response.result || {};
      paintSettings(result);
      return result;
    },
    function (err) {
      modelFormHint('读不到这份配置: ' + message(err), 'error');
      return null;
    }
  );
}

// extra 是"这一趟顺带要说的一句"（比如有几段对话还没换过来），接在常规说明后面。
function paintSettings(result, extra) {
  var model = document.getElementById(MODEL_FORM_MODEL_ID);
  var url = document.getElementById(MODEL_FORM_URL_ID);
  var key = document.getElementById(MODEL_FORM_KEY_ID);
  var path = document.getElementById(MODEL_FORM_PATH_ID);
  var saved = result.saved || {};
  var fromEnv = result.from_env || [];
  var fromFile = result.from_file || [];

  // 生效值优先：它是"宿主真正拿在手里的那个"，而 saved 只是文件里存的。
  if (model) model.value = result.model || saved.model || '';
  if (url) url.value = result.base_url || saved.base_url || '';
  if (key) key.value = '';

  var notes = [];
  if (result.configured) {
    notes.push('当前用它: ' + (result.model || '(没名字)') + (result.base_url ? ' @ ' + result.base_url : ''));
  } else {
    notes.push('还没配好: ' + (result.error || '缺模型名'));
  }
  if (fromEnv.length) notes.push('环境变量已经给了 ' + fromEnv.join('、') + '，这几项在这儿改了不生效');
  if (fromFile.length) notes.push('这份文件正提供 ' + fromFile.join('、'));
  if (saved.has_key) notes.push('已存过密钥（不回显）');
  if (result.file_error) notes.push(result.file_error);
  if (extra) notes.push(extra);
  modelFormHint(notes.join('；'), result.configured ? 'info' : 'error');

  if (path) {
    path.textContent = result.path ? '存到 ' + result.path : '这个宿主没挂配置存储，只能靠环境变量给';
  }
}

// clearKey = true 表示"把已存的密钥删掉"（发空串）；否则密钥留空就当没打算动它 ——
// 只想改地址的人不该被迫把密钥再抄一遍。
function saveSettings(clearKey) {
  var model = document.getElementById(MODEL_FORM_MODEL_ID);
  var url = document.getElementById(MODEL_FORM_URL_ID);
  var key = document.getElementById(MODEL_FORM_KEY_ID);
  var payload = {};
  if (model) payload[MODEL_ENV] = model.value.trim();
  if (url) payload[BASE_URL_ENV] = url.value.trim();
  if (clearKey === true) payload[API_KEY_ENV] = '';
  else if (key && key.value.trim()) payload[API_KEY_ENV] = key.value.trim();

  modelFormHint('正在存…');
  return Promise.resolve(bridge.request('agent/settings', payload)).then(
    function (response) {
      if (!response || response.ok !== true) {
        modelFormHint('存不下: ' + message((response && response.error) || {}), 'error');
        return null;
      }
      var result = response.result || {};
      var extra = '';
      if (result.skipped && result.skipped.length) {
        extra = '有 ' + result.skipped.length + ' 段对话正在跑，它们这一轮结束后才用上新配置';
      }
      paintSettings(result, extra);
      if (result.configured) {
        // 下拉里的模型清单跟着换（地址变了，服务端能给的名字也可能变了）。
        loadModels();
        setStatus('模型配置已更新', 'info');
      } else {
        setStatus('模型配置已存，但还差模型名', 'error');
      }
      return result;
    },
    function (err) {
      modelFormHint('存不下: ' + message(err), 'error');
      return null;
    }
  );
}

// ---- 模型切换 ----------------------------------------------------------

function setModelHint(text) {
  var model = document.getElementById(MODEL_ID);
  if (!model) return;
  model.title = text;
}

// 下拉里 option 的值是"来源::模型名"，拆开要用；模型名本身含 :: 也没关系（只切第一个）。
function sourceRefOf(value) {
  var text = String(value || '');
  var index = text.indexOf(MODEL_SOURCE_SEP);
  return index < 0 ? MODEL_SOURCE_DEFAULT : text.slice(0, index);
}

function modelNameOf(value) {
  var text = String(value || '');
  var index = text.indexOf(MODEL_SOURCE_SEP);
  return index < 0 ? text : text.slice(index + MODEL_SOURCE_SEP.length);
}

function modelRefOf(source, name) {
  return (source || MODEL_SOURCE_DEFAULT) + MODEL_SOURCE_SEP + String(name || '');
}

// 铺模型下拉。groups 是宿主按来源分好的组（[{source,label,models,error}]）：本机 Ollama 一组、
// DeepSeek 一组，用 optgroup 隔开 —— 两串模型名混在一列里，用户分不清哪个是本机的、哪个要花钱。
// 拉不到清单的那一组照样画出来（标题上写着原因）：从下拉里悄悄抹掉，用户只会以为自己刚配的
// 那一家没生效，然后反复改它。
function fillModels(groups, current, currentSource) {
  var model = document.getElementById(MODEL_ID);
  if (!model) return;
  var list = groups || [];
  model.textContent = '';
  for (var i = 0; i < list.length; i++) {
    var group = list[i] || {};
    var names = group.models || [];
    if (!names.length && !group.error) continue;
    var bucket = document.createElement('optgroup');
    bucket.label = String(group.label || group.source || '模型');
    if (group.error) bucket.title = '这一家没给模型列表: ' + group.error;
    for (var j = 0; j < names.length; j++) {
      var option = document.createElement('option');
      option.value = modelRefOf(group.source, names[j]);
      option.textContent = String(names[j]);
      bucket.appendChild(option);
    }
    model.appendChild(bucket);
  }

  var wanted = current ? modelRefOf(currentSource, current) : '';
  if (wanted) model.value = wanted;
  if (!model.value && model.options.length > 0) {
    // 当前那个不在任何一组里（那家清单拉不到、或它已被改名删掉）：退回第一个，
    // 别让下拉空着 —— 空着比显示一个"不是当前值"的值更让人糊涂。
    model.value = model.options[0].value;
  }
  STATE.modelRef = model.value || '';
  STATE.model = model.value ? modelNameOf(model.value) : String(current || '');
  refreshModelEnabled();
}

function loadModels() {
  return Promise.resolve(bridge.request('agent/models')).then(
    function (response) {
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        fillModels([], '');
        setModelHint('读模型列表失败: ' + (error.message || '未知错误'));
        return null;
      }
      var result = response.result || {};
      var groups = result.groups;
      if (!groups || !groups.length) {
        // 老宿主（或一条清单都没拿到）没有 groups：退回扁平那份，别让下拉空着。
        // error / origin 也要一起搬：这是主源那一组，顶端那三个字段说的就是它 —— 漏掉 error
        // 的话，"服务端为什么没给模型列表"那句提示就再也不会出现了。
        groups = [
          {
            source: MODEL_SOURCE_DEFAULT,
            label: '',
            models: result.models,
            origin: result.source,
            error: result.error
          }
        ];
      }
      fillModels(groups, result.current, result.current_source);

      var broken = [];
      for (var i = 0; i < groups.length; i++) {
        var group = groups[i] || {};
        if (!group.error) continue;
        // 名字 + 原因都放上：只说"某家没给列表"，用户还是不知道该去改地址、改密钥还是重启。
        // 名字优先用 label（宿主给的是地址的 host，比如 DeepSeek 或 127.0.0.1:11434）；
        // 老宿主没有 label，就退回它自己的源名（主源那个恒叫 default）。
        broken.push((group.label || group.source || '有一家') + '（' + group.error + '）');
      }
      if (result.extra_error) {
        setModelHint('settings.json 里那几条额外的模型源读不了：' + result.extra_error);
      } else if (broken.length) {
        // 某一家拿不到清单：说清是哪家、为什么，别让人以为模型就这些
        setModelHint(broken.join('、') + ' 没给模型列表；下拉里只有能拿到的那几家');
      } else {
        setModelHint('切换这个宿主用的模型（已有会话的下一轮也会跟着换）');
      }
      return result;
    },
    function (err) {
      fillModels([], '');
      setModelHint('读模型列表失败: ' + message(err));
      return null;
    }
  );
}

// ---- 智能体切换 --------------------------------------------------------
//
// 与模型那节几乎是同一套写法（宿主那两个方法也是照 agent/models、agent/model 的形状来的），
// 差别只有一处：切的只是人设里的角色段，正在飞的那一轮不受影响 —— 换完下一次提问就按新角色
// 答，不必等这一轮结束（见 lib/comfy_studio/server.py 的 agent_agent）。
//
// 读不了的文件也画进下拉（灰掉、原因写在 title 里）：从列表里悄悄抹掉，用户只会以为自己那份
// 文件没生效，然后反复改它。

function setAgentHint(text) {
  var agent = document.getElementById(AGENT_ID);
  if (!agent) return;
  agent.title = text;
}

// 下拉的 tooltip：正常时说清换的是什么，出毛病时先报毛病。
function agentHint(result) {
  var parts = [];
  if (result.missing) parts.push(String(result.missing));
  if (result.error) parts.push('智能体目录读不了（' + result.error + '）；这里只剩内置与随包带的几个');
  var broken = result.problems || [];
  if (broken.length) {
    var files = [];
    for (var i = 0; i < broken.length; i++) files.push(String((broken[i] || {}).file || ''));
    parts.push('这几份文件读不了，没进清单：' + files.join('、'));
  }
  if (parts.length === 0) parts.push('换一个智能体（只换人设，工具和历史都不动；下一次提问生效）');
  if (result.dir) parts.push('自己写的智能体放这里：' + result.dir);
  return parts.join('；');
}

function fillAgents(agents, current, problems) {
  var agent = document.getElementById(AGENT_ID);
  if (!agent) return;
  var list = agents || [];
  agent.textContent = '';
  for (var i = 0; i < list.length; i++) {
    var item = list[i] || {};
    var option = document.createElement('option');
    option.value = String(item.id || '');
    option.textContent = item.name ? String(item.name) : String(item.id || '');
    if (item.summary) option.title = String(item.summary);
    agent.appendChild(option);
  }
  var broken = problems || [];
  for (var j = 0; j < broken.length; j++) {
    var bad = broken[j] || {};
    var skipped = document.createElement('option');
    skipped.value = '';
    skipped.textContent = String(bad.file || '（没文件名）') + '（读不了）';
    skipped.title = String(bad.error || '');
    skipped.disabled = true;
    agent.appendChild(skipped);
  }
  var wanted = String(current || '');
  agent.value = wanted;
  if (agent.value !== wanted) {
    // 选中的那一项不在清单里（文件被删、改名或者改坏）：还留着上一个选中项，等于假装它还在。
    agent.selectedIndex = -1;
  }
  STATE.agent = wanted;
  refreshAgentEnabled();
}

// ---- 一键跑 skill --------------------------------------------------------
//
// 为什么默认参数由 skill 自己说、面板不替它编：一套工作流里哪个节点吃哪个值，只有 skill
// 文件自己知道（params 里写着 node/field，见引擎侧 skills/params.py）。面板随手填一个
// "看着差不多"的值，跑出来不会报错，只会是另一套东西 —— 那种错没人查得出来。
//
// 所以这里的"一键"只有一个成立条件：**每个必填参数都有默认值**。有必填参数没默认值的，
// 就停下来说清是哪个参数，让用户去对话里让 agent 跑（它会先查模型列表再问用户要什么）。

function skillOf(id) {
  var list = STATE.skills || [];
  for (var i = 0; i < list.length; i++) {
    if (String((list[i] || {}).id || '') === String(id)) return list[i];
  }
  return null;
}

// 一键跑要带的那份参数：只取 skill 自己声明了默认值的那些；必填又没默认值的一个都不替它
// 编，只把名字列出来（见上面那一段）。
function skillDefaults(entry) {
  var params = (entry && entry.params) || [];
  var values = {};
  var missing = [];
  for (var i = 0; i < params.length; i++) {
    var param = params[i] || {};
    var name = String(param.name || '');
    if (name === '') continue;
    if (param.hasDefault === true) values[name] = param.default;
    else if (param.required === true) missing.push(name);
  }
  return { values: values, missing: missing };
}

// 下拉里那条 tooltip：这是干嘛的、要什么参数。参数表是引擎给的，这里只念不猜。
function skillHint(entry) {
  var parts = [];
  if (entry.description) parts.push(String(entry.description));
  var tags = entry.tags || [];
  if (tags.length) parts.push('标签: ' + tags.join('、'));
  var params = entry.params || [];
  var names = [];
  for (var i = 0; i < params.length; i++) {
    var param = params[i] || {};
    names.push(String(param.name || '') + (param.hasDefault === true ? '（有默认值）' : '（必填）'));
  }
  parts.push(names.length ? '参数: ' + names.join('、') : '没有参数');
  return parts.join('；');
}

function setSkillHint(text) {
  var select = document.getElementById(SKILL_ID);
  if (!select) return;
  select.title =
    text || '选一个 skill，按「跑一遍」按它自己声明的默认参数跑，跑出来的图画在这一页里';
}

// 判"有 skill"看的是 STATE.skills，不是下拉里的 option 条数：目录为空时下拉里那一条是
// 占位文案（见 fillSkills），它也算一个 option，拿它当判据会让按钮亮着但按下去没得跑。
//
// 正在跑的时候：下拉灭掉（跑着改选择没有意义），但"跑一遍"留着按得动 —— 跑一套工作流
// 要几分钟，灭掉的按钮不会解释自己为什么灭，而按一下能听到一句"上一个还在跑"（见 runSkill）。
function refreshSkillEnabled() {
  var select = document.getElementById(SKILL_ID);
  var run = document.getElementById(SKILL_RUN_ID);
  var ready = (STATE.skills || []).length > 0 && !!select;
  var running = STATE.skillRunning !== '';
  if (select) {
    select.disabled = !ready || running;
    select.style.opacity = !ready || running ? '0.5' : '1';
  }
  if (run) {
    run.disabled = !ready;
    run.style.opacity = ready ? '1' : '0.5';
  }
}

function fillSkills(skills) {
  var select = document.getElementById(SKILL_ID);
  if (!select) return;
  var list = skills || [];
  var wanted = STATE.skill;
  select.textContent = '';
  for (var i = 0; i < list.length; i++) {
    var entry = list[i] || {};
    var option = document.createElement('option');
    option.value = String(entry.id || '');
    option.textContent = String(entry.title || entry.id || '');
    option.title = skillHint(entry);
    select.appendChild(option);
  }
  if (select.options.length === 0) {
    // 空着不解释，用户只会以为面板坏了：skill 目录在引擎侧（MCP），引擎没起来就是空的。
    var none = document.createElement('option');
    none.value = '';
    none.textContent = '（引擎没报出 skill）';
    none.disabled = true;
    select.appendChild(none);
  } else if (wanted && skillOf(wanted)) {
    // 上一次选的那个还在清单里就接着选中：刷新一次就跳回第一个，等于替用户改了选择。
    select.value = String(wanted);
  }
  STATE.skills = list;
  STATE.skill = select.value || '';
  refreshSkillEnabled();
}

function loadSkills() {
  return Promise.resolve(bridge.request('skills/list')).then(
    function (response) {
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        fillSkills([]);
        setSkillHint('读 skill 目录失败: ' + (error.message || '未知错误'));
        return null;
      }
      var result = response.result || {};
      fillSkills(result.skills);
      setSkillHint('');
      return result;
    },
    function (err) {
      fillSkills([]);
      setSkillHint('读 skill 目录失败: ' + message(err));
      return null;
    }
  );
}

// 跑 skill 的那张卡：标题 + 状态 + 结果区。跟工具卡一个形状（同一个 appendNode 插进日志），
// 这样"正在跑"和"跑完了"是同一张卡的前后两态，而不是两行。
function skillCard(entry) {
  var card = makeRow('skill');
  card.setAttribute('data-skill', String(entry.id || ''));
  card.setAttribute('data-state', 'running');
  var head = document.createElement('div');
  head.className = 'cs-skill-head';
  var title = document.createElement('span');
  title.className = 'cs-skill-title';
  title.textContent = '技能 ' + String(entry.title || entry.id || '') + '（' + String(entry.id || '') + '）';
  head.appendChild(title);
  var state = document.createElement('span');
  state.className = 'cs-skill-state';
  state.textContent = '运行中…';
  head.appendChild(state);
  var body = document.createElement('div');
  body.className = 'cs-skill-body';
  card.appendChild(head);
  card.appendChild(body);
  card.csState = state;
  card.csBody = body;
  return card;
}

// 一张输出图。地址与文件名都是引擎说的（宿主原样转回来，见 lib/comfy_studio/skills/catalog.py）：
// 面板不自己拼 /view 的地址，也不去猜文件落在哪个目录。
function paintSkillImage(body, image) {
  var url = String((image && image.url) || '');
  var filename = String((image && image.filename) || '');
  if (url === '') {
    // 引擎报了图却没有地址：明说这一条画不出来，比留个空位强（空位看着像图还在路上）。
    var skipped = document.createElement('div');
    skipped.className = 'cs-skill-image-note';
    skipped.textContent = '引擎报了一张图但没有地址: ' + (filename || '（也没文件名）');
    body.appendChild(skipped);
    return;
  }
  var img = document.createElement('img');
  img.className = 'cs-skill-image';
  img.src = url;
  img.alt = filename || 'skill 输出图';
  img.loading = 'lazy';
  img.addEventListener('error', function (event) {
    // 加载不出来（引擎的 /view 挂了、或那文件已经被清掉）时别留一个空框：换成一行字并把
    // 地址写上，用户能自己去查是引擎没起来还是文件没了。
    var note = document.createElement('div');
    note.className = 'cs-skill-image-note';
    note.textContent = '这张图加载不出来: ' + url;
    var node = event.target;
    if (node && node.parentNode) node.parentNode.replaceChild(note, node);
  });
  body.appendChild(img);
  if (filename !== '') {
    var caption = document.createElement('div');
    caption.className = 'cs-skill-caption';
    caption.textContent = filename;
    body.appendChild(caption);
  }
}

// 一次 skill 跑完之后画它。三种结果都要说清是哪一种：引擎**执行**失败（显存不够、模型名
// 写错，落在 isError 上）、跑成了但没有图、跑成了有图 —— 尤其"没有图"不能被画成一片空白。
function paintSkillRun(card, id, run) {
  var result = run || {};
  if (result.isError === true) {
    card.setAttribute('data-state', 'error');
    card.csState.textContent = '失败';
    card.csBody.appendChild(makeBlock('引擎说', String(result.text || '（没有说明）'), RESULT_FOLD));
    setStatus('skill ' + id + ' 失败（原因在那张卡里）', 'error');
    return;
  }
  var data = result.data || {};
  var images = data.images || [];
  card.setAttribute('data-state', 'done');
  if (images.length > 0) {
    for (var i = 0; i < images.length; i++) paintSkillImage(card.csBody, images[i] || {});
    card.csState.textContent = '完成 · ' + images.length + ' 张图';
    setStatus('skill ' + id + ' 跑完了：' + images.length + ' 张图（在这一页里）');
    return;
  }
  // 走得通但没有图：把引擎的原文照放，别让人以为跑空了。
  card.csState.textContent = '完成（没有图片输出）';
  card.csBody.appendChild(makeBlock('结果', String(result.text || '（引擎没有返回内容）'), RESULT_FOLD));
  setStatus('skill ' + id + ' 跑完了，但引擎没报出图片输出（结果在那张卡里）');
}

function runSkill(id) {
  var skillId = String(id || '');
  if (STATE.skillRunning !== '') {
    // 一次只跑一个：引擎跑一套工作流要占住显存，叠着跑两边都慢，而界面上只能画一条"运行中"。
    setStatus('上一个 skill（' + STATE.skillRunning + '）还在跑，等它完再按', 'error');
    return null;
  }
  var entry = skillOf(skillId);
  if (!entry) {
    setStatus('先在上面选一个技能', 'error');
    return null;
  }
  var args = skillDefaults(entry);
  if (args.missing.length > 0) {
    setStatus(
      'skill ' + skillId + ' 的必填参数 ' + args.missing.join('、') +
        ' 没有默认值：面板一键跑不了它，在对话里让 agent 跑（它会先查模型列表再问你要什么）',
      'error'
    );
    return null;
  }
  // 卡先摆上再发请求：跑一套工作流可能要几分钟，这期间界面上得有东西说明"在跑哪个"。
  switchView('chat');
  var card = skillCard(entry);
  appendNode(card);
  STATE.skillRunning = skillId;
  refreshSkillEnabled();
  setStatus('正在跑 skill ' + skillId + '…');

  var settle = function () {
    STATE.skillRunning = '';
    refreshSkillEnabled();
  };
  var failed = function (reason) {
    card.setAttribute('data-state', 'error');
    card.csState.textContent = '失败';
    card.csBody.appendChild(makeBlock('宿主说', String(reason), RESULT_FOLD));
    setStatus('skill ' + skillId + ' 没跑起来（原因在那张卡里）', 'error');
    return null;
  };
  return Promise.resolve(
    bridge.request('skills/run', { skill_id: skillId, params: args.values })
  ).then(
    function (response) {
      if (!response || response.ok !== true) {
        // 走到这里的是**协议层**的问题（引擎没这把工具、目录里没这个 id）：原因整段放进卡里。
        var error = (response && response.error) || {};
        return failed(error.message || '未知错误');
      }
      paintSkillRun(card, skillId, response.result);
      return response.result;
    },
    function (err) {
      return failed(message(err));
    }
  ).then(settle, settle);
}

// ---- 一键跑渲染目标 ------------------------------------------------------
//
// 渲染目标是引擎侧那 12 张**生产工作流**（角色定妆板、分镜首帧、视频试片、主题曲、放大…，
// 见引擎 skills/render.py 的 RENDER_TARGETS）。它与 skill 是同一件事的两层：skill 是"参数化
// 工作流"，渲染目标是"这台机器上配好的、带用途的那几张"。
//
// 与技能那一行有一处**必须不同**：技能的一键靠"每个必填参数都有默认值"，而渲染目标的必填参数
// （prompt / caption / lyrics / file）就是**内容本身**，引擎没给默认值可编 —— 面板替它编一句
// 提示词，跑出来不会报错，只会是另一张图，那种错没人查得出来。所以这一行让用户当场填必填参数：
// 只有必填且没默认值的才建输入框，可选参数（宽高 / seed / steps / frame_rate）一律用图上原值。
//
// 参考图（引擎报 referenceImages=true 的那几只，即视频目标）要的是**本机文件路径**，不是工作流
// 参数，所以单独一个输入框、多张用分号隔开；留空就是不用图（t2v）。

function renderOf(id) {
  var list = STATE.renders || [];
  for (var i = 0; i < list.length; i++) {
    if (String((list[i] || {}).id || '') === String(id)) return list[i];
  }
  return null;
}

function renderParam(entry, name) {
  var params = (entry && entry.params) || [];
  for (var i = 0; i < params.length; i++) {
    if (String((params[i] || {}).name || '') === String(name)) return params[i];
  }
  return null;
}

// 必填又没默认值的参数名：面板为它们各建一个输入框。判据与技能那边同一套字段（引擎与宿主共用
// 一份参数形状，见引擎 skills/params.py 的 param_entry），不另立一套。
function renderRequired(entry) {
  var params = (entry && entry.params) || [];
  var names = [];
  for (var i = 0; i < params.length; i++) {
    var param = params[i] || {};
    var name = String(param.name || '');
    if (name === '' || param.required !== true || param.hasDefault === true) continue;
    names.push(name);
  }
  return names;
}

// 下拉里那条 tooltip：这是干嘛的、工作流在不在、要填什么。文件名与参数表都是引擎给的（宿主原样
// 转回来），这里只念不猜。
function renderHint(entry) {
  var parts = [];
  if (entry.description) parts.push(String(entry.description));
  var tags = entry.tags || [];
  if (tags.length) parts.push('标签: ' + tags.join('、'));
  // 文件缺了要说在最前面：列出来不等于跑得起来（引擎照实报 fileExists，见宿主 renders/catalog.py）。
  parts.push(
    entry.fileExists === false
      ? '工作流文件没找到: ' + String(entry.file || '')
      : '工作流: ' + String(entry.file || '')
  );
  var names = renderRequired(entry);
  parts.push(names.length ? '要填: ' + names.join('、') : '必填参数都有默认值');
  if (entry.referenceImages === true) parts.push('可以给参考图（本机图片路径，不给就是不用图）');
  return parts.join('；');
}

function setRenderHint(text) {
  var select = document.getElementById(RENDER_ID);
  if (!select) return;
  if (text) {
    select.title = String(text);
    return;
  }
  // 目录这一句是引擎如实报出来的（见宿主 renders/catalog.py 的 note 与 workflows_dir）：目标表是
  // 代码里定死的，所以"目录整个不在"时下拉里照样有 12 条 —— 那就得让人看得见图该去哪儿找。
  var parts = ['选一个渲染目标，填好必填参数再按「跑一遍」'];
  if (STATE.rendersDir) parts.push('工作流目录: ' + STATE.rendersDir);
  if (STATE.rendersNote) parts.push(String(STATE.rendersNote));
  select.title = parts.join('；');
}

// 与技能那一份同一个口径：判"有目标"看 STATE.renders，不看 option 条数（空目录时下拉里那条是
// 占位文案）；跑着的时候下拉灭掉、按钮留着按得动（按一下会听到"上一个还在跑"，见 runRender）。
function refreshRenderEnabled() {
  var select = document.getElementById(RENDER_ID);
  var run = document.getElementById(RENDER_RUN_ID);
  var ready = (STATE.renders || []).length > 0 && !!select;
  var running = STATE.renderRunning !== '';
  if (select) {
    select.disabled = !ready || running;
    select.style.opacity = !ready || running ? '0.5' : '1';
  }
  if (run) {
    run.disabled = !ready;
    run.style.opacity = ready ? '1' : '0.5';
  }
}

// 渲染那一行：外壳自己一列（一行下拉 + 一块参数区），下拉样式与技能共用一份（由调用方传进来，
// 不各写一份内联样式）。
function buildRenderRow(selectCss) {
  var outer = document.createElement('div');
  outer.style.cssText = 'display:flex;flex-direction:column;padding:0 0 8px;';

  var row = document.createElement('div');
  row.style.cssText = 'display:flex;align-items:center;gap:6px;padding:0 12px;';

  var label = document.createElement('label');
  label.textContent = '渲染';
  label.setAttribute('for', RENDER_ID);
  label.style.cssText = 'color:' + MUTED + ';font-size:11px;white-space:nowrap;';

  var select = document.createElement('select');
  select.id = RENDER_ID;
  select.disabled = true;
  select.title = '正在读引擎的渲染目标…';
  select.style.cssText = selectCss;
  select.addEventListener('change', function () {
    // 换目标要连着换参数表：必填的参数名每个目标都不一样（提示词 / 歌词 / 片子名），
    // 留着上一条的输入框只会让人填错位置。
    STATE.render = select.value;
    fillRenderArgs(renderOf(select.value));
  });

  var run = document.createElement('button');
  run.id = RENDER_RUN_ID;
  run.type = 'button';
  run.textContent = '跑一遍';
  run.disabled = true;
  run.title = '按上面填的参数跑这个渲染目标，产物画在这一页里';
  run.style.cssText =
    'border:1px solid ' + BORDER + ';border-radius:4px;background:transparent;color:' + MUTED + ';' +
    'cursor:pointer;font-size:11px;padding:2px 6px;white-space:nowrap;';
  run.addEventListener('click', function () {
    runRender(select.value);
  });

  row.appendChild(label);
  row.appendChild(select);
  row.appendChild(run);

  var args = document.createElement('div');
  args.id = RENDER_ARGS_ID;
  args.style.cssText = 'display:none;flex-direction:column;gap:6px;padding:6px 12px 0;';

  outer.appendChild(row);
  outer.appendChild(args);
  return outer;
}

function renderInputCss() {
  return (
    'flex:1;min-width:0;box-sizing:border-box;padding:4px 6px;border-radius:4px;font-size:11px;' +
    'border:1px solid ' + BORDER + ';background:' + INPUT_BG + ';color:' + FG + ';font:inherit;'
  );
}

// 一个必填参数的输入框。类型一律 text：必填的这几个本来就是文本（提示词 / 歌词 / 要放大的片子名），
// 而数字那些都在可选参数里、根本不摆出来。值原样发出去 ——"这串字算不算数"由引擎的组装期判，
// 面板不在这里另立一套校验（见引擎 skills/render.py）。
function renderArgRow(param, name) {
  var row = document.createElement('div');
  row.style.cssText = 'display:flex;align-items:center;gap:6px;';

  var label = document.createElement('label');
  label.textContent = name;
  label.setAttribute('for', RENDER_ARG_PREFIX + name);
  label.style.cssText = 'color:' + MUTED + ';font-size:11px;white-space:nowrap;min-width:60px;';

  var input = document.createElement('input');
  input.id = RENDER_ARG_PREFIX + name;
  input.type = 'text';
  input.placeholder = String((param && param.description) || '必填');
  input.title = String((param && param.description) || '');
  input.style.cssText = renderInputCss();

  row.appendChild(label);
  row.appendChild(input);
  return row;
}

// 参考图那一行：视频目标要的首帧 / 尾帧或参考图。路径是**这台机器上的**文件，引擎会先搬进它自己的
// input/（见引擎 skills/render.py 的 INPUT_IMAGE_SUBDIR），所以这里只收路径、不传内容。
function renderImagesRow() {
  var row = document.createElement('div');
  row.style.cssText = 'display:flex;align-items:center;gap:6px;';

  var label = document.createElement('label');
  label.textContent = '参考图';
  label.setAttribute('for', RENDER_IMAGES_ID);
  label.style.cssText = 'color:' + MUTED + ';font-size:11px;white-space:nowrap;min-width:60px;';

  var input = document.createElement('input');
  input.id = RENDER_IMAGES_ID;
  input.type = 'text';
  input.placeholder = '本机图片路径，多张用 ; 隔开（首帧、尾帧 / 参考图1、参考图2…）；留空=不用图';
  input.title = '这台机器上的图片文件，引擎按顺序搬进自己的 input/：图片1、图片2…';
  input.style.cssText = renderInputCss();

  row.appendChild(label);
  row.appendChild(input);
  return row;
}

// 参数区按选中的目标重建：**只建必填且没默认值的那些**。一个输入框都没有时整块收起来 ——
// 留一片空白只会让人以为漏了东西。切目标会丢上一轮填的字，这是故意的：每个目标的必填项不同，
// 留着上一份就是让人把"上一张图的提示词"填进这首歌里。
function fillRenderArgs(entry) {
  var box = document.getElementById(RENDER_ARGS_ID);
  if (!box) return;
  box.textContent = '';
  var names = renderRequired(entry);
  for (var i = 0; i < names.length; i++) {
    box.appendChild(renderArgRow(renderParam(entry, names[i]), names[i]));
  }
  if (entry && entry.referenceImages === true) box.appendChild(renderImagesRow());
  box.style.display = box.childNodes.length > 0 ? 'flex' : 'none';
}

// 面板要发出去的那份参数：**只发必填的那些**（其余用图上原值，等于没填）。空的必填项原地点名，
// 不替它编、也不静默塞一个空串进去。
function renderArgValues(entry) {
  var names = renderRequired(entry);
  var values = {};
  var missing = [];
  for (var i = 0; i < names.length; i++) {
    var input = document.getElementById(RENDER_ARG_PREFIX + names[i]);
    var value = input ? String(input.value || '').trim() : '';
    if (value === '') missing.push(names[i]);
    else values[names[i]] = value;
  }
  return { values: values, missing: missing };
}

// 参考图那一串：分号 / 换行分隔的本机路径。空项直接丢掉（敲了两个分号不等于两张图），全空就是
// "不用参考图"。
function renderImages() {
  var input = document.getElementById(RENDER_IMAGES_ID);
  if (!input) return [];
  var raw = String(input.value || '').split(/[;\\n]/);
  var out = [];
  for (var i = 0; i < raw.length; i++) {
    var path = raw[i].trim();
    if (path !== '') out.push(path);
  }
  return out;
}

function fillRenders(payload) {
  var select = document.getElementById(RENDER_ID);
  if (!select) return;
  var data = payload || {};
  var list = data.targets || [];
  var wanted = STATE.render;
  select.textContent = '';
  for (var i = 0; i < list.length; i++) {
    var entry = list[i] || {};
    var option = document.createElement('option');
    option.value = String(entry.id || '');
    // 缺文件的那几条在下拉里就标出来：点下去才发现跑不起来，比提前说一句坏得多。
    option.textContent =
      String(entry.title || entry.id || '') +
      (entry.fileExists === false ? '（工作流文件没找到）' : '');
    option.title = renderHint(entry);
    select.appendChild(option);
  }
  if (select.options.length === 0) {
    // 空着不解释，用户只会以为面板坏了：目标表在引擎侧（MCP），引擎没起来就是空的。
    var none = document.createElement('option');
    none.value = '';
    none.textContent = '（引擎没报出渲染目标）';
    none.disabled = true;
    select.appendChild(none);
  } else if (wanted && renderOf(wanted)) {
    // 上一次选的那个还在清单里就接着选中（与技能那份同一个理由：别替用户改选择）。
    select.value = String(wanted);
  }
  STATE.renders = list;
  STATE.render = select.value || '';
  STATE.rendersDir = String(data.workflows_dir || '');
  STATE.rendersNote = data.note ? String(data.note) : '';
  refreshRenderEnabled();
  fillRenderArgs(renderOf(STATE.render));
}

function loadRenders() {
  return Promise.resolve(bridge.request('renders/list')).then(
    function (response) {
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        fillRenders({ targets: [] });
        setRenderHint('读渲染目标失败: ' + (error.message || '未知错误'));
        return null;
      }
      fillRenders(response.result || {});
      setRenderHint('');
      return response.result;
    },
    function (err) {
      fillRenders({ targets: [] });
      setRenderHint('读渲染目标失败: ' + message(err));
      return null;
    }
  );
}

// 跑渲染的那张卡：与技能卡同一个形状（同一批 class 与 CSS），这样"正在跑"和"跑完了"是同一张卡的
// 前后两态，而不是两行。
function renderCard(entry) {
  var card = makeRow('render');
  card.setAttribute('data-render', String(entry.id || ''));
  card.setAttribute('data-state', 'running');
  var head = document.createElement('div');
  head.className = 'cs-skill-head';
  var title = document.createElement('span');
  title.className = 'cs-skill-title';
  title.textContent = '渲染 ' + String(entry.title || entry.id || '') + '（' + String(entry.id || '') + '）';
  head.appendChild(title);
  var state = document.createElement('span');
  state.className = 'cs-skill-state';
  state.textContent = '运行中…';
  head.appendChild(state);
  var body = document.createElement('div');
  body.className = 'cs-skill-body';
  card.appendChild(head);
  card.appendChild(body);
  card.csState = state;
  card.csBody = body;
  return card;
}

// 产物**不都是图**：视频目标出 mp4、主题曲出 flac，拿 <img> 去装它们只会得到"这张图加载不出来"。
// 按后缀挑标签：图走 paintSkillImage（那边已经处理好"没地址"与"加载不出来"两种坏情况），视频用
// <video>，其余（音频等）只把地址与文件名写上 —— 面板不假装自己什么都能放。
var RENDER_IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp'];
var RENDER_VIDEO_EXTS = ['mp4', 'webm', 'mov', 'mkv'];

// 一个产物的后缀（小写，不含点）。名字是引擎给的（它落在 output/ 里的文件名），面板不自己造。
function mediaExt(media) {
  var filename = String((media && media.filename) || '');
  var dot = filename.lastIndexOf('.');
  return dot < 0 ? '' : filename.slice(dot + 1).toLowerCase();
}

// 换掉一个加载不出来的产物：留个空框看着像"还在路上"，换成一行字并写上地址，用户能自己去查是引擎
// 没起来还是那个文件已经被清掉。
function paintMediaFailure(node, note, url) {
  var line = document.createElement('div');
  line.className = 'cs-skill-image-note';
  line.textContent = note + ': ' + url;
  if (node && node.parentNode) node.parentNode.replaceChild(line, node);
}

function paintRenderMedia(body, media) {
  var item = media || {};
  var url = String(item.url || '');
  var filename = String(item.filename || '');
  var ext = mediaExt(item);
  if (RENDER_IMAGE_EXTS.indexOf(ext) >= 0 || (ext === '' && url !== '')) {
    // 后缀认不出但给了地址（引擎那边形状变过）：按图试一次，比什么都不画强。
    paintSkillImage(body, item);
    return;
  }
  if (url === '') {
    var skipped = document.createElement('div');
    skipped.className = 'cs-skill-image-note';
    skipped.textContent = '引擎报了一个产物但没有地址: ' + (filename || '（也没文件名）');
    body.appendChild(skipped);
    return;
  }
  if (RENDER_VIDEO_EXTS.indexOf(ext) >= 0) {
    var video = document.createElement('video');
    video.className = 'cs-skill-image';
    video.src = url;
    video.controls = true;
    video.preload = 'metadata';
    video.setAttribute('data-media', 'video');
    video.addEventListener('error', function (event) {
      paintMediaFailure(event.target, '这段视频加载不出来', url);
    });
    body.appendChild(video);
  } else {
    // 音频之类：画不了就不硬画（浏览器对 flac 的支持看机器），把地址与文件名给足。
    var line = document.createElement('div');
    line.className = 'cs-skill-caption';
    line.textContent = '产物（这一页放不了）: ' + url;
    body.appendChild(line);
  }
  if (filename !== '') {
    var caption = document.createElement('div');
    caption.className = 'cs-skill-caption';
    caption.textContent = filename;
    body.appendChild(caption);
  }
}

// 一次渲染跑完之后画它。跟技能那边一样把三种结果分开说：引擎**执行**失败（显存不够、工作流里那个
// 模型没装）、跑成了但没有产物、跑成了有产物。渲染比 skill 多两样要如实带出来：notes（组装期的
// 让步 —— 时长按帧数折了、接的是外部组）与 saved（指定了输出目录时落盘的文件）。
function paintRenderRun(card, id, run) {
  var result = run || {};
  if (result.isError === true) {
    card.setAttribute('data-state', 'error');
    card.csState.textContent = '失败';
    card.csBody.appendChild(makeBlock('引擎说', String(result.text || '（没有说明）'), RESULT_FOLD));
    setStatus('渲染 ' + id + ' 失败（原因在那张卡里）', 'error');
    return;
  }
  var data = result.data || {};
  // 组装期让步了就得说：没这句话，用户看到的时长 / 接法与工作流图上写的不一样，会以为哪里算错了。
  var notes = data.notes || [];
  if (notes.length > 0) {
    card.csBody.appendChild(makeBlock('这次组装改了什么', notes.join('\\n'), RESULT_FOLD));
  }
  var media = data.images || [];
  var saved = data.saved || [];
  card.setAttribute('data-state', 'done');
  if (media.length > 0) {
    for (var i = 0; i < media.length; i++) paintRenderMedia(card.csBody, media[i] || {});
    card.csState.textContent = '完成 · ' + media.length + ' 个产物';
    setStatus('渲染 ' + id + ' 跑完了：' + media.length + ' 个产物（在这一页里）');
  } else {
    // 走得通但没有产物：把引擎的原文照放，别让人以为跑空了。
    card.csState.textContent = '完成（没有产物）';
    card.csBody.appendChild(makeBlock('结果', String(result.text || '（引擎没有返回内容）'), RESULT_FOLD));
    setStatus('渲染 ' + id + ' 跑完了，但引擎没报出产物（结果在那张卡里）');
  }
  if (saved.length > 0) {
    card.csBody.appendChild(makeBlock('另存到', saved.join('\\n'), RESULT_FOLD));
  }
}

function runRender(id) {
  var targetId = String(id || '');
  if (STATE.renderRunning !== '') {
    // 一次只跑一个（与技能同一个理由）：渲染要占满显存好些分钟，叠着跑两边都慢。
    setStatus('上一个渲染（' + STATE.renderRunning + '）还在跑，等它完再按', 'error');
    return null;
  }
  var entry = renderOf(targetId);
  if (!entry) {
    setStatus('先在上面选一个渲染目标', 'error');
    return null;
  }
  if (entry.fileExists === false) {
    // 文件缺了这一趟必跑不起来（引擎那边也会报），但先把话说在前面：别让人等到模型加载完才看到。
    setStatus(
      '渲染 ' + targetId + ' 的工作流文件不在（' + String(entry.file || '') + '）：先把它放回引擎的工作流目录',
      'error'
    );
    return null;
  }
  var args = renderArgValues(entry);
  if (args.missing.length > 0) {
    // 面板不替它编内容（编出来的不报错，只是另一张图）：说清要填哪个，让人自己填。
    setStatus('渲染 ' + targetId + ' 要填 ' + args.missing.join('、') + '（填完再按「跑一遍」）', 'error');
    return null;
  }
  // 卡先摆上再发请求：渲染要跑几分钟到几十分钟，界面上得有东西说明"在跑哪个"。
  switchView('chat');
  var card = renderCard(entry);
  appendNode(card);
  STATE.renderRunning = targetId;
  refreshRenderEnabled();
  setStatus('正在渲染 ' + targetId + '…');

  var settle = function () {
    STATE.renderRunning = '';
    refreshRenderEnabled();
  };
  var failed = function (reason) {
    card.setAttribute('data-state', 'error');
    card.csState.textContent = '失败';
    card.csBody.appendChild(makeBlock('宿主说', String(reason), RESULT_FOLD));
    setStatus('渲染 ' + targetId + ' 没跑起来（原因在那张卡里）', 'error');
    return null;
  };
  var payload = { target_id: targetId, params: args.values };
  var images = renderImages();
  // 没给参考图就**不带这一项**：带一个空数组过去，读的人会以为"打算给图但没给"。
  if (images.length > 0) payload.images = images;
  return Promise.resolve(bridge.request('renders/run', payload)).then(
    function (response) {
      if (!response || response.ok !== true) {
        // 走到这里的是**协议层**的问题（引擎没这把工具、目录里没这个 id、参数形状不对）：
        // 原因整段放进卡里。
        var error = (response && response.error) || {};
        return failed(error.message || '未知错误');
      }
      paintRenderRun(card, targetId, response.result);
      return response.result;
    },
    function (err) {
      return failed(message(err));
    }
  ).then(settle, settle);
}

function loadAgents() {
  return Promise.resolve(bridge.request('agent/agents')).then(
    function (response) {
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        fillAgents([], STATE.agent, []);
        setAgentHint('读智能体清单失败: ' + (error.message || '未知错误'));
        return null;
      }
      var result = response.result || {};
      fillAgents(result.agents, result.current, result.problems);
      setAgentHint(agentHint(result));
      return result;
    },
    function (err) {
      fillAgents([], STATE.agent, []);
      setAgentHint('读智能体清单失败: ' + message(err));
      return null;
    }
  );
}

// ---- 上次的对话 ----------------------------------------------------------
//
// 面板和宿主是两份生命周期：这一屏一重载（切个画面、宿主重启过），抽屉里就空了，
// 可那段对话其实还在——宿主手里活着就还在内存里，宿主也重启过就还在 sessions/ 的
// 存档里（见 lib/comfy_studio/history.py）。所以开抽屉时问一次 agent/history，
// 用与实时事件同一套画法把自己补回来：用户看到的是"接着上次聊"，而不是一段空白。
// 只在**空抽屉**里补：已经有内容说明这一屏正在画这一轮，再补一遍就成了同一段话
// 说两遍。

function loadHistory(sessionId, options) {
  var id = sessionId || STATE.session;
  var heading = (options && options.heading) || '上次的对话（存在这台机器上）';
  var emptyNote = (options && options.emptyNote) || '';
  var log = document.getElementById(LOG_ID);
  if (!log || log.childNodes.length > 0 || STATE.busy) return null;
  // 这一趟的票：回来时票变了，说明用户已经换到别的段去了（clearLog 会把票翻新）。这时
  // **一句都不许画** —— 画下去就是两段话混在一屏上，而下拉说你在另一段上，最难查的那种。
  var ticket = STATE.paint || 0;
  return Promise.resolve(bridge.request('agent/history', { session_id: id })).then(
    function (response) {
      if ((STATE.paint || 0) !== ticket) return 0;
      if (!response || response.ok !== true) {
        // 取不回来就说一句。不说的话用户只看到一段空白，会以为对话被吞了；
        // 宿主没在运行时状态栏也在报同一件事，两处并不矛盾。
        var error = (response && response.error) || {};
        var line = makeRow('agent');
        line.textContent = '取不回上次的对话: ' + (error.message || '未知错误');
        appendNode(line);
        return 0;
      }
      // 换过来的这一段是空的时候也要把标题画上：用户刚点过来，得知道自己站在哪一段上。
      var painted = paintHistory(response.result || {}, heading, emptyNote !== '');
      if (painted === 0 && emptyNote !== '') {
        // 换过来的这一段是空的：留一句话，好过让人对着空抽屉猜"是不是没取到"。
        var note = makeRow('agent');
        note.textContent = emptyNote;
        appendNode(note);
      }
      return painted;
    },
    function () {
      // 传输层就没送到（宿主进程不在）：状态栏已经在报，这里不再多插一行。
      return 0;
    }
  );
}

function paintHistory(result, heading, forceHeading) {
  var entries = result.entries || [];
  // 开抽屉时（没人点名要标题）空档就留空，别拿一句"上次的对话"占着地方；
  // 用户自己点过来换的那一段（forceHeading）则相反：标题得有，不然他不知道自己站在哪。
  if (entries.length === 0 && forceHeading !== true) return 0;

  var head = makeRow('agent');
  head.textContent = heading || '上次的对话（存在这台机器上）';
  // 多轮上下文这件事照实说在这一行的悬停里：这一段里的每一条都会发给模型（它自己按上下文
  // 窗口裁，见 agent/loop.py），所以"接着上一句说"是有依据的 —— 面板不替它记上下文，
  // 也不假装自己记得。messages / source 都是 agent/history 回的（server.py 的 agent_history）。
  var messages = Number(result.messages) || entries.length;
  STATE.historyCount = messages;
  head.title =
    '这一段共 ' +
    messages +
    ' 条消息' +
    (result.source === 'store' ? '（从存档喂回来的）' : '') +
    '；接着说就行，上面说过的不用重述。';
  appendNode(head);
  if (entries.length === 0) return 0;

  var dropped = Number(result.dropped) || 0;
  if (dropped > 0) {
    var note = makeRow('agent');
    note.textContent = '更早的 ' + dropped + ' 条超出存档上限，没留下来';
    appendNode(note);
  }

  var painted = 0;
  for (var i = 0; i < entries.length; i++) {
    var entry = entries[i] || {};
    if (entry.type === 'user') addUser(String(entry.text || ''));
    else if (entry.type === 'assistant') addAssistant(String(entry.text || ''), entry.variant);
    else if (entry.type === 'tool_call') addToolCall(entry);
    else if (entry.type === 'tool_result') addToolResult(entry);
    else continue; // 不认识的条目跳过就好，别让一条把后面整段历史截断
    painted++;
  }
  return painted;
}

// ---- 会话：换一段、新开一段、关掉一段 --------------------------------------
//
// 一段对话 = 一个 session_id（宿主那边也这么认：见 lib/comfy_studio/server.py）。宿主的会话位
// 是有数的（默认 8 段），位子满了要么淘汰最久没用过的（有存档时无损），要么老实拒绝 ——
// 这一行就是让用户自己管这段事的那只手：看清单（agent/sessions）、换一段（按存档重画）、
// 新开一段（面板自己挑个新 id）、关掉一段（agent/close：腾位子，对话留在存档里）。
//
// 三处"看着像 bug、其实不是"的地方都直说：
// ① 清单里"读不了"的行：存档坏了，只认得出文件名，点不动 —— 报出来让用户去修或删，
//    而不是把那一行抹掉假装没有；
// ② --no-history 那一档：关掉不是"留着下次接着聊"，而是真丢掉，所以要先点两下（第一次只警告）；
// ③ 新开的一段在说出第一句话之前宿主里根本没有它，清单里也没有 —— 那很正常。
//
// 面板只记得"上次停在哪一段"（一个 id，存在浏览器存储里）。对话本身在宿主那儿，不在这：
// 宿主重启、面板重载，都还能把那一段喂回来。

var SESSION_KEY = 'comfyStudio.session';

// 返回 '' = 没记过；返回 null = 读不到浏览器存储（隐私模式、被禁用）—— 两者不是一回事：
// 前者是"第一次用"，后者是"这次记不住"，后者要说出来，别拿默认那段冒充上次那段。
function readSavedSession() {
  try {
    var value = window.localStorage.getItem(SESSION_KEY);
    return typeof value === 'string' ? value : '';
  } catch (e) {
    return null;
  }
}

function rememberSession(id) {
  try {
    window.localStorage.setItem(SESSION_KEY, id);
  } catch (e) {
    STATE.remembered = null; // 记不住就如实记在面板自己的账上（会话提示里会说一句）
  }
}

function restoreSession() {
  var remembered = readSavedSession();
  STATE.remembered = remembered;
  if (typeof remembered === 'string' && remembered !== '') STATE.session = remembered;
}

function sessionSelect() {
  return document.getElementById(SESSION_ID);
}

function sessionHint(text) {
  var select = sessionSelect();
  if (select) select.title = text;
}

// 会话这一行悬停时说的那句话。两处拼信息：宿主那份清单（条数上限、现在活着几段）与
// host/info（开没开存档）—— 谁后知道谁重念一遍，所以两边都调这一个函数。
function sessionHintText() {
  // "关掉是什么后果"照实说：开着存档是"留着下次接着聊"，没开存档就是"真丢掉"。
  var closing =
    STATE.archive === false
      ? '（这次没开存档：关掉一段就等于丢掉它，所以要点两下）'
      : STATE.archive === true
        ? '（关掉只是腾位子，对话留在存档里）'
        : '（关掉会腾出位子）';
  var text = '这里能换一段接着聊、新开一段、或者关掉这一段' + closing;
  var result = STATE.sessions;
  if (result && typeof result.max_sessions === 'number') {
    text +=
      '；它最多同时留 ' +
      result.max_sessions +
      ' 段，现在活着 ' +
      (typeof result.live === 'number' ? result.live : '？') +
      ' 段';
  }
  if (STATE.remembered === null) {
    text += '；浏览器存储用不了，"上次停在哪一段"这一屏重载后会忘掉（对话本身在宿主那儿）';
  }
  // 这一段的条数（agent/history 来的）：换段之前先看得到"那一段里有多少东西"，
  // 换过去之后也不会以为自己新开了一段。
  if (typeof STATE.historyCount === 'number' && STATE.historyCount > 0) {
    text += '；屏幕上这一段现在有 ' + STATE.historyCount + ' 条';
  }
  return text;
}

// 清单里那一行的字：标题 + 条数，一眼分得清是哪一段。
function sessionLabelOf(item) {
  var title = item.title ? String(item.title) : '（还没说话）';
  var count = typeof item.messages === 'number' ? item.messages : 0;
  var mark = item.busy === true ? '在跑' : item.live === true ? '' : '存档里';
  return title + ' · ' + count + ' 条' + (mark ? '（' + mark + '）' : '');
}

function fillSessions(list) {
  var select = sessionSelect();
  if (!select) return;
  select.textContent = '';
  var seen = false;
  for (var i = 0; i < list.length; i++) {
    var item = list[i] || {};
    if (item.error) {
      // 读不了的存档：只认得出文件名。列出来（用户得知道有这东西），但不给选。
      var broken = document.createElement('option');
      broken.value = '';
      broken.disabled = true;
      broken.textContent = '读不了：' + (item.file || '（它没报文件名）');
      broken.title = String(item.error);
      select.appendChild(broken);
      continue;
    }
    var id = item.session_id ? String(item.session_id) : '';
    if (id === '') continue;
    var option = document.createElement('option');
    option.value = id;
    option.textContent = sessionLabelOf(item);
    if (id === STATE.session) {
      option.textContent += '（当前）';
      seen = true;
    }
    select.appendChild(option);
  }
  if (!seen) {
    // 当前这一段还没出现在宿主的清单里（刚开的新对话、或宿主刚重启还没问起它）：
    // 补一行，别让下拉停在别的对话上 —— 那会让人以为自己在聊另一段。
    var mine = document.createElement('option');
    mine.value = STATE.session;
    mine.textContent = '（当前）这一段还没跟宿主说过话';
    select.appendChild(mine);
  }
  select.value = STATE.session;
}

function loadSessions() {
  return Promise.resolve(bridge.request('agent/sessions')).then(
    function (response) {
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        return keepLastSessions(
          '读会话清单失败: ' + (error.message || '未知错误') + '；这一段还能接着聊'
        );
      }
      var result = response.result || {};
      if (!(result.sessions instanceof Array)) {
        // 宿主的回话里没有清单（版本对不上之类）：别装作"你就这一段"，直说。
        return keepLastSessions('宿主没给会话清单：这一段还能接着聊，别处那几段看不到');
      }
      STATE.sessions = result;
      fillSessions(result.sessions);
      sessionHint(sessionHintText());
      refreshSessionEnabled();
      return result;
    },
    function () {
      // 传输层就没送到（宿主进程不在）：状态栏已经在报同一件事，这里不抢话。
      return keepLastSessions('宿主不在，看不到别的对话');
    }
  );
}

// 这一次没读到清单时走这里：**手上那份留着**，别清空。清空看起来就是"别的对话都没了"，
// 而这正是这会话行最不该让人误会的事（宿主抖一下、或它刚重启，下拉就只剩当前这一段，
// 用户会以为对话被吞了）。这份清单是上一次真读到的，"这次没读到"由提示那一句说清。
function keepLastSessions(hint) {
  var last =
    STATE.sessions && STATE.sessions.sessions instanceof Array ? STATE.sessions.sessions : [];
  fillSessions(last);
  sessionHint(hint);
  refreshSessionEnabled();
  return null;
}

// 清空消息区，准备画另一段对话（换段与关掉之后都要清，别把上一段的答案留在屏幕上）。
// 顺带把"正在画的那一次"作废（票号 +1）：换段是异步的，用户点得快时，前一段的"取历史"
// 可能后回来 —— 不认票的话它会把上上段的话画进这一段的屏幕上（见 loadHistory）。
function clearLog() {
  var log = logEl();
  if (log) log.textContent = '';
  STATE.pending = null;
  STATE.pendingLabel = null;
  STATE.forceReset = null;
  STATE.cards = {};
  STATE.planCard = null;
  STATE.paint = (STATE.paint || 0) + 1;
  // 换到别的段去了：那一段有没有轮次在跑是它自己的事。面板不再举着"叫停"的键 —— 举着的话
  // 点下去会把这一发 cancel 送给刚换到的这一段（见 cancelTurn 的 session_id）。
  STATE.detached = false;
  setStopVisible(false);
  // 找字那点东西全在这段消息里：消息清掉了，标记与计数也就无从谈起（留着会让计数说
  // "3/3 处"而屏幕上一个都没有）。所以连输入框一起清干净，等这一段画出来再重找。
  clearFind();
}

// 新会话的 id 由面板挑：宿主只认"一个字符串"，没聊起来之前这一段在它那儿根本不存在
// （也就不占会话位）。用时间戳生成，宿主那个目录里一眼看得出先后。
function nextSessionId() {
  return 'chat-' + Date.now().toString(36);
}

function newSession() {
  if (STATE.busy) return;
  STATE.closeArmed = false;
  STATE.resetArmed = false;
  STATE.session = nextSessionId();
  rememberSession(STATE.session);
  clearLog();
  loadSessions();
  setStatus('新的一段对话；说一句它就开始了');
  var input = document.getElementById(INPUT_ID);
  if (input) input.focus();
}

function switchSession(id) {
  if (STATE.busy || !id || id === STATE.session) return;
  STATE.closeArmed = false;
  STATE.session = id;
  rememberSession(id);
  clearLog();
  setStatus('换到这一段了');
  loadHistory(id, {
    heading: '这一段对话（存在这台机器上）',
    emptyNote: '这一段还没说过话'
  });
  loadSessions();
}

function closeSession() {
  if (STATE.busy) return;
  // 只有**确认**存档开着时，关掉才是"留着下次接着聊"这种可逆的事，点一下就够。
  // 没开存档（--no-history）= 关掉就是真丢掉；连存不存都不知道（拿不到 host/info）时
  // 也先按"可能要丢"对待 —— 丢掉一段对话只能由用户自己点两下，宁可多问一句。
  if (STATE.archive !== true && STATE.closeArmed !== true) {
    STATE.closeArmed = true;
    setStatus(
      STATE.archive === false
        ? '这次没开对话存档（--no-history）：再点一下「关掉」就是真丢掉这一段'
        : '还没问到宿主存不存对话：再点一下「关掉」就关掉它（有存档的话对话会留着）',
      'error'
    );
    return;
  }
  STATE.closeArmed = false;
  setSessionEnabled(false);
  setStatus('正在关掉这一段…');
  Promise.resolve(bridge.request('agent/close', { session_id: STATE.session })).then(
    function (response) {
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        addError('关掉这一段失败: ' + (error.message || '未知错误'), error.code);
        setStatus('这一段还开着', 'error');
        refreshSessionEnabled();
        return;
      }
      var result = response.result || {};
      // 关掉之后接着开一段新的：关掉的意思是"这一段我聊完了"，不是"我要看着它空着"。
      // 上一段按宿主说的留没留住，由下面那句话交代（newSession 会先写自己那句状态）。
      var kept = result.history_kept === true;
      var missed = result.closed !== true;
      newSession();
      if (missed) setStatus('这一段本来就没在宿主里开着（没说过话）');
      else if (kept) setStatus('已关掉这一段；对话留在存档里，选它就能接着说');
      else setStatus('已关掉这一段；这次没开存档，那段对话就此没了', 'error');
    },
    function (err) {
      addError('关掉这一段失败: ' + message(err));
      setStatus('这一段还开着', 'error');
      refreshSessionEnabled();
    }
  );
}

// 清空一段对话：说过的话与它的存档一起抹掉（宿主 agent/reset）。
//
// 与 closeSession 的分工见上面那个按钮的注释。这里照着 close 的"要不要问一句"来：清空比关掉
// 更狠（关掉在开着存档时是可逆的，清空永远不可逆），所以**一律两下**——不因为开着存档就省掉
// 那一声提醒。第一下只把话讲明白，第二下才真发请求。
//
// 宿主返回的 reset 与 history_cleared 是两个独立的事实：reset 说的是"内存里这一段还在不在"，
// history_cleared 说的是"磁盘上的存档删掉没有"。四个组合各有各的实话，别一律报成"已清空"——
// 内存里本来就没这一段、盘上也没东西时，说"已清空"等于替一次什么都没发生的事背书。
function resetSession() {
  if (STATE.busy) return;
  if (STATE.resetArmed !== true) {
    STATE.resetArmed = true;
    setStatus('清空会把这一段说过的话连存档一起抹掉，撤不回来；再点一下「清空」就真清', 'error');
    return;
  }
  STATE.resetArmed = false;
  setSessionEnabled(false);
  setStatus('正在清空这一段…');
  Promise.resolve(bridge.request('agent/reset', { session_id: STATE.session })).then(
    function (response) {
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        addError('清空这一段失败: ' + (error.message || '未知错误'), error.code);
        setStatus('这一段没清掉', 'error');
        refreshSessionEnabled();
        return;
      }
      var result = response.result || {};
      var reset = result.reset === true;
      var cleared = result.history_cleared === true;
      // 屏上那些行现在是"已经不存在的话"：留着就是给一段空对话背书（而且用户会以为没清掉）。
      clearLog();
      loadSessions();
      if (!reset && !cleared) setStatus('这一段本来就空着，没什么可清的');
      else if (reset && !cleared) setStatus('已清空这一段：它没有存档，只清了内存里这一份');
      else if (!reset && cleared) setStatus('已清空这一段的存档；它本来就没在内存里开着');
      else setStatus('已清空这一段：说过的话连存档一起抹掉了');
    },
    function (err) {
      addError('清空这一段失败: ' + message(err));
      setStatus('这一段没清掉', 'error');
      refreshSessionEnabled();
    }
  );
}

// ---- 它记在哪 ------------------------------------------------------------
//
// 记忆和对话都落在用户级数据目录里（见 lib/comfy_studio/memory.py / history.py），面板得让
// 人看得见：出了事要能去找那个文件，平时也该知道"它记的东西留在这台机器上"。三种"看着像
// bug、其实不是"的情况更要直说：
// ① 记忆文件读不了（宿主在 host/info 的 memory_error 里如实报了）：这一档下**每问一句都会
//    报错**，因为人设每轮都要拿记忆重算（server.py 的 _prompt_source），修好或删掉它才能
//    接着聊 —— 所以这一行报红，且写明是哪个文件；
// ② 宿主是 --no-memory 起的：它这一档不记事，别把"没记住"当成坏了；
// ③ 宿主是 --no-history 起的：这段对话面板一关就没了，别指望下次还接得上。
// 正常时就是一行小字（记着几条 + 都在这台机器上），完整路径放悬停提示里：那串路径铺在
// 界面上要占掉半个抽屉。宿主没报的字段不替它编，就报"没说"。
// 一轮结束后再看一眼条数：它刚记下的事，用户应该当场看得见。

function setStorage(text, tone, hint) {
  var line = document.getElementById(STORAGE_ID);
  if (!line) return;
  line.textContent = text;
  line.setAttribute('data-tone', tone === 'error' ? 'error' : 'ok');
  line.style.color = tone === 'error' ? '#ff8080' : MUTED;
  line.title = hint || '';
  line.style.cursor = hint ? 'help' : 'default';
}

function loadStorage() {
  return Promise.resolve(bridge.request('host/info')).then(
    function (response) {
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        setStorage('看不清它把记忆和对话存在哪: ' + (error.message || '未知错误'), 'error', '');
        return null;
      }
      var info = response.result || {};
      paintStorage(info);
      return info;
    },
    function () {
      // 传输层就没送到（宿主进程不在）：状态栏已经在报同一件事，这里不抢话。
      setStorage('宿主不在，看不到它把记忆和对话存在哪', '', '');
      return null;
    }
  );
}

function paintStorage(info) {
  var where = [];
  if (info.memory_file) where.push('记忆：' + info.memory_file);
  if (info.history_dir) where.push('对话存档：' + info.history_dir);

  // 开没开存档先记下来：面板的"关掉"要不要先警告一次，就看它（见 closeSession）。
  // 就算记忆那一行报红先返回，这一条也得记 —— 它管的是会话那行，不是这一行。
  STATE.archive = info.history === true ? true : info.history === false ? false : null;
  // 会话那行的悬停提示里也有"关掉是什么后果"（它可能比这一行先拼好）：现在知道了就重念一遍。
  sessionHint(sessionHintText());

  if (info.memory_error) {
    setStorage(
      '记忆读不了（' + (info.memory_file || '记忆文件') + '）：修好或删掉它，助手才能接着聊',
      'error',
      String(info.memory_error)
    );
    return;
  }

  var parts = [];
  if (info.memory === false) parts.push('这次没开记忆（--no-memory），你说过的事它不会记住');
  else if (info.memory !== true) parts.push('记忆开没开它没说');
  else if (info.memory_entries === 0) parts.push('还没记住什么');
  else if (typeof info.memory_entries === 'number') parts.push('它记着 ' + info.memory_entries + ' 条事');
  else parts.push('记忆开着');

  if (info.history === false) parts.push('这次没开对话存档（--no-history），面板一关这段对话就没了');
  else if (info.history === true) parts.push('对话存在这台机器上');
  else parts.push('对话存不存它没说');

  // 能不能上网：默认开着（web__search / web__fetch / web__crawl 三张表工具），只有 --no-web 才关。
  // 顺带报**走的是哪条路** —— 必应 RSS 还是自建 SearXNG："搜出来结果不对/太少"时第一个要看的就是它，
  // 而这条路在界面上没别的地方会说（见 lib/comfy_studio/server.py 里 host/info 那几行）。
  // 宿主没报的字段不替它编：老宿主可能只说 web 不说后端。
  if (info.web === false) parts.push('这次没开联网（--no-web），不知道的事它只能凭记忆答');
  else if (info.web !== true) parts.push('联网开没开它没说');
  else if (info.web_backend === 'searxng') parts.push('能联网（自建 SearXNG）');
  else if (info.web_backend === 'bing') parts.push('能联网（走必应）');
  else parts.push('能联网');

  // 地址按同样的理由塞进悬停提示：一个网址铺在界面上占地方，但它正是排障要看的那一眼。
  // 两条各报各的、都只看宿主给没给：走自建实例时宿主那头就**不会**再报必应那条入口
  // （它没被请求过），所以这里不必自己判断"该不该显示"—— 报了才画，没报就没有。
  if (info.web === true && info.web_search_url) where.push('搜索入口：' + info.web_search_url);
  if (info.web === true && info.web_searxng_url) where.push('自建实例：' + info.web_searxng_url);

  setStorage(parts.join('；'), '', where.join(' ｜ '));
}

// 传进来的是下拉的完整值（"来源::模型名"）：切模型的同时也换了地址与密钥（宿主 agent_model
// 走的是 use_config），所以只认整串；纯模型名会被当成主源 —— 那是给老脚本留的口子。
function switchModel(ref) {
  var model = document.getElementById(MODEL_ID);
  if (!model || STATE.busy || ref === '' || ref === STATE.modelRef) return;
  var previous = STATE.modelRef;
  setModelEnabled(false);
  setStatus('正在切到 ' + modelNameOf(ref) + '…');

  var settle = function () {
    refreshModelEnabled();
  };
  Promise.resolve(bridge.request('agent/model', { model: ref })).then(
    function (response) {
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        model.value = previous;
        addError('切换模型失败: ' + (error.message || '未知错误'), error.code);
        setStatus('模型仍是 ' + (previous ? modelNameOf(previous) : '未知'), 'error');
        return;
      }
      var result = response.result || {};
      // 下拉里的值始终是"来源::模型名"的整串：宿主只回模型名（它不知道面板是怎么拼的），
      // 照着它写回下拉就把来源丢了 —— 之后再切一次就会切去错的那一家。
      STATE.model = String(result.model || modelNameOf(ref));
      STATE.modelRef = ref;
      model.value = ref;
      var skipped = result.skipped || [];
      setStatus(
        '模型：' +
          STATE.model +
          (skipped.length ? '（' + skipped.length + ' 个会话正在跑，等这一轮结束再生效）' : '')
      );
    },
    function (err) {
      model.value = previous;
      addError('切换模型失败: ' + message(err));
      setStatus('模型仍是 ' + (previous || '未知'), 'error');
    }
  ).then(settle, settle);
}

// 换智能体。与 switchModel 同一套写法，只是响应里没有 skipped：人设是每轮现算的，所有会话
// 下一次提问就用新的（宿主 agent_agent 的说明里写了为什么不用跳过）。
function switchAgent(id) {
  var agent = document.getElementById(AGENT_ID);
  if (!agent || STATE.busy || id === '' || id === STATE.agent) return;
  var previous = STATE.agent;
  setAgentEnabled(false);
  setStatus('正在换成 ' + id + '…');

  var settle = function () {
    refreshAgentEnabled();
  };
  Promise.resolve(bridge.request('agent/agent', { agent: id })).then(
    function (response) {
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        agent.value = previous;
        addError('换智能体失败: ' + (error.message || '未知错误'), error.code);
        setStatus('智能体仍是 ' + (previous || '未知'), 'error');
        return;
      }
      var result = response.result || {};
      STATE.agent = String(result.agent || id);
      agent.value = STATE.agent;
      setStatus('智能体：' + (result.name || STATE.agent) + '（下一次提问按这个来）');
    },
    function (err) {
      agent.value = previous;
      addError('换智能体失败: ' + message(err));
      setStatus('智能体仍是 ' + (previous || '未知'), 'error');
    }
  ).then(settle, settle);
}

// ---- 事件与请求 --------------------------------------------------------

function onEvent(payload) {
  // 只有一轮在跑：这期间来的事件都属于它。
  if (!STATE.turn) return;
  var params = (payload && payload.params) || {};
  // 宿主上的会话可以不止一条，事件自带 session_id：别的会话在跑，别画进这个抽屉。
  if (params.session_id && params.session_id !== STATE.session) return;
  var type = params.type;
  if (type === 'retry') {
    // 宿主在一次模型调用失败之后按退避重试（见 lib/comfy_studio/agent/llm.py）：这是
    // "还活着、只是还没成"的唯一信号，必须画出来 —— 不画，它和卡死就是同一幅画面。
    var attempt = params.attempt;
    var total = params.total;
    var delay = params.delay;
    STATE.turnNote =
      '模型没回应，' + (delay || 0) + 's 后重试（第 ' + attempt + '/' + total + ' 次）';
    paintTurnClock();
    setStatus('模型请求失败，正在重试（第 ' + attempt + '/' + total + ' 次）', 'error');
    return;
  }
  if (type === 'assistant') {
    addAssistant(String(params.text || ''), 'intermediate');
    return;
  }
  if (type === 'tool_call') {
    addToolCall(params);
    return;
  }
  if (type === 'tool_result') {
    addToolResult(params);
    return;
  }
  if (type === 'ask_user') {
    // 审核节点：宿主那张 review__ask_user 正挂着等这张卡片的回答。
    addAskUser(params);
    return;
  }
  if (type === 'plan') {
    // 灵感输入：宿主那张 plan__submit 正挂着等这张清单卡的态度。
    addPlan(params);
    return;
  }
  if (type === 'plan_progress') {
    // 单向通知：回来给清单里的某一步打勾，没有谁在等它。
    markPlanStep(params);
    return;
  }
  // final 不画：最终文本由请求结果给，画两遍就重复了。
}

function sendTurn() {
  if (STATE.busy) return;
  var input = document.getElementById(INPUT_ID);
  if (!input) return;
  var text = (input.value || '').trim();
  var quotes = STATE.quotes || [];
  // 只带引用不写字也是能发的：那一轮就是"照这段原文开工"。
  if (text === '' && quotes.length === 0) return;

  STATE.busy = true;
  STATE.closeArmed = false;
  setSendEnabled(false);
  setStopVisible(true);
  refreshModelEnabled(); // 一轮在飞时不换模型、不换会话，免得把这一轮打断或答到别的段上
  refreshAgentEnabled();
  refreshSessionEnabled();
  input.value = '';
  // 引用块拼在话前面（composeQuotes）：这一版既画进气泡、也**原样发给宿主**。画的和发的
  // 必须是同一份文本 —— 只画不发，那张卡就只是给人看的装饰，模型手里根本没有那段原文；
  // 而画的时候由 addUser 拆回卡片，所以重开面板后画出来还是卡片（同一份文本，两处一致）。
  var composed = composeQuotes(text, quotes);
  addUser(composed);
  STATE.quotes = [];
  paintQuotes();
  setStatus('agent 正在处理…');

  STATE.turn = {};
  STATE.cards = {};
  STATE.planCard = null;
  addPending();
  startTurnClock();
  // 收尾：摘下"正在思考"、放开发送键。detached 说的不是"这一轮跑完了"，而是"面板放手了，
  // 宿主那一轮还在跑"：
  //   - 这一轮的 agent/chat 落地了（成功、失败、或是被宿主拒了）→ false，该摘的都摘；
  //   - 界面被强行复位（见 forceResetTurn）→ true：宿主那一轮还在，所以"停止"键要按
  //     "叫停宿主那一轮"的身份留下来；
  //   - 这一轮被宿主以"会话已有一轮在跑"挡下（-32602）→ true：这一轮压根没起来，卡住的是
  //     上一轮，能停的同样只有宿主手里那一份。
  // 原先这三种收成同一个样子（键一律摘掉），于是用户能撞进"发一次被拒一次，而面板上一个
  // 能按的都没有"的死角。
  var settle = function (detached) {
    stopTurnClock();
    removePending();
    STATE.finishTurn = null;
    STATE.turn = null;
    STATE.cards = {};
    STATE.planCard = null;
    STATE.busy = false;
    STATE.detached = detached === true;
    setSendEnabled(true);
    setStopVisible(STATE.detached, STATE.detached);
    refreshModelEnabled();
    refreshAgentEnabled();
    refreshSessionEnabled();
    // 这一轮可能刚记下一条事或刚把记忆文件弄坏：再看一眼，别让那一行停在旧话上。
    loadStorage();
    // 智能体清单是从盘上现读的：用户可能刚往里丢了一份 md，聊完这句就该看得见。
    loadAgents();
    // 技能目录同理：agent 自己就是用它跑工作流的，这一轮里可能刚新增过一套。
    loadSkills();
    // 渲染目标也一起重读：这一轮里 agent 可能刚往工作流目录里放过文件（那样"文件没找到"就该消失）。
    loadRenders();
    // 这一轮过后这段对话的样子也变了（第一句话成了它的标题、条数加了）：
    // 清单跟着刷新，用户才看得见"它现在叫什么"。
    loadSessions();
  };
  // 等太久时那颗"强制复位"按钮要能叫到它（见 forceResetTurn）：那次收尾按 detached 走。
  STATE.finishTurn = function () {
    settle(true);
  };

  // 失败不吞字：这一轮要是没发成，刚才那段话原样还回输入框（出处：ComfyUI 官方前端 agent 面板
  // 的 composables/agent/useAgentDraftSubmission.ts —— 提交失败走 composer.restorePrompt）。
  // 只在输入框还空着的时候还：用户已经在下面写别的了，覆盖掉更糟，那就一行字都别动。
  var restoreDraft = function () {
    if (!input || (input.value || '').trim() !== '') return false;
    input.value = composed;
    if (typeof input.setSelectionRange === 'function') {
      input.setSelectionRange(composed.length, composed.length);
    }
    return true;
  };

  // 宿主挡下"同一个会话的第二轮"时，这一轮压根没起来：收尾要照 detached 走（见 settle）。
  var rejectedBusy = false;
  bridge.request('agent/chat', { text: composed, session_id: STATE.session }).then(
    function (response) {
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        addError('失败: ' + (error.message || '未知错误'), error.code);
        // 宿主那句"会话已有一轮在跑"不是这一轮的失败，是这一轮压根没起来（卡住的是上一轮）：
        // 收尾照 detached 处理，把"叫停宿主那一轮"摆出来（见 settle）。
        rejectedBusy = isSessionBusy(error);
        var kept = restoreDraft();
        if (rejectedBusy) {
          setStatus(
            (kept ? '这一轮没发出去，话还回输入框了：' : '') +
              '宿主那一轮还在跑，点「叫停宿主那一轮」或换个会话',
            'error'
          );
        } else {
          setStatus(
            kept ? '这一轮失败了，刚才那段话还回输入框了（改完再发）' : '这一轮失败了',
            'error'
          );
        }
        return;
      }
      var result = response.result || {};
      if (result.cancelled === true) {
        // 停下的一轮照样是一次**正常**响应（宿主这么约定的）：画一行"已停止"收尾，
        // 别当失败报红，也别把空回答画成一个空气泡。
        addStopped(result.reason);
        setStatus('已停止（可以接着说下一句）');
        return;
      }
      var answer = result.text;
      addAssistant(typeof answer === 'string' ? answer : JSON.stringify(result), 'final');
      setStatus('就绪');
    },
    function (err) {
      addError('失败: ' + message(err));
      setStatus(
        restoreDraft() ? '这一轮失败了，刚才那段话还回输入框了（改完再发）' : '这一轮失败了',
        'error'
      );
    }
  ).then(
    function () {
      settle(rejectedBusy);
    },
    function () {
      settle(rejectedBusy);
    }
  );
}

// 叫停这一轮。真正的收尾（摘下"正在思考"、放开发送键）仍走上面那条 finish，
// 因为停下之后 agent/chat 会正常回一个 cancelled 结果——这里只负责把请求发出去。
function cancelTurn() {
  // detached 时 STATE.busy 已经是 false（界面早复位了），可宿主那一轮还占着这个会话 ——
  // 这颗键正是为那一刻留的，所以判据得把它算上，否则点它什么都不会发生（原先就是这个死角）。
  if (!STATE.busy && !STATE.detached) return;
  var stop = document.getElementById(STOP_ID);
  if (stop) {
    stop.disabled = true;
    stop.style.opacity = '0.5';
  }
  setStatus(STATE.detached ? '正在叫停宿主那一轮…' : '正在停下这一轮…');

  var restore = function () {
    if (stop) {
      stop.disabled = false;
      stop.style.opacity = '1';
    }
  };
  Promise.resolve(bridge.request('agent/cancel', { session_id: STATE.session })).then(
    function (response) {
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        addError('取消失败: ' + (error.message || '未知错误'), error.code);
        setStatus('没停下，这一轮还在跑', 'error');
        restore();
        return;
      }
      if (!response.result || response.result.cancelled !== true) {
        // 幂等：没有在跑的轮次就回 cancelled:false。多半是这一轮刚好自己跑完了，
        // 正常结果正在回来的路上。界面复位后叫停也会走到这里 —— 宿主说它手上那一份
        // 已经收场了，那就别再举着"叫停"的键了。
        STATE.detached = false;
        setStopVisible(false);
        setStatus('这一轮已经结束了');
        restore();
      }
      // cancelled:true：等 agent/chat 那条结果回来收尾（它会画"已停止"）。
    },
    function (err) {
      addError('取消失败: ' + message(err));
      setStatus('没停下，这一轮还在跑', 'error');
      restore();
    }
  );
}

function refreshStatus() {
  return Promise.resolve(bridge.status()).then(
    function (status) {
      if (!status || status.available !== true) {
        setStatus(status && status.error ? status.error : '宿主不可用', 'error');
        setSendEnabled(false);
        setModelEnabled(false);
        setSessionEnabled(false);
        return status;
      }
      setStatus(status.running ? 'MCP 宿主运行中' : '宿主待启动（发消息时自动拉起）');
      setSendEnabled(true);
      refreshModelEnabled();
      refreshAgentEnabled();
      refreshSessionEnabled();
      return status;
    },
    function (err) {
      setStatus('查询宿主状态失败: ' + message(err), 'error');
      setSendEnabled(false);
      setSessionEnabled(false);
      return null;
    }
  );
}

function openDrawer() {
  if (!document.getElementById(DRAWER_ID)) buildDrawer();
  var drawer = document.getElementById(DRAWER_ID);
  if (!drawer) return;
  drawer.style.display = 'flex';
  STATE.open = true;
  // 关抽屉就把两处"第二次点击"收回去：隔了半天再点一下不该把一段对话关掉或清掉。
  STATE.closeArmed = false;
  STATE.resetArmed = false;
  var input = document.getElementById(INPUT_ID);
  if (input) input.focus();
  refreshStatus();
  loadModels();
  loadAgents();
  // skill 目录也在引擎侧：面板每次打开都现读一遍，引擎重启过、或刚往 skills 目录里加了
  // 一套，这里就该跟上（跟智能体清单一个道理）。渲染目标同理（它连工作流文件在不在都是现读的）。
  loadSkills();
  loadRenders();
  loadHistory();
  loadSessions();
  loadStorage();
}

function closeDrawer() {
  var drawer = document.getElementById(DRAWER_ID);
  if (drawer) drawer.style.display = 'none';
  STATE.open = false;
}

// ---- 管理小说 ----------------------------------------------------------
//
// 漫剧那套流程的入口是**原文**：manju/novel/ 下躺着小说 txt，拆章、写剧本、出分镜都从它
// 出发。这一页就是那座书库的前台：列出来、翻一翻、把本机的一份接进来、看不顺眼的删掉；
// 选中一篇还能直接把"用这篇开工"送进对话输入框（人改完自己发，面板不替人按发送）。
//
// 路径一个都不拼：目录由宿主给（host/info 的 novel_dir，默认
// <comfyui-dir>/custom_nodes/comfy_studio/manju/novel，见 lib/comfy_studio/novels.py）。
// 面板这边自己拼路径，迟早会和宿主说的不是同一个地方。四个动作全走 novels/* RPC，
// 这一页自己只留两样东西：读到的第几页、和"删到第二步了没"。

// 一页多少字**不问面板**：请求时不带 chars，按宿主的 DEFAULT_READ_CHARS 来（见
// lib/comfy_studio/novels.py），翻页要用的页长从回话里的 requested_chars 拿。
// 曾在这里手抄过一份 4000 —— 两份数对不上时是**静默**的：翻页会跳字或原地打转，
// 而面板和宿主谁都不会报错，正是最该避开的那类错。

//: 四页的名字与先后（tablist 的顺序、方向键绕圈、Home/End 都照它来）。
var VIEW_ORDER = ['chat', 'novel', 'project', 'pipeline'];

//: 页名 → 给人看的页名。标签栏、占满窗口那一层的标题栏都读它 ——
//: 抄成两份的话，标签上写着「管理小说」、铺开那一层的标题却写着别的，而没人会报错。
var VIEW_LABELS = { chat: '对话', novel: '管理小说', project: '项目管理', pipeline: '流水线' };

//: 页名 → 那一页容器的 id（tab 的 aria-controls 用它，见 buildTabs）。
function viewIdOf(view) {
  if (view === 'novel') return NOVEL_VIEW_ID;
  if (view === 'project') return PROJECT_VIEW_ID;
  if (view === 'pipeline') return PIPELINE_VIEW_ID;
  return CHAT_VIEW_ID;
}

// 标签之间按方向键走时，这一按该挪几格：左右/上下 ±1，Home 到第一个，End 到最后一个，
// 别的键返回 null（不管）。绕圈由调用处取模完成。
function tabStep(view, key) {
  var at = VIEW_ORDER.indexOf(view);
  if (key === 'ArrowRight' || key === 'ArrowDown') return 1;
  if (key === 'ArrowLeft' || key === 'ArrowUp') return -1;
  if (key === 'Home') return -at;
  if (key === 'End') return VIEW_ORDER.length - 1 - at;
  return null;
}

// 键盘在标签间走时焦点也得跟着走（roving tabindex 的字面意思）：换了页不挪焦点，下一按
// 左右键还是从原来那个标签算起，人会以为键坏了。
function focusTab(view) {
  var tab = document.querySelector('#' + DRAWER_ID + ' .cs-tab[data-view="' + view + '"]');
  if (tab && typeof tab.focus === 'function') tab.focus();
}

//: 当前这一页的检索框：对话页是消息区上面那个，小说页是左边目录栏里的搜索框，
//: 项目页是筛项目那个（页内找字那个框就摆在正文上头，不用快捷键也看得见）。
function findTargetForView() {
  if (STATE.view === 'novel') {
    // 搜索框在目录栏里，栏收起来了就先展开再聚焦：对一个 display:none 的输入框 focus 是没用的。
    if (STATE.novelSideOpen !== true) toggleNovelToc();
    return document.getElementById(NOVEL_SEARCH_ID);
  }
  if (STATE.view === 'project') return document.getElementById(PROJECT_FIND_ID);
  return document.getElementById(FIND_ID);
}

// 焦点是不是落在"正在输入的东西"上：那种地方按 Esc 是"清掉我刚打的字"（各检索框自己处理），
// 不该顺手把抽屉也关掉 —— 边打字边按 Esc 的人多半不是想关面板。
function typingSomewhere() {
  var el = document.activeElement;
  if (!el) return false;
  var tag = String(el.tagName || '').toUpperCase();
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable === true;
}

function onShortcut(event) {
  if (STATE.open !== true) return;
  // 自己那面抽屉已经不在页面上了（宿主刷新了网页、又注入了一份新脚本）：这一按不归我管。
  // 少了这一句，上一份实例会照着 id 摸到**新的**那面抽屉动手 —— 同一个 Esc 被新旧两只手
  // 各收一层，一次按键收掉两层，而两边都觉得自己没错。
  if (!STATE.drawer || STATE.drawer.isConnected !== true) return;
  var key = String(event.key || '');
  if ((event.ctrlKey || event.metaKey) && !event.altKey && key.toLowerCase() === 'f') {
    var target = findTargetForView();
    // 这一页没有检索框就不动浏览器的查找（不 preventDefault）：把键抢了又不给东西最烦人。
    if (!target) return;
    event.preventDefault();
    target.focus();
    if (typeof target.select === 'function') target.select();
    return;
  }
  if (key === 'Escape' && !typingSomewhere()) {
    event.preventDefault();
    // 一次 Esc 只收一层，从眼前最近的一层往回收：
    // 弹窗（导入 / 新建项目）→ 占满窗口那两页 → 抽屉自己。
    // 一次收两层的话，填了一半的表单会和"我正看的那一页"一起消失，人得从头找回来。
    if (closeOpenPopup()) return;
    if (STATE.view !== 'chat') {
      switchView('chat');
      return;
    }
    closeDrawer();
  }
}

// 有没有正开着的弹窗（导入原文 / 新建项目…）。弹窗自己也在 Esc 上收（见 buildPopup），
// 这里再查一遍是为了兜住另一种情形：焦点被 Tab 挪到了卡片外面 —— 那时卡片上的监听
// 收不到这一按，只剩这里能把弹窗收掉（不收的话，Esc 会把抽屉关了、弹窗却还开着）。
function closeOpenPopup() {
  var pairs = [[NOVEL_FORM_ID, toggleNovelForm], [PROJECT_FORM_ID, toggleProjectForm]];
  for (var index = 0; index < pairs.length; index += 1) {
    var layer = document.getElementById(pairs[index][0]);
    if (layer && layer.dataset.open === '1') {
      pairs[index][1](false);
      return true;
    }
  }
  return false;
}

// 挂一次就够（抽屉是常驻的，见 start），所以跟宽度监听一个套路。
function installShortcuts() {
  if (STATE.shortcuts === true) return;
  STATE.shortcuts = true;
  document.addEventListener('keydown', onShortcut);
}

// 这一排标签照 ARIA 的 Tabs 惯例接键盘（出处：W3C ARIA Authoring Practices 的 Tabs 模式）：
// role=tablist/tab、aria-selected 说清哪一个是当前页、roving tabindex（只有当前那个 tab 能被
// Tab 到，其余 -1）、左右键在标签间走、Home/End 到首尾。这样键盘用户不必先摸鼠标才能换页。
function buildTabs() {
  var tabs = document.createElement('div');
  tabs.id = TABS_ID;
  tabs.className = 'cs-tabs';
  tabs.setAttribute('role', 'tablist');
  VIEW_ORDER.map(function (view) {
    return [view, VIEW_LABELS[view]];
  }).forEach(function (pair) {
    var tab = document.createElement('button');
    tab.type = 'button';
    tab.className = 'cs-tab';
    tab.dataset.view = pair[0];
    tab.textContent = pair[1];
    tab.setAttribute('role', 'tab');
    tab.setAttribute('aria-controls', viewIdOf(pair[0]));
    tab.setAttribute('aria-selected', pair[0] === STATE.view ? 'true' : 'false');
    tab.tabIndex = pair[0] === STATE.view ? 0 : -1;
    tab.addEventListener('click', function () {
      switchView(pair[0]);
    });
    tab.addEventListener('keydown', function (event) {
      var step = tabStep(pair[0], event.key);
      if (step === null) return;
      event.preventDefault();
      var next = VIEW_ORDER[(VIEW_ORDER.indexOf(pair[0]) + step + VIEW_ORDER.length) % VIEW_ORDER.length];
      switchView(next);
      focusTab(next);
    });
    tabs.appendChild(tab);
  });
  return tabs;
}

function switchView(view) {
  STATE.view =
    view === 'novel' || view === 'project' || view === 'pipeline' ? view : 'chat';
  var chat = document.getElementById(CHAT_VIEW_ID);
  var novel = document.getElementById(NOVEL_VIEW_ID);
  var project = document.getElementById(PROJECT_VIEW_ID);
  var pipeline = document.getElementById(PIPELINE_VIEW_ID);
  if (chat) chat.style.display = STATE.view === 'chat' ? 'flex' : 'none';
  if (novel) novel.style.display = STATE.view === 'novel' ? 'flex' : 'none';
  if (project) project.style.display = STATE.view === 'project' ? 'flex' : 'none';
  if (pipeline) pipeline.style.display = STATE.view === 'pipeline' ? 'flex' : 'none';
  var tabs = document.querySelectorAll('#' + DRAWER_ID + ' .cs-tab');
  for (var index = 0; index < tabs.length; index += 1) {
    var on = tabs[index].dataset.view === STATE.view;
    tabs[index].dataset.active = on ? 'true' : 'false';
    // aria-selected 与 roving tabindex 得跟着一起走，否则读屏软件说的和眼睛看到的不是同一页。
    tabs[index].setAttribute('aria-selected', on ? 'true' : 'false');
    tabs[index].tabIndex = on ? 0 : -1;
  }
  // 「管理小说」「项目管理」不在这条窄缝里显示，而是把**占满窗口**的那一层铺开
  // （见 buildViewsOverlay）：那两层自己的显隐仍旧由上面那两行管着 ——
  // 这一层只负责"要不要占满窗口"，两件事分开，各自都只有一处作者。
  var layer = document.getElementById(VIEWS_ID);
  if (layer) layer.dataset.open = STATE.view === 'chat' ? '0' : '1';
  var layerTitle = document.getElementById(VIEWS_TITLE_ID);
  if (layerTitle) layerTitle.textContent = VIEW_LABELS[STATE.view];
  // 每次切到这一页都重新列一遍：原文是别的程序（编辑器、git、别的工具）也会动的东西，
  // 拿上回那份列表当准数，就会出现"点了半天打开的是个已经不存在的文件"。
  if (STATE.view === 'novel') loadNovels();
  // 项目那页同理，而且更甚：剧本、分镜、素材多半是别的程序（编辑器、生成脚本、智能体）写的，
  // 面板只是看它与调用它的地方。已经开着的那一部跟着重读一遍（不重读就等于给旧数据背书）。
  if (STATE.view === 'project') {
    loadProjects();
    if (STATE.projectOpen) openProject(STATE.projectOpen.name);
  }
  // 流水线那页同理：项目目录、原文库、进度账全是别的程序（编辑器、生成脚本、别的智能体）
  // 也会动的东西，拿上回那份当准数，就会出现"计划上写着还差 S4、其实早跑过了"。
  if (STATE.view === 'pipeline') loadPipeline();
}

// 「管理小说」与「项目管理」共用的那一层：**占满窗口**。
//
// 为什么挂抽屉里而不是挂到 document.body 上：面板这几百条样式全收在 DRAWER_ID 那一条
// （见 CHAT_CSS 的头一条注释），挂到 body 上就得把整套选择器再写一遍 —— 两处维护，
// 改一处忘一处。能挂抽屉里是因为 position:fixed：抽屉自己没有 transform / filter /
// will-change 这类会造"包含块"的东西（见 buildDrawer 的内联样式），所以固定定位在这里
// **就是**相对视口，inset:0 即铺满窗口。哪天给抽屉加上动画位移，这一层会**悄悄**缩回
// 抽屉那条窄缝里 —— 那正是这里写清楚这条前提的原因。
//
// 标题栏不是摆设：这一层铺满窗口时，抽屉顶上那排标签也被盖住了，得有一个说清
// "我现在在哪一页、按哪儿回去"的地方（各页工具栏里那个「去对话」在滚动区里，会滚走）。
function buildViewsOverlay() {
  var layer = document.createElement('div');
  layer.id = VIEWS_ID;
  layer.className = 'cs-views';
  layer.dataset.open = '0';

  var head = document.createElement('div');
  head.className = 'cs-views-head';

  var title = document.createElement('div');
  title.id = VIEWS_TITLE_ID;
  title.className = 'cs-views-title';
  // 标题由 switchView 填（同一个来源 VIEW_LABELS）：这里不先写死一句"管理小说"，
  // 否则第一帧显示的是上一次那一页的名字。
  title.textContent = '';
  head.appendChild(title);

  var back = document.createElement('button');
  back.id = VIEWS_BACK_ID;
  back.type = 'button';
  back.className = 'cs-views-back';
  back.textContent = '返回对话';
  back.title = '回到对话那一页（这一层只是收起来，里面的选择都还在）';
  back.addEventListener('click', function () {
    switchView('chat');
  });
  head.appendChild(back);

  layer.appendChild(head);
  layer.appendChild(buildNovelView());
  layer.appendChild(buildProjectView());
  // 流水线也是"翻资料 + 按键"的地方：一张八段的表加上每段的落点，窄缝里放不下。
  layer.appendChild(buildPipelineView());
  return layer;
}

function buildNovelView() {
  var view = document.createElement('div');
  view.id = NOVEL_VIEW_ID;
  view.style.cssText = 'flex:1;min-height:0;display:none;flex-direction:column;';
  view.setAttribute('role', 'tabpanel');

  var bar = document.createElement('div');
  bar.className = 'cs-novel-bar';
  bar.appendChild(novelButton('刷新', '重新列一遍原文目录', function () {
    loadNovels();
  }));
  bar.appendChild(novelButton('导入…', '把本机的一份 txt/md 接进原文目录（粘贴它的绝对路径）', function () {
    // 打开就是一个干净的导入弹窗：上一回那个"要不要覆盖"是属于上一回那一次的
    // （同一份路径再来一次，「导入」还会再问一遍，问的答案不该在上一个问题上接着用）。
    if (toggleNovelForm()) showOverwrite(false);
  }));
  bar.appendChild(novelButton('去对话', '回到对话那一页', function () {
    switchView('chat');
  }));
  var toc = novelButton('目录', '左边那一栏：这一篇的章节目录与全文搜索（先点一行「读」打开一篇）', function () {
    toggleNovelToc();
  });
  toc.id = NOVEL_TOC_ID;
  // 默认开着（STATE.novelSideOpen）：切章跳转是这一页的日常动作，藏起来没人会去找。
  toc.dataset.active = 'true';
  bar.appendChild(toc);

  // 导入表单是个弹窗（搭法见 buildPopup）：路径是长文本，挤在按钮那行里会窄到看不见自己
  // 粘了什么，整行给它。
  var popup = buildPopup(NOVEL_FORM_ID, NOVEL_FORM_HINT_ID, '导入原文');
  var form = popup.layer;

  var path = document.createElement('input');
  path.id = NOVEL_PATH_ID;
  path.type = 'text';
  path.className = 'cs-novel-path';
  // 例子里用正斜杠：这段 JS 住在一个模板字符串里，反斜杠要先过一层转义，
  // 写出来是给人看的话就别给自己埋雷（Windows 上路径两种斜杠两边都认）。
  path.placeholder = '本机原文的绝对路径，例如 D:/books/某小说.txt';
  path.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') {
      event.preventDefault();
      importNovel(false);
    }
  });
  // 换了路径就把"覆盖导入"收回去：那一下会替换掉目录里同名那本，只该对着刚问过的那个
  // 路径点，不能留在屏幕上等着被下一个路径误用。
  path.addEventListener('input', function () {
    showOverwrite(false);
  });

  popup.body.appendChild(popupField('本机原文的绝对路径（txt / md）', path));

  popup.actions.appendChild(
    novelButton('取消', '关掉这个弹窗（不接进来）', function () {
      toggleNovelForm(false);
    })
  );
  var go = novelButton('导入', '把这份接进原文目录（同名会先问你）', function () {
    importNovel(false);
  });
  // 「导入」是这一页往下走的那一步，弹窗里就它是实心的。
  go.dataset.primary = '1';
  popup.actions.appendChild(go);
  // 「覆盖导入」不是另一条路，是同一个问题的另一个答案：露出来之前先看卡片上那句话。
  var overwrite = novelButton('覆盖导入', '同名时换成你这份，原来那本会被替换掉', function () {
    importNovel(true);
  });
  overwrite.dataset.tone = 'danger';
  overwrite.style.display = 'none';
  popup.actions.appendChild(overwrite);

  var hint = document.createElement('div');
  hint.id = NOVEL_HINT_ID;
  hint.className = 'cs-novel-hint';
  hint.textContent = '还没读过原文目录。';

  var list = document.createElement('div');
  list.id = NOVEL_LIST_ID;
  list.className = 'cs-novel-list';

  var reader = document.createElement('div');
  reader.id = NOVEL_READER_ID;
  reader.className = 'cs-novel-reader';
  reader.textContent = '选中上面一篇，正文显示在这里。';

  var pager = document.createElement('div');
  pager.id = NOVEL_PAGER_ID;
  pager.className = 'cs-novel-pager';

  // 正文那一列：正文占满，翻页行钉在它下面（跟着正文一起滚，翻页就找不着了）。
  var main = document.createElement('div');
  main.id = NOVEL_MAIN_ID;
  main.className = 'cs-novel-main';
  main.appendChild(reader);
  main.appendChild(pager);

  var body = document.createElement('div');
  body.id = NOVEL_BODY_ID;
  body.className = 'cs-novel-body';
  body.appendChild(buildNovelSide());
  body.appendChild(main);

  view.appendChild(bar);
  view.appendChild(hint);
  // 批量那一栏就摆在篇目列表上面（它管的就是下面这一列）：常驻，没勾选时只说明怎么用。
  view.appendChild(buildNovelBatch());
  view.appendChild(list);
  view.appendChild(body);
  // 弹窗摆在最后：它是绝对定位、不吃布局（放哪儿都不推别人），摆最后只是为了让它在这一页
  // 所有内容上面。
  view.appendChild(form);
  return view;
}

// 正文左边那一栏：一行标题（说清下面是目录还是搜索结果）、一个搜索框、下面那列。
// 它一直躺在 DOM 里，显隐交给 [data-open]（见 applyNovelSide）—— 用了再建会在
// "切页 → 回来"的时候丢掉搜索结果，那等于每次都得重搜一遍。
function buildNovelSide() {
  var side = document.createElement('div');
  side.id = NOVEL_SIDE_ID;
  side.className = 'cs-novel-side';
  side.dataset.open = '0';

  var head = document.createElement('div');
  head.id = NOVEL_SIDE_HEAD_ID;
  head.className = 'cs-novel-side-head';
  var label = document.createElement('span');
  label.className = 'cs-novel-side-title';
  label.textContent = '目录';
  var back = novelButton('返回目录', '从搜索结果回到章节目录', function () {
    if (STATE.novelOpen) loadChapters(STATE.novelOpen.name);
  });
  back.id = NOVEL_TOC_BACK_ID;
  back.style.display = 'none';
  head.appendChild(label);
  head.appendChild(back);

  var search = document.createElement('div');
  search.className = 'cs-novel-search';
  var input = document.createElement('input');
  input.id = NOVEL_SEARCH_ID;
  input.type = 'text';
  input.placeholder = '在正文里找一串字';
  input.addEventListener('keydown', function (event) {
    if (event.key === 'Enter') {
      event.preventDefault();
      searchNovelFromForm();
    }
  });
  search.appendChild(input);
  search.appendChild(
    novelButton('找', '在正文里找这串字（点结果跳过去）', function () {
      searchNovelFromForm();
    })
  );

  var list = document.createElement('div');
  list.id = NOVEL_SIDE_LIST_ID;
  list.className = 'cs-novel-side-list';

  side.appendChild(head);
  side.appendChild(search);
  side.appendChild(list);
  return side;
}

// 这一页要用的按钮长一个样，样式表里一条 .cs-novel-btn 管全部。
function novelButton(text, title, onClick) {
  var button = document.createElement('button');
  button.type = 'button';
  button.className = 'cs-novel-btn';
  button.textContent = text;
  button.title = title;
  button.addEventListener('click', onClick);
  return button;
}

// 这一页的提示行：文案是这一页的事，语气交给 hintLine（三页同一套）。
function novelHint(text, tone) {
  return hintLine(NOVEL_HINT_ID, text, tone);
}

// 导入这条路上的提示：导入弹窗盖住了页顶那条，所以同一句话要在卡片里也写一份（跟项目页的
// projectHint 是同一个道理：**一个调用写两处**，文案与语气还是只在这里定）。
// 只有导入用这一份 —— 这一页页顶那条还说别的事（正读着哪一章、列表里几篇），那些跟这张
// 卡片没有关系，不该跟着抄进弹窗里。
function importHint(text, tone) {
  hintLine(NOVEL_FORM_HINT_ID, text, tone);
  return novelHint(text, tone);
}

// 导入弹窗的开关：工具栏那颗「导入…」与导完的收尾都走它（脾气交给 togglePopup）。
function toggleNovelForm(open) {
  return togglePopup(NOVEL_FORM_ID, NOVEL_FORM_HINT_ID, NOVEL_PATH_ID, open);
}

// 「覆盖导入」不常驻：同名不是出错，是"要你确认一下"，确认了才把它露出来 —— 而且只对着刚
// 问过的那条路径（改了路径就收回，见 NOVEL_PATH_ID 的 input 监听）。
// 它露出来的同时卡片也变个脸色：这一下会替换掉目录里同名那本，长什么样就说明这一下有多重。
function showOverwrite(visible) {
  var form = document.getElementById(NOVEL_FORM_ID);
  if (!form) return;
  var button = form.querySelector('.cs-novel-btn[data-tone="danger"]');
  if (button) button.style.display = visible ? '' : 'none';
  var card = form.querySelector('.cs-popup-card');
  if (card) card.dataset.state = visible ? 'confirm' : '';
}

// 大小和日期都按人看得懂的样子写：面板上"3145728 字节"和"3.0 MB"是同一件事，
// 但只有后者能让人一眼判断这篇值不值得打开。
function formatBytes(bytes) {
  if (typeof bytes !== 'number' || bytes < 0) return '大小不明';
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1024 / 1024).toFixed(1) + ' MB';
}

function formatTime(seconds) {
  if (typeof seconds !== 'number' || !seconds) return '改于不明';
  return new Date(seconds * 1000).toLocaleString();
}

function novelEmpty(text) {
  var empty = document.createElement('div');
  empty.className = 'cs-novel-empty';
  empty.textContent = text;
  return empty;
}

// note 是"刚刚发生的那件事"（刚导进来一本、刚删掉一篇）。它有理由压过目录摘要：
// 用户按下那个按钮，要看到的是"这一下成没成"，而不是又一次被念目录在哪、共几篇。
function loadNovels(note) {
  var list = document.getElementById(NOVEL_LIST_ID);
  if (list && !STATE.novels) {
    list.textContent = '';
    list.appendChild(novelEmpty('正在列原文目录…'));
  }
  // 连点两下"刷新"、或者切页切得快，回话可能乱序：认序号，不是最新那趟的就不画。
  STATE.novelListToken = (STATE.novelListToken || 0) + 1;
  var token = STATE.novelListToken;
  return Promise.resolve(bridge.request('novels/list', {})).then(
    function (response) {
      if (token !== STATE.novelListToken) return null;
      // 通道本身出事（宿主退了、连接断了）时 bridge 那边也可能直接把 Promise 打回失败，
      // 所以下面那个 rejection 分支照留；这里管的是"通道在，但宿主回了 ok:false"。
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        STATE.novels = null;
        novelHint('列不了原文目录: ' + (error.message || '未知错误'), 'error');
        paintNovels(null);
        return null;
      }
      var result = response.result || null;
      STATE.novels = result;
      paintNovels(result);
      if (note) novelHint(note, 'info');
      return result;
    },
    function (err) {
      if (token !== STATE.novelListToken) return null;
      STATE.novels = null;
      novelHint('列不了原文目录: ' + message(err), 'error');
      paintNovels(null);
      return null;
    }
  );
}

function paintNovels(result) {
  var list = document.getElementById(NOVEL_LIST_ID);
  if (!list) return;
  list.textContent = '';
  if (!result) return;
  // exists=false 不是失败：目录还没建出来（这个检出从没导过原文）或者这个检出里没有漫剧
  // 数据目录。这两件事在界面上要说成人话，而不是画成一个红叉。
  if (result.exists !== true) {
    novelHint(
      '这个检出里还没有原文目录（' + (result.dir || '路径不明') + '）：导入一本就会建出来。',
      'info'
    );
    list.appendChild(novelEmpty('还没有原文。'));
    return;
  }
  var novels = result.novels || [];
  novelHint(
    (result.dir || '原文目录') +
      ' · 共 ' +
      result.matched +
      ' 篇' +
      (result.truncated ? '（只列了前 ' + result.returned + ' 篇）' : ''),
    'info'
  );
  if (!novels.length) {
    list.appendChild(novelEmpty('目录里没有原文（txt/md）。用上面的「导入…」接一份进来。'));
    return;
  }
  novels.forEach(function (row) {
    list.appendChild(novelRow(row));
  });
}

function novelRow(row) {
  var line = document.createElement('div');
  line.className = 'cs-novel-row';
  line.dataset.name = row.name;
  if (STATE.novelOpen && STATE.novelOpen.name === row.name) line.dataset.open = 'true';
  if (isPicked(row.name)) line.dataset.picked = 'true';

  var pick = document.createElement('input');
  pick.type = 'checkbox';
  pick.className = 'cs-novel-pick';
  pick.checked = isPicked(row.name);
  pick.title = '勾进"选中"（下面那一栏能一次删掉几篇），不勾就是什么都不做';
  pick.addEventListener('change', function () {
    setPicked(row.name, pick.checked);
    // 只动这一行的底色，不重画整张表：勾一下就让人滚回列表顶上，是最败兴的那种小事
    // （要重画的动作 —— 全选/清空 —— 走 repaintPicked，那边会把滚动位置摆回去）。
    if (pick.checked) line.dataset.picked = 'true';
    else delete line.dataset.picked;
  });

  var name = document.createElement('div');
  name.className = 'cs-novel-name';
  name.textContent = row.name;

  var meta = document.createElement('div');
  meta.className = 'cs-novel-meta';
  meta.textContent = formatBytes(row.bytes) + ' · ' + formatTime(row.mtime);

  var actions = document.createElement('div');
  actions.className = 'cs-novel-actions';

  var read = novelButton(
    '读',
    row.text === true ? '读这一篇的正文' : '不是 txt/md，面板读不了这种格式',
    function () {
      openNovel(row.name, 0);
    }
  );
  // 不是 txt/md 的照样列出来（就躺在那个目录里，藏起来更让人摸不着头脑），但读不了。
  if (row.text !== true) read.disabled = true;
  actions.appendChild(read);
  actions.appendChild(
    novelButton('发到对话', '把"用这篇开工"写进对话框（自己改完再发）', function () {
      novelToChat(row);
    })
  );
  // 「以此立项」：这一篇当原著，跳到项目那页把建项目的表单打开、剧名与原著都填好。
  // 只是**填好**，不替人按"建"：集数、要不要补落点都得人来定。
  actions.appendChild(
    novelButton('以此立项', '拿这一篇当原著，跳到「项目管理」把新建表单填好', function () {
      novelToProject(row);
    })
  );

  // 删除要两下："删除"变成"确认删除"才算数，而且只对着刚点的那一行。
  // 挪走回收站那种后手不做：宿主的 novels/delete 是真删，界面上就得让人看得见这一步有多重。
  var armed = STATE.novelDeleteArmed === row.name;
  var remove = novelButton(
    armed ? '确认删除' : '删除',
    armed ? '再点一下就从磁盘上删掉这份原文' : '从原文目录里删掉这一篇（会先问一次）',
    function () {
      if (STATE.novelDeleteArmed === row.name) {
        deleteNovel(row.name);
        return;
      }
      STATE.novelDeleteArmed = row.name;
      paintNovels(STATE.novels);
    }
  );
  remove.dataset.tone = 'danger';
  if (armed) remove.dataset.armed = 'true';
  actions.appendChild(remove);

  line.appendChild(pick);
  line.appendChild(name);
  line.appendChild(meta);
  line.appendChild(actions);
  return line;
}

// ---- 批量那条道：勾几篇、一起删 ------------------------------------------
//
// 勾选记的是**名字**，不是行（见 setPicked）：列表每次刷新都整表重建，把勾挂在行上等于
// 一刷新就替用户清空选择。删除还是两下确认那一套，只是"确认"的是这一批 —— 勾选一变就
// 重新问一遍，不然会删掉没确认过的那几篇。

function pickedNames() {
  var picked = STATE.novelPicked;
  if (!picked) return [];
  return Object.keys(picked).filter(function (name) {
    return picked[name] === true;
  });
}

function isPicked(name) {
  return !!STATE.novelPicked && STATE.novelPicked[name] === true;
}

function setPicked(name, on) {
  if (!STATE.novelPicked) STATE.novelPicked = {};
  if (on) STATE.novelPicked[name] = true;
  else delete STATE.novelPicked[name];
  // 勾选一变，上一轮那个"确认删除"就不作数了。
  if (STATE.novelBatchArmed !== pickedNames().join('|')) STATE.novelBatchArmed = null;
  paintNovelBatch();
}

// 该重画列表的场合（全选/清空）：重画会把滚动位置弹回顶上，所以拿原来的位置再摆回去 ——
// 勾第 30 篇时被弹回第 1 篇是最让人火大的那种小事。
function repaintPicked() {
  var list = document.getElementById(NOVEL_LIST_ID);
  var top = list ? list.scrollTop : 0;
  paintNovels(STATE.novels);
  if (list) list.scrollTop = top;
}

// 批量那一栏：一句话说清"选了几篇"，三个动作摆出来（全选 / 清空勾选 / 删除选中）。
// 整栏重建而不是按字段改：这一栏一共一行字三个按钮，重建比按字段改不容易漏（见 setPicked）。
function paintNovelBatch() {
  var bar = document.getElementById(NOVEL_BATCH_ID);
  if (!bar || !bar.parentNode) return;
  bar.parentNode.replaceChild(buildNovelBatch(), bar);
}

function buildNovelBatch() {
  var bar = document.createElement('div');
  bar.id = NOVEL_BATCH_ID;
  bar.className = 'cs-novel-batch';
  var picked = pickedNames();

  var count = document.createElement('span');
  count.className = 'cs-novel-batch-count';
  count.textContent =
    picked.length === 0
      ? '没勾选：勾上左边方框，可以一次删几篇'
      : '选中 ' + picked.length + ' 篇：' + picked.join('、');
  bar.appendChild(count);

  var all = novelButton('全选', '把列出来的篇目都勾上（不删东西）', function () {
    var rows = (STATE.novels && STATE.novels.novels) || [];
    if (!STATE.novelPicked) STATE.novelPicked = {};
    rows.forEach(function (row) {
      STATE.novelPicked[row.name] = true;
    });
    STATE.novelBatchArmed = null;
    repaintPicked();
    paintNovelBatch();
  });
  all.id = NOVEL_BATCH_ALL_ID;
  bar.appendChild(all);

  var none = novelButton('清空勾选', '把勾去掉（不删东西）', function () {
    STATE.novelPicked = {};
    STATE.novelBatchArmed = null;
    repaintPicked();
    paintNovelBatch();
  });
  none.id = NOVEL_BATCH_NONE_ID;
  bar.appendChild(none);

  var armed = picked.length > 0 && STATE.novelBatchArmed === picked.join('|');
  var remove = novelButton(
    armed ? '确认删除 ' + picked.length + ' 篇' : '删除选中',
    armed
      ? '再点一下就从磁盘上删掉这 ' + picked.length + ' 份原文'
      : '把勾上的这几篇删掉（会先问一次）',
    function () {
      var names = pickedNames();
      if (names.length === 0) {
        novelHint('先勾上要删的篇目。', 'error');
        return;
      }
      var key = names.join('|');
      if (STATE.novelBatchArmed !== key) {
        STATE.novelBatchArmed = key;
        paintNovelBatch();
        return;
      }
      deletePicked(names);
    }
  );
  remove.id = NOVEL_BATCH_DELETE_ID;
  remove.dataset.tone = 'danger';
  if (armed) remove.dataset.armed = 'true';
  if (picked.length === 0) remove.disabled = true;
  bar.appendChild(remove);
  return bar;
}

// 批量删除：宿主一次只删一篇（novels/delete 接一个名字，见 server.py 的 novels_delete），
// 所以这里串着一篇一篇来 —— 但不假装它是一件事：哪几篇删掉了、哪几篇没删成（连着原因）
// 最后如实报一句。中途不停：一篇删不动不该把后面几篇一起卡住。
function deletePicked(names) {
  if (!names || names.length === 0) return null;
  STATE.novelBatchArmed = null;
  novelHint('正在删这 ' + names.length + ' 篇…', 'info');
  var done = [];
  var failed = [];
  var step = function (index) {
    if (index >= names.length) {
      STATE.novelPicked = {};
      var note =
        done.length > 0 ? '删了 ' + done.length + ' 篇：' + done.join('、') : '一篇都没删成。';
      if (failed.length > 0) {
        note +=
          '；没删成 ' +
          failed.length +
          ' 篇：' +
          failed
            .map(function (item) {
              return item.name + '（' + item.reason + '）';
            })
            .join('、');
      }
      // 提示留到最后这一句：loadNovels 自己会把提示改回"目录里有几篇"，
      // 所以删完的结果得等它列完再写上去（不然立刻被盖掉）。
      // 批量那一栏也要重画：勾清掉了，可它上面那行字是上一轮画的 —— 不重画就还写着"选中 N 篇"，
      // 再点一下删除就会拿已经不存在的名字去问宿主。paintNovels 只管列表，不管这一栏。
      return Promise.resolve(loadNovels()).then(function () {
        paintNovelBatch();
        novelHint(note, failed.length > 0 ? 'error' : 'info');
        return null;
      });
    }
    var name = names[index];
    return Promise.resolve(bridge.request('novels/delete', { name: name })).then(
      function (response) {
        if (!response || response.ok !== true) {
          failed.push({
            name: name,
            reason: ((response && response.error) || {}).message || '未知错误'
          });
        } else {
          done.push(name);
          // 打开着的那一篇被删了：阅读区得收掉，不然屏幕上还摊着一份已经不存在的原文。
          closeNovel(name);
        }
        return step(index + 1);
      },
      function (err) {
        failed.push({ name: name, reason: message(err) });
        return step(index + 1);
      }
    );
  };
  return step(0);
}

// ---- 左栏：章节目录与全文搜索 ------------------------------------------

// 这一栏是"读一篇"的导航，默认开着（STATE.novelSideOpen）。切章和跳搜索命中是同一件事：
// 宿主给一个**字符 offset**，拿去调 openNovel —— 面板自己不算位置，因为切章与搜字用的
// 是宿主那一份解好的正文（lib/comfy_studio/novels.py 的 _text），口径只有一个，对不上
// 就是静默跳错地方。
//
// 目录要把整篇扫一遍才切得出来，所以头一次点会等一下；扫完正文留在宿主的缓存里，
// 翻章、再点一遍都快。因此"关掉再打开"不重新问一遍（见 toggleNovelToc）：那是同一个答案。

// 这一栏的显隐只由两件事决定：用户开着它没有、当前有没有打开一篇。
// （没打开任何一篇时那一栏没有意义：一棵不属于任何书的树，比空着更让人糊涂。）
function applyNovelSide() {
  var side = document.getElementById(NOVEL_SIDE_ID);
  var opened = STATE.novelSideOpen === true && !!STATE.novelOpen;
  if (side) side.dataset.open = opened ? '1' : '0';
  var toc = document.getElementById(NOVEL_TOC_ID);
  if (toc) toc.dataset.active = STATE.novelSideOpen === true ? 'true' : 'false';
}

// 左栏这一趟的回话还算不算数：得还是这一篇、票还是最新那张。
// 跟列表、正文那两处一个道理 —— 连着点两章、或者点完章立刻搜索，回话会乱序。
function novelSideCurrent(name, ticket) {
  var side = STATE.novelSide;
  return !!side && side.name === name && side.token === ticket;
}

function toggleNovelToc() {
  if (!STATE.novelOpen) {
    // 没打开哪一篇时这一栏没有意义：说清该先干什么，而不是画一棵空树。
    novelHint('先点上面某一行的「读」打开一篇，左边这栏才有它的目录。', 'info');
    return;
  }
  STATE.novelSideOpen = STATE.novelSideOpen !== true;
  applyNovelSide();
  if (!STATE.novelSideOpen) return;
  var side = STATE.novelSide;
  var ready =
    !!side &&
    side.name === STATE.novelOpen.name &&
    !side.loading &&
    !side.error &&
    ((side.mode === 'search' && side.matches) || (side.mode !== 'search' && side.chapters));
  // 已经拿到过这一篇的目录/搜索结果就不再问一遍：切章要整篇扫一遍，而答案不会变。
  if (!ready) loadChapters(STATE.novelOpen.name);
}

// 切这一篇的章节目录。整篇扫一遍，长篇小说头一次会等一下 —— 先把它画成"正在切"。
function loadChapters(name) {
  var side = STATE.novelSide;
  if (!side || side.name !== name) {
    side = emptyNovelSide(name);
    STATE.novelSide = side;
  }
  side.mode = 'toc';
  side.query = '';
  side.matches = null;
  side.error = '';
  side.loading = true;
  side.token = (side.token || 0) + 1;
  var ticket = side.token;
  paintNovelSide();
  return Promise.resolve(bridge.request('novels/chapters', { name: name })).then(
    function (response) {
      if (!novelSideCurrent(name, ticket)) return null;
      side.loading = false;
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        side.chapters = null;
        side.meta = null;
        // 错在哪儿要写在那一栏里（而不是只更新状态行）：用户的眼睛就在那儿，
        // 而且失败之后那一栏是空的，空着不说为什么等于让人再点一遍。
        side.error = '切不出目录: ' + (error.message || '未知错误');
        paintNovelSide();
        return null;
      }
      var result = response.result || {};
      side.chapters = result.chapters || [];
      side.meta = result;
      paintNovelSide();
      return result;
    },
    function (err) {
      if (!novelSideCurrent(name, ticket)) return null;
      side.loading = false;
      side.chapters = null;
      side.meta = null;
      side.error = '切不出目录: ' + message(err);
      paintNovelSide();
      return null;
    }
  );
}

// 在这一篇里找一串字，把位置列到左栏上（点一条就跳过去）。
function searchNovel(name, query) {
  var side = STATE.novelSide;
  if (!side || side.name !== name) {
    side = emptyNovelSide(name);
    STATE.novelSide = side;
  }
  side.mode = 'search';
  side.query = query;
  side.matches = null;
  side.meta = null;
  side.error = '';
  side.loading = true;
  side.token = (side.token || 0) + 1;
  var ticket = side.token;
  paintNovelSide();
  return Promise.resolve(bridge.request('novels/search', { name: name, query: query })).then(
    function (response) {
      if (!novelSideCurrent(name, ticket)) return null;
      side.loading = false;
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        side.matches = null;
        side.error = '找不到: ' + (error.message || '未知错误');
        paintNovelSide();
        return null;
      }
      var result = response.result || {};
      side.matches = result.matches || [];
      side.meta = result;
      paintNovelSide();
      return result;
    },
    function (err) {
      if (!novelSideCurrent(name, ticket)) return null;
      side.loading = false;
      side.matches = null;
      side.error = '找不到: ' + message(err);
      paintNovelSide();
      return null;
    }
  );
}

// 搜索框那一下：搜的是**当前打开的那一篇**（左栏讲的是它，不是列表里选中的那一行）。
function searchNovelFromForm() {
  var input = document.getElementById(NOVEL_SEARCH_ID);
  if (!input) return null;
  if (!STATE.novelOpen) {
    novelHint('先在列表里点「读」打开一篇，再在它里面找。', 'info');
    return null;
  }
  // 原样搜，不去首尾空白：宿主那边只认字面（题字里带空格的情况是有的），
  // 面板"顺手"帮人 trim 一下，就会给出一个他没要的位置。
  var query = input.value || '';
  if (query.replace(/\\s/g, '') === '') {
    novelHint('要搜的字不能是空的。', 'error');
    input.focus();
    return null;
  }
  return searchNovel(STATE.novelOpen.name, query);
}

function emptyNovelSide(name) {
  return {
    name: name,
    mode: 'toc',
    query: '',
    token: 0,
    loading: false,
    error: '',
    chapters: null,
    matches: null,
    meta: null
  };
}

function paintNovelSide() {
  var head = document.getElementById(NOVEL_SIDE_HEAD_ID);
  var list = document.getElementById(NOVEL_SIDE_LIST_ID);
  if (!head || !list) return;
  var side = STATE.novelSide;
  var label = head.querySelector('.cs-novel-side-title');
  var back = document.getElementById(NOVEL_TOC_BACK_ID);
  // 「返回目录」只在搜索结果那一屏露出来：目录那一屏上它没有去处。
  if (back) back.style.display = side && side.mode === 'search' ? '' : 'none';
  list.textContent = '';
  if (label) label.textContent = '目录';
  if (!STATE.novelOpen || !side) {
    list.appendChild(novelEmpty('打开一篇，这里就是它的目录。'));
    return;
  }
  if (side.error) {
    if (label) label.textContent = '这一栏没读出来';
    list.appendChild(novelEmpty(side.error));
    return;
  }
  if (side.loading) {
    if (label) label.textContent = side.mode === 'search' ? '正在找…' : '正在切章节…';
    list.appendChild(novelEmpty('…'));
    return;
  }
  if (side.mode === 'search') {
    paintSearchRows(side, list);
    return;
  }
  paintChapterRows(side, list);
}

// 目录那一行的话（"几章 · 多少字 · 读到第几章 · 有没有被截"）。单独拎出来是因为它有**两个**
// 更新的时机：重建这一栏时（paintChapterRows）与翻页/跳章之后（markCurrentChapter）—— 只写在
// 其中一处，跳到第二章时那一行还在说"读到第 1 章"。
// 字数是宿主的数（meta.total_chars 与每章的 chars，见 novels.py 的 chapters）：面板不自己去量
// 正文 —— 量出来的跟宿主报的对不上，人先怀疑的是这个面板。
function chapterLabel(side, at) {
  var chapters = side.chapters || [];
  var meta = side.meta || {};
  return (
    '目录 · ' + (meta.count || chapters.length) + ' 章' +
    (meta.total_chars ? ' · ' + meta.total_chars + ' 字' : '') +
    (at >= 0 ? ' · 读到第 ' + (at + 1) + ' 章' : '') +
    (meta.truncated === true ? '（只列了前 ' + meta.returned + ' 章）' : '')
  );
}

function paintChapterRows(side, list) {
  var chapters = side.chapters || [];
  var meta = side.meta || {};
  var label = document.querySelector('#' + NOVEL_SIDE_HEAD_ID + ' .cs-novel-side-title');
  var at = STATE.novelOpen ? currentChapterIndex(chapters, STATE.novelOpen.offset) : -1;
  if (label) label.textContent = chapterLabel(side, at);
  // 切不出章节不是失败（宿主回的是"整行标题一条也没认出来"）：照它说，别画一棵空树。
  // 那条路下面仍然有「全文」一条，所以翻页不会因此断路。
  if (meta.message) list.appendChild(novelEmpty(meta.message));
  chapters.forEach(function (chapter) {
    var row = document.createElement('button');
    row.type = 'button';
    row.className = 'cs-novel-side-row';
    row.dataset.index = String(chapter.index);
    row.dataset.offset = String(chapter.offset);
    row.title = '跳到这一章（第 ' + chapter.offset + ' 字起）';
    var title = document.createElement('span');
    title.textContent = chapter.title;
    row.appendChild(title);
    var size = document.createElement('span');
    size.className = 'cs-novel-side-meta';
    // 这一章占全篇多少：条形与"X 字"用的是同一对数（chapter.chars / meta.total_chars），
    // 只是把比例画出来 —— 判据仍然是宿主给的，面板没有多算一个数。
    var total = Number(meta.total_chars) || 0;
    var share = total > 0 ? (Number(chapter.chars) || 0) / total * 100 : 0;
    size.textContent = chapter.chars + ' 字' + (total > 0 ? ' · ' + Math.round(share) + '%' : '');
    row.appendChild(size);
    if (total > 0) {
      var bar = document.createElement('span');
      bar.className = 'cs-novel-side-bar';
      var fill = document.createElement('span');
      fill.className = 'cs-novel-side-bar-fill';
      fill.style.width = share.toFixed(2) + '%';
      bar.appendChild(fill);
      row.appendChild(bar);
    }
    row.addEventListener('click', function () {
      openNovel(side.name, chapter.offset);
    });
    list.appendChild(row);
  });
  // 建完就把"正在读的是哪一章"标上：跳过去之后不标，人在目录里就找不着自己在哪儿。
  markCurrentChapter();
}

function paintSearchRows(side, list) {
  var matches = side.matches || [];
  var meta = side.meta || {};
  var label = document.querySelector('#' + NOVEL_SIDE_HEAD_ID + ' .cs-novel-side-title');
  if (label) {
    label.textContent =
      '“' + side.query + '” · ' + matches.length + ' 处' +
      (meta.truncated === true ? '（只列了前 ' + meta.limit + ' 处）' : '');
  }
  if (!matches.length) {
    list.appendChild(novelEmpty('这一篇里没有“' + side.query + '”。'));
    return;
  }
  matches.forEach(function (match) {
    var row = document.createElement('button');
    row.type = 'button';
    row.className = 'cs-novel-side-row';
    row.dataset.offset = String(match.offset);
    // 片段是宿主给的（命中处前后各一小段，见 novels.py 的 _snippet）：面板自己截正文
    // 拼一句上下文，就跟宿主的口径分了家。
    row.textContent = match.snippet;
    row.title = '跳到这一处（第 ' + match.offset + ' 字）';
    row.addEventListener('click', function () {
      openNovel(side.name, match.offset);
    });
    list.appendChild(row);
  });
}

// 读的是第几章：最后一个 offset 不大于当前页起点的章节（章节目录是按下标递增的）。
function currentChapterIndex(chapters, offset) {
  var found = -1;
  for (var index = 0; index < chapters.length; index += 1) {
    if (chapters[index].offset <= offset) found = index;
    else break;
  }
  return found;
}

// 翻页、跳章之后把"正在读哪一章"挪一下。只动那两个标记，不重建这一栏：
// 长篇小说上有几千章，每翻一页把几千个按钮重画一遍是白费的，滚动位置还会被弹回去。
function markCurrentChapter() {
  var list = document.getElementById(NOVEL_SIDE_LIST_ID);
  var side = STATE.novelSide;
  if (!list || !side || side.mode !== 'toc' || !side.chapters) return;
  var offset = STATE.novelOpen ? STATE.novelOpen.offset : 0;
  var current = currentChapterIndex(side.chapters, offset);
  // 那一行"读到第几章"跟着一起走：只在重建这一栏时写它，翻页之后它就成了一句假话。
  var label = document.querySelector('#' + NOVEL_SIDE_HEAD_ID + ' .cs-novel-side-title');
  if (label) label.textContent = chapterLabel(side, current);
  var rows = list.querySelectorAll('.cs-novel-side-row');
  for (var index = 0; index < rows.length; index += 1) {
    if (index === current) {
      if (rows[index].dataset.current !== 'true') {
        rows[index].dataset.current = 'true';
        // block:'nearest'：本来就在眼前就不动它，省得每翻一页整栏都跳一下。
        if (rows[index].scrollIntoView) rows[index].scrollIntoView({ block: 'nearest' });
      }
    } else if (rows[index].dataset.current === 'true') {
      delete rows[index].dataset.current;
    }
  }
}

// 读一篇的一页。offset 是第几个**字**（0 起，宿主按字符分页，见 lib/comfy_studio/novels.py）：
// 面板这边绝不去算字节 —— UTF-8 是变长的，算错了就会把汉字劈成两半。
function openNovel(name, offset) {
  var reader = document.getElementById(NOVEL_READER_ID);
  if (!reader) return null;
  var open = STATE.novelOpen;
  if (!open || open.name !== name) {
    // 换了一篇（不是翻页）：正文区先清掉。留着上一篇的字，人会以为自己点的那本已经打开了。
    open = { name: name, offset: 0, page: null, token: 0 };
    STATE.novelOpen = open;
    reader.textContent = '正在读 ' + name + ' …';
    var pager = document.getElementById(NOVEL_PAGER_ID);
    if (pager) pager.textContent = '';
    // 列表那一行要跟着变粗（[data-open="true"]）：只重画名字那一格，别整表重建，
    // 否则"点了读"之后滚动位置会跳回顶上。
    if (STATE.novels) paintNovels(STATE.novels);
    // 左栏里那份目录属于上一篇：留着它，点下去会跳到另一本书的某个字上（宿主那边直接报
    // "没有这一篇"，但屏幕上先显示的是一棵对不上号的树）。
    if (STATE.novelSide && STATE.novelSide.name !== name) STATE.novelSide = null;
    applyNovelSide();
    // 换了一篇就把新那篇的目录拿来。这一栏没开着就不问 —— 那是白白整篇扫一遍。
    if (STATE.novelSideOpen === true) loadChapters(name);
    else paintNovelSide();
  }
  // 连点翻页时的票，跟列表那条一个道理：不是最新那趟的回话，一个字都不许往正文区里写。
  open.token = (open.token || 0) + 1;
  var ticket = open.token;
  return Promise.resolve(
    bridge.request('novels/read', { name: name, offset: offset })
  ).then(
    function (response) {
      if (!STATE.novelOpen || STATE.novelOpen.name !== name || STATE.novelOpen.token !== ticket) {
        return null;
      }
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        // 宿主给的原因可能是一整段（认不出编码这类，里面要写清试过哪几种、该怎么办）：
        // 整段放正文区那个大地方，状态行只报是哪一篇读不了 —— 一行里塞一整段，谁也读不完。
        var reason = error.message || '未知错误';
        reader.textContent = '读不了这一篇: ' + reason;
        novelHint('读不了 ' + name + '：原因写在正文区', 'error');
        return null;
      }
      var page = response.result || {};
      STATE.novelOpen.offset = page.offset || 0;
      STATE.novelOpen.page = page;
      paintNovelPage(page);
      return page;
    },
    function (err) {
      if (!STATE.novelOpen || STATE.novelOpen.name !== name || STATE.novelOpen.token !== ticket) {
        return null;
      }
      reader.textContent = '读不了这一篇: ' + message(err);
      novelHint('读不了 ' + name + ': ' + message(err), 'error');
      return null;
    }
  );
}

function paintNovelPage(page) {
  var reader = document.getElementById(NOVEL_READER_ID);
  var pager = document.getElementById(NOVEL_PAGER_ID);
  if (!reader || !pager) return;
  var text = typeof page.text === 'string' ? page.text : '';
  reader.textContent = text === '' ? '（这一篇到这里就完了）' : text;
  // 翻页要停在页首，不然下一页一出来就停在半中间，读起来得像倒着走。
  reader.scrollTop = 0;

  pager.textContent = '';
  var name = page.name || '';
  var start = page.offset || 0;
  var end = start + (page.chars || 0);
  // 页长用宿主**这一次实际要了多少字**（requested_chars），不是这一页的正文长度（chars）：
  // 末页比一页短，拿正文长度退回去会退不够，"上一页"就落在半中间。页长由宿主给，面板不再自己定。
  var step = typeof page.requested_chars === 'number' ? page.requested_chars : 0;
  var back = novelButton('上一页', '往回翻一页', function () {
    openNovel(name, Math.max(0, start - step));
  });
  if (start <= 0 || step <= 0) back.disabled = true;
  var next = novelButton('下一页', '接着往下翻一页', function () {
    openNovel(name, start + step);
  });
  if (page.at_end === true || step <= 0) next.disabled = true;
  pager.appendChild(back);
  pager.appendChild(next);
  // 「引用」：把选中的那段原文带到对话去（没选就引这一页开头的一段，两种都当场说明）。
  pager.appendChild(
    novelButton('引用', '把正文里选中的那段带到对话去（没选就引用这一页开头的一段）', function () {
      quoteFromReader();
    })
  );

  var pos = document.createElement('span');
  pos.className = 'cs-novel-pos';
  pos.textContent =
    '第 ' + start + '–' + end + ' 字 / 共 ' + (page.total_chars || 0) + ' 字' +
    '（' + formatBytes(page.bytes) + '）';
  pager.appendChild(pos);
  // 编码只在**不是 UTF-8** 时说出来：那是"宿主替你认了另一种编码"这件事本身，值得写在脸上
  // （中文网文多是 GB18030）。UTF-8 是默认档，写出来只是噪音。
  var encoding = page.encoding && page.encoding !== 'utf-8' ? ' · ' + page.encoding : '';
  novelHint(
    name + ' · ' + formatTime(page.mtime) + encoding + (page.at_end === true ? ' · 已到末尾' : ''),
    'info'
  );
  // 正文已经翻到/跳到别处了，左栏里"正在读哪一章"得跟着走（见 markCurrentChapter）。
  markCurrentChapter();
}

// 把某一篇从正文区里收掉：它已经被删掉了，或者刚被另一份同名文件覆盖了。
// 留着字，人会以为文件还在（列表明明写着换成了新的，正文却还是旧的，等于拿两份不同的字给人看）。
// 传名字而不是无条件清空：在读的是别的篇时，那篇不该受影响。
function closeNovel(name) {
  if (!STATE.novelOpen || STATE.novelOpen.name !== name) return;
  STATE.novelOpen = null;
  var reader = document.getElementById(NOVEL_READER_ID);
  if (reader) reader.textContent = '选中上面一篇，正文显示在这里。';
  var pager = document.getElementById(NOVEL_PAGER_ID);
  if (pager) pager.textContent = '';
  // 左栏讲的是"正开着的那一篇"：那一篇收掉了，它就没有主语了（下次打开别的篇会重切）。
  STATE.novelSide = null;
  applyNovelSide();
  paintNovelSide();
}

// 把导入表单上那几个控件开关起来。请求在飞的时候必须关：粘着路径连点两下「导入」，
// 同一份文件会被拷两遍（第二遍是覆盖），用户看到的却像只点了一下。
function setNovelFormEnabled(enabled) {
  var form = document.getElementById(NOVEL_FORM_ID);
  if (!form) return;
  var controls = form.querySelectorAll('input, button');
  for (var index = 0; index < controls.length; index += 1) {
    controls[index].disabled = !enabled;
    // 「覆盖导入」的显隐是另一回事（由 showOverwrite 管 display），这里只动 disabled：
    // 关表单不会把藏着的那个按钮露出来，重新打开也不会替它做"该不该露"的决定。
  }
}

function importNovel(overwrite) {
  var path = document.getElementById(NOVEL_PATH_ID);
  if (!path) return null;
  var source = (path.value || '').trim();
  if (source === '') {
    importHint('先粘一份本机 txt/md 的绝对路径。', 'error');
    path.focus();
    return null;
  }
  setNovelFormEnabled(false);
  importHint('正在把 ' + source + (overwrite ? ' 覆盖进来…' : ' 接进原文目录…'), 'info');
  return Promise.resolve(
    bridge.request('novels/import', { path: source, overwrite: overwrite === true })
  ).then(
    function (response) {
      setNovelFormEnabled(true);
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        // 路径不对、不是 txt/md、拷不动 —— 都是"这一次没成"，不是"结果里有话要说"。
        showOverwrite(false);
        importHint('没导进来: ' + (error.message || '未知错误'), 'error');
        return null;
      }
      var result = response.result || {};
      if (result.imported !== true) {
        // 同名不是错误：宿主回的是 {imported:false, reason:"exists"}，是"要你确认一下"。
        // 这时候才把「覆盖导入」露出来 —— 而且只对着刚问过的那条路径，改了路径就收回
        // （见 NOVEL_PATH_ID 的 input 监听）。
        showOverwrite(true);
        importHint(result.message || '原文目录里已经有这一本了：要换成你这份就点「覆盖导入」', 'info');
        return result;
      }
      showOverwrite(false);
      path.value = '';
      // 这一趟做完了就把弹窗收掉：结果（接进来哪一份、目录在哪）写在页顶那条提示与列表里，
      // 弹窗继续举着只会挡住刚更新出来的那一列。
      toggleNovelForm(false);
      var note =
        (result.overwritten === true ? '换成了 ' : '接进来了 ') +
        result.name +
        '（' + formatBytes(result.bytes) + '）' +
        (result.created_dir === true ? ' —— 原文目录是这一下建出来的' : '');
      // 导完把列表重列一遍：目录里多了一份（或者少了一份旧的、多了个新的）。
      closeNovel(result.name);
      loadNovels(note);
      return result;
    },
    function (err) {
      setNovelFormEnabled(true);
      showOverwrite(false);
      importHint('没导进来: ' + message(err), 'error');
      return null;
    }
  );
}

function deleteNovel(name) {
  // 已经点到第二步了：先把"待确认"收回去，别让请求还在飞的时候界面上还举着红按钮
  // （那会让人以为是点漏了，接着再点一下）。
  STATE.novelDeleteArmed = null;
  novelHint('正在删 ' + name + ' …', 'info');
  return Promise.resolve(bridge.request('novels/delete', { name: name })).then(
    function (response) {
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        var reason = error.message || '未知错误';
        loadNovels('删不掉 ' + name + ': ' + reason);
        return null;
      }
      var result = response.result || {};
      // 删掉的正好是开着的那一篇：正文区跟着收掉（磁盘上已经没有这份原文了）。
      closeNovel(name);
      loadNovels('删掉了 ' + name + '（' + formatBytes(result.bytes) + '）');
      return result;
    },
    function (err) {
      loadNovels('删不掉 ' + name + ': ' + message(err));
      return null;
    }
  );
}

// "拿去对话"：把这句话写进对话输入框，然后**停手**。面板不替人按发送 —— 拿哪一篇开工、
// 怎么开工是用户的事，替他发出去等于替他下了这个决定（而且删掉的原文可撤不回来）。
function novelToChat(row) {
  switchView('chat');
  var input = document.getElementById(INPUT_ID);
  if (!input) return;
  var line = '用原文「' + row.name + '」开工';
  if ((input.value || '').trim() === '') {
    input.value = line;
  } else {
    // 人家可能正打着半句话：接着往下写一行，别覆盖掉。
    // 这一段 JS 住在 TS 模板字符串里，反斜杠要写两遍：只写一遍的话，转义会被模板那层
    // 先吃掉（正则变成 s，换行变成一个真换行、把字符串截断）—— 跟上面 NOVEL_PATH_ID
    // 的 placeholder 是同一个坑。
    input.value = input.value.replace(/\\s+$/, '') + '\\n' + line;
  }
  input.focus();
  setStatus('已把「' + row.name + '」写进对话框：添上要求再发。');
}

// 「以此立项」：拿这一篇当原著，跳到「项目管理」把建项目的表单打开、剧名与原著都填好，
// 然后**停手** —— 集数、要不要补齐落点都还得人来定，替他按下「建」就等于替他建了一堆目录。
// 三页之间就靠这类动作互相接上：小说页出的是"哪一篇"，项目页出的是"这部戏的格子"。
function novelToProject(row) {
  switchView('project');
  // 走弹窗那一套开关打开（内含：清掉上一次那句话、把光标放进剧名）。
  // 这里**不**顺手 fillNovelOptions：下面那趟是有序的 —— 先填下拉、再选中这一篇；
  // 两趟并在一起时，后回来的那趟会把已经选中的冲掉。
  toggleProjectForm(true);
  var name = document.getElementById(PROJECT_FORM_NAME_ID);
  // 剧名默认去掉扩展名（"斗破苍穹.txt" → "斗破苍穹"）：剧名就是目录名，
  // 带着 .txt 建出来的目录一眼就是机器随手起的。
  var title = String(row.name || '').replace(/\\.[^.]+$/, '');
  if (name) name.value = title;
  var novel = document.getElementById(PROJECT_FORM_NOVEL_ID);
  // 顺序不能反：原著下拉是现填的（原文库别的程序也会动），先选中会被重填冲掉。
  return Promise.resolve(fillNovelOptions()).then(function () {
    if (novel) novel.value = row.name;
    projectHint('拿「' + row.name + '」当原著开一部戏：集数填好就按「建」。', 'info');
    return title;
  });
}

// ---- 项目管理 ----------------------------------------------------------
//
// 漫剧那套流程的**资料面**：剧本、对白与配音、资产索引与台账、流程与进度、交付与出图、
// 素材归档、世界观、角色/服装/道具、场景/表情/姿态、分镜与镜头、一致性与音频 —— 各占一格，
// 全部住在 manju/projects/<剧名>/ 下。这一页就是那一堆目录的前台：列出这部戏、看它的格子
// 齐不齐、阶段到哪一步、把某份资料点开读一读、再把"这部戏现在什么样"写进对话。
//
// 格子的清单**一份都不抄**：宿主 projects/tree 回来的 shelves / dirs / stages 就是全部，
// 这里只负责画。抄一份的下场不是报错，是两边悄悄分家（规范里加了一格，面板上永远少一格，
// 而谁都不报错）—— 所以连"阶段判据"都是宿主那边 manju 工作流 src/project.py 的代码。
//
// 路径一个都不拼：项目根由宿主给（host/info 的 project_dir，默认
// <comfyui-dir>/custom_nodes/comfy_studio/manju/projects，见 lib/comfy_studio/projects.py）。
//
// 与「管理小说」那页的分工：小说那页管**原文**（拆章、搜索、引用），这页管**为这部剧备下的
// 资料**。两页在同两处接上：① 建项目时从原文库里挑一本原著，登记进
// 00_PROJECT/07_素材归档/素材来源登记.md（只登记、不覆盖别人填过的 —— 那是来源记录）；
// ② 选中一部剧能把它现在的样子写成一段话放进对话输入框（人改完自己发，面板不替人按发送）。
//
// 这一页自己只记三样：列表那趟的票、正开着的是哪一部（含 tree 那趟的票、正读哪份文件）、
// 以及正读的那份读到第几页。票是为了"慢回话别盖掉新界面"。

// 这一页的提示行：文案是这一页的事，语气交给 hintLine（三页同一套）。
// 建项目弹窗盖住了页顶这条，所以同一句话要在卡片里也写一份（弹窗自己那条 hint）——
// 这是**一个调用写两处**，不是一个来源变两个：文案与语气还是只在这里定。
function projectHint(text, tone) {
  hintLine(PROJECT_FORM_HINT_ID, text, tone);
  return hintLine(PROJECT_HINT_ID, text, tone);
}

// 建项目弹窗的开关：脾气交给 togglePopup（那一份是两页共用的），这里只说清是哪一个弹窗、
// 打开时光标该落在剧名那一格。
function toggleProjectForm(open) {
  return togglePopup(PROJECT_FORM_ID, PROJECT_FORM_HINT_ID, PROJECT_FORM_NAME_ID, open);
}

function projectButton(label, title, onClick) {
  var button = document.createElement('button');
  button.type = 'button';
  button.className = 'cs-proj-btn';
  button.textContent = label;
  button.title = title || '';
  button.addEventListener('click', onClick);
  return button;
}

function projectEmpty(text) {
  var empty = document.createElement('div');
  empty.className = 'cs-proj-empty';
  empty.textContent = text;
  return empty;
}

// ---- 流水线（S0–S7 接到随包那七位智能体上）-------------------------------
//
// 这一页是"从小说到成片"那条链的**按键处**。阶段表、每段谁做、产出落哪儿、要不要回引擎侧渲染
// （第一步只出提示词，图/视频/音频得回引擎里出），全部来自宿主 pipeline/plan 那一趟回话 ——
// 形状与对话里 pipeline__plan 是同一份（见 lib/comfy_studio/pipeline.py 的 plan_payload）。
// **面板不自己写一张阶段表**：抄一份就会跟宿主分家，而分家的表现是"面板上写着还差 S4、
// 模型说早跑完了"，两边都不报错，只有人白等一场。
//
// 跑起来之后宿主一段一段推 pipeline/event（start / stage_start / stage / finished），
// 这一页拿它们逐段改卡片。**进度不靠轮询**：一段跑十几分钟，轮询要么太吵要么太钝；
// 而这几条通知就是 run 自己 emit 出来的，与它落进度账的时机同源。

// 这一页的提示行：文案是这一页的事，语气交给 hintLine（全页同一套）。
// 确认卡盖住了页顶那条，所以同一句话在卡片里也写一份 —— 一个调用写两处，不是一个来源变两个。
function pipelineHint(text, tone) {
  hintLine(PIPELINE_FORM_HINT_ID, text, tone);
  return hintLine(PIPELINE_HINT_ID, text, tone);
}

// 一段的归宿 → 卡片上那枚签（文字 + 语气）。归宿不只靠颜色：签本身就写着字，色盲或黑白打印
// 都分得出来。status 是宿主报的那几个码（见 pipeline.py 的 STATUS_DONE / STATUS_SKIPPED /
// STATUS_FAILED），认不出来就照原样写出来 —— 没见过的码是宿主那边新加的，
// 藏起来只会让人以为这一段压根没跑。
function pipeChip(status) {
  if (status === 'running') return projectChip('跑着…', 'action');
  if (status === 'done') return projectChip('跑过了', '');
  if (status === 'skipped') return projectChip('跳过', '');
  if (status === 'failed') return projectChip('栽了', 'warn');
  if (status) return projectChip(String(status), 'warn');
  return projectChip('还没跑', 'zero');
}

// 一段一张卡：阶段号、名字、归宿、谁做、产出落哪儿。
// 归宿先看这一趟跑出来的（run），没有再退回进度账（past）—— 跑的时候进度账还没落盘，
// 只看进度账的话，正在跑的那一段永远写着"还没跑"。
function pipeStageCard(stage, run, past) {
  var code = String(stage.code || '');
  var live = run && run[code] ? run[code] : null;
  var done = past && past[code] ? past[code] : null;
  var status = live ? live.status : done ? done.status : '';

  var card = document.createElement('div');
  card.className = 'cs-pipe-stage';
  card.dataset.code = code;
  card.dataset.status = status || 'todo';

  var head = document.createElement('div');
  head.className = 'cs-pipe-head';
  var codeEl = document.createElement('span');
  codeEl.className = 'cs-pipe-code';
  codeEl.textContent = code;
  var nameEl = document.createElement('span');
  nameEl.className = 'cs-pipe-name';
  nameEl.textContent = String(stage.name || '');
  head.appendChild(codeEl);
  head.appendChild(nameEl);
  head.appendChild(pipeChip(status));
  card.appendChild(head);

  // 谁做 = 随包那七位里的哪一位；没接智能体的段写它自己的模块名（宿主给的 owner）。
  var bits = ['谁做：' + String(stage.actor || stage.agent || stage.owner || '—')];
  bits.push('落点：' + String(stage.artifact || '—'));
  if (stage.needs_render === true) bits.push('跑完还要回引擎侧出图/视频/音频');
  var meta = document.createElement('div');
  meta.className = 'cs-pipe-meta';
  meta.textContent = bits.join(' · ');
  card.appendChild(meta);

  var note = '';
  var tone = '';
  if (live) {
    if (live.error) {
      note = String(live.error);
      tone = 'error';
    } else if (live.note) {
      note = String(live.note);
    }
    if (live.render_pending === true) {
      note = (note ? note + ' · ' : '') + '这一步只出了提示词，图/视频得回引擎侧出';
      tone = tone || 'warn';
    }
  } else if (done) {
    // 进度账上每段只有这四栏（status / artifact / at / error，见 pipeline.py 的 state）；
    // 没有 note —— 那是 run 那一刻的回话里的东西，账上不存。
    if (done.error) {
      note = String(done.error);
      tone = 'error';
    }
    if (done.at) note = (note ? note + ' · ' : '') + formatTime(done.at) + ' 跑的';
  }
  if (note) {
    var line = document.createElement('div');
    line.className = 'cs-pipe-note';
    line.textContent = note;
    if (tone) line.dataset.tone = tone;
    card.appendChild(line);
  }
  return card;
}

// 跑之前那张卡。它是**这一页自己的确认**，不是宿主 review 通道那一套：面板里按键的是人自己，
// 与对话里"模型想替人按"是两回事（后者才必须有人点头，见 pipeline.py 顶部那段）。但这一趟
// 一跑十几分钟、花的是模型的钱，所以按下去之前把话摆清：跑几段、跳几段、哪几段还得回引擎侧。
function buildPipelineRunForm() {
  var popup = buildPopup(PIPELINE_FORM_ID, PIPELINE_FORM_HINT_ID, '这一趟要跑的段');

  var text = document.createElement('div');
  text.id = PIPELINE_FORM_TEXT_ID;
  text.className = 'cs-pipe-note';
  popup.body.appendChild(text);

  // 起止段只在这张卡里给：页顶那条窄缝塞不下四个控件，而"只补中间某一段"是常事。
  var from = document.createElement('select');
  from.id = PIPELINE_FROM_ID;
  from.className = 'cs-proj-input';
  from.title = '从这一段起';
  var to = document.createElement('select');
  to.id = PIPELINE_TO_ID;
  to.className = 'cs-proj-input';
  to.title = '跑到这一段为止';
  popup.body.appendChild(popupField('从哪一段起', from));
  popup.body.appendChild(popupField('跑到哪一段', to));

  var force = document.createElement('input');
  force.type = 'checkbox';
  force.id = PIPELINE_FORCE_ID;
  force.title = '不勾就是跳过：产物还在的段不重做';
  var forceLabel = document.createElement('label');
  forceLabel.className = 'cs-popup-check';
  forceLabel.appendChild(force);
  var forceText = document.createElement('span');
  forceText.textContent = '跑过的也重做（默认跳过产物还在的段）';
  forceLabel.appendChild(forceText);
  popup.body.appendChild(forceLabel);

  popup.actions.appendChild(
    projectButton('先别跑', '退出去，什么都不做', function () {
      togglePopup(PIPELINE_FORM_ID, PIPELINE_FORM_HINT_ID, null, false);
    })
  );
  var go = projectButton('继续跑', '从这一段起往下跑；跑的时候这一页逐段亮起来', function () {
    runPipeline();
  });
  go.dataset.primary = '1';
  popup.actions.appendChild(go);
  return popup.layer;
}

function buildPipelineView() {
  var view = document.createElement('div');
  view.id = PIPELINE_VIEW_ID;
  view.style.cssText = 'flex:1;min-height:0;display:none;flex-direction:column;';
  view.setAttribute('role', 'tabpanel');

  var bar = document.createElement('div');
  bar.className = 'cs-proj-bar';

  // 剧目：选项是宿主 projects/list 那一趟的行（哪个目录算一部戏是宿主判的，见 projects.py）。
  var project = document.createElement('select');
  project.id = PIPELINE_PROJECT_ID;
  project.className = 'cs-proj-input';
  project.title = '跑哪一部戏；换一部会自动重新看一遍计划';
  project.addEventListener('change', function () {
    STATE.pipelineProject = project.value || '';
    planPipeline();
  });
  bar.appendChild(project);

  // 原文：可选。留空就用项目里那份（S1 自己有默认落点）。
  var novel = document.createElement('select');
  novel.id = PIPELINE_NOVEL_ID;
  novel.className = 'cs-proj-input';
  novel.title = '这一部用哪篇原文（可选，留空就用项目里那份）';
  bar.appendChild(novel);

  // 集数：与建项目表单同一个默认（那边也是 12）。它只进提示词里的"目标集数"。
  var episodes = document.createElement('input');
  episodes.id = PIPELINE_EPISODES_ID;
  episodes.className = 'cs-proj-input';
  episodes.type = 'number';
  episodes.min = '1';
  episodes.max = '9999';
  episodes.value = '12';
  episodes.title = '目标集数：写进提示词，实际做多少集是你自己的事';
  bar.appendChild(episodes);

  bar.appendChild(
    projectButton('看计划', '问一遍宿主：这八段现在跑到哪儿了、哪几段跑完还得回引擎侧渲染', function () {
      planPipeline();
    })
  );
  bar.appendChild(
    projectButton('开跑…', '从没跑过的那一段往下跑；按之前先让你看一眼这一趟要跑几段、跳几段', function () {
      askPipelineRun();
    })
  );

  view.appendChild(bar);

  var hint = document.createElement('div');
  hint.id = PIPELINE_HINT_ID;
  hint.className = 'cs-proj-hint';
  hint.textContent = '';
  view.appendChild(hint);

  var overview = document.createElement('div');
  overview.id = PIPELINE_OVERVIEW_ID;
  overview.className = 'cs-proj-overview';
  view.appendChild(overview);

  var list = document.createElement('div');
  list.id = PIPELINE_LIST_ID;
  list.className = 'cs-pipe-list';
  view.appendChild(list);

  view.appendChild(buildPipelineRunForm());
  return view;
}

// 这一页三个请求共用的参数：剧目（必给）、原文（可选）、集数（可选）。
// 空的一律不带 —— 宿主那边缺省就是它自己的默认（见 pipeline.py 的 plan / run 签名）。
function pipelineArgs() {
  var params = {};
  var project = String(STATE.pipelineProject || '').trim();
  if (project) params.name = project;
  var novel = document.getElementById(PIPELINE_NOVEL_ID);
  if (novel && novel.value) params.novel = novel.value;
  var episodes = document.getElementById(PIPELINE_EPISODES_ID);
  var count = episodes ? parseInt(episodes.value, 10) : 0;
  if (count > 0) params.episodes = count;
  return params;
}

// 剧目与原文两个下拉：都从宿主现取（projects/list、novels/list），面板不存自己的一份清单 ——
// 存一份就得操心它什么时候过期，而"这部戏刚被删掉"这种事没人会记得同步。
// 已选中的那部戏留着：切页回来不该把挑好的东西丢掉；它已经不在列表里也照留，并写清
// "目录里没这一部"，让后面那句报错有的放矢，而不是悄悄换成另一部戏跑起来。
function loadPipelineOptions() {
  var projectSelect = document.getElementById(PIPELINE_PROJECT_ID);
  var novelSelect = document.getElementById(PIPELINE_NOVEL_ID);
  var keepProject = String(STATE.pipelineProject || '');
  var keepNovel = novelSelect ? novelSelect.value || '' : '';
  var asked = [bridge.request('projects/list', {}), bridge.request('novels/list', {})];
  return Promise.all(asked).then(function (answers) {
    var listed = answers[0] && answers[0].ok === true ? answers[0].result || {} : null;
    if (projectSelect && listed) {
      var rows = listed.projects || [];
      projectSelect.textContent = '';
      rows.forEach(function (row) {
        var option = document.createElement('option');
        option.value = row.name;
        option.textContent = row.name;
        projectSelect.appendChild(option);
      });
      if (!keepProject && rows.length) keepProject = rows[0].name;
      var listedNow = rows.some(function (row) {
        return row.name === keepProject;
      });
      if (keepProject && !listedNow) {
        var gone = document.createElement('option');
        gone.value = keepProject;
        gone.textContent = keepProject + '（项目目录里没这一部）';
        projectSelect.insertBefore(gone, projectSelect.firstChild);
      }
      projectSelect.value = keepProject;
      STATE.pipelineProject = keepProject;
    }
    var novels = answers[1] && answers[1].ok === true ? (answers[1].result || {}).novels || [] : [];
    if (novelSelect) {
      novelSelect.textContent = '';
      var none = document.createElement('option');
      none.value = '';
      none.textContent = novels.length ? '（用项目里那份原文）' : '原文库里没有原文（S1 会用它自己的落点）';
      novelSelect.appendChild(none);
      novels.forEach(function (row) {
        var option = document.createElement('option');
        option.value = row.name;
        option.textContent = row.name;
        novelSelect.appendChild(option);
      });
      if (keepNovel) novelSelect.value = keepNovel;
    }
    return true;
  });
}

// 切到这一页时走这一趟：先补两个下拉，再看计划。看计划没成也留着下拉 —— 下拉是它的前置条件，
// 而"挑哪一部戏"这件事跟"这一部跑到哪儿了"是两回事，后者失败不该把前者也收走。
function loadPipeline() {
  pipelineHint('正在看这一步跑到哪儿了…', 'info');
  return loadPipelineOptions().then(function () {
    if (!STATE.pipelineProject) {
      STATE.pipeline = null;
      STATE.pipelineStages = null;
      paintPipeline(null);
      pipelineHint('还没有可以跑的戏：先去「项目管理」那一页建一部，这里才有阶段表。', 'info');
      return null;
    }
    return planPipeline();
  });
}

// 问一遍宿主（pipeline/plan）要那张阶段表。票与 loadProjects 那一套同理：
// 连点两下、或者连着换几部戏，先发的请求后回来会把新计划盖成旧的。
function planPipeline() {
  var params = pipelineArgs();
  if (!params.name) {
    paintPipeline(null);
    pipelineHint('先挑一部戏。', 'error');
    return Promise.resolve(null);
  }
  STATE.pipelineToken = (STATE.pipelineToken || 0) + 1;
  var ticket = STATE.pipelineToken;
  // 上一趟（换戏之前那部）的实时归宿在这里作废：留着的话，新计划会顶着旧状态画出来。
  STATE.pipelineStages = null;
  pipelineHint('正在看「' + params.name + '」跑到哪儿了…', 'info');
  var asked = Promise.resolve(bridge.request('pipeline/plan', params));
  return asked.then(
    function (response) {
      if (STATE.pipelineToken !== ticket) return null;
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        STATE.pipeline = null;
        paintPipeline(null);
        pipelineHint('看不了计划：' + (error.message || '未知错误'), 'error');
        return null;
      }
      STATE.pipeline = response.result || null;
      paintPipeline(STATE.pipeline);
      pipelineHint('计划在这儿了。按「开跑…」之前先看一眼这一趟要跑哪几段。', 'info');
      return STATE.pipeline;
    },
    function (err) {
      if (STATE.pipelineToken !== ticket) return null;
      STATE.pipeline = null;
      paintPipeline(null);
      pipelineHint('看不了计划：' + message(err), 'error');
      return null;
    }
  );
}

// 画这一页：总览那一行 + 一段一张卡。payload 是 pipeline/plan 的回话，null 表示没得跑。
// 实时归宿（STATE.pipelineStages）在这里叠上去：跑着的时候进度账还没落盘，只看它就会
// 让正在跑的那一段一直写着"还没跑"。
function paintPipeline(payload) {
  var overview = document.getElementById(PIPELINE_OVERVIEW_ID);
  var list = document.getElementById(PIPELINE_LIST_ID);
  if (overview) overview.textContent = '';
  if (!list) return;
  list.textContent = '';
  var stages = (payload && payload.stages) || [];
  if (stages.length === 0) {
    list.appendChild(projectEmpty('这里还没有阶段表。'));
    return;
  }
  var past = (payload && payload.state) || {};
  var run = STATE.pipelineStages || null;
  var found = 0;
  stages.forEach(function (stage) {
    var live = run && run[stage.code] ? run[stage.code] : null;
    var was = past[stage.code] || null;
    var status = live ? live.status : was ? was.status : '';
    if (status === 'done') found += 1;
  });
  if (overview) {
    overview.appendChild(projectChip('跑过了 ' + found + '/' + stages.length + ' 段'));
    var waiting = (payload && payload.render_required) || [];
    if (waiting.length) {
      overview.appendChild(document.createTextNode(' '));
      overview.appendChild(
        projectChip('跑完还要回引擎侧出图/视频：' + waiting.join('、'), 'warn')
      );
    }
    if (payload && payload.novel) {
      overview.appendChild(document.createTextNode(' '));
      overview.appendChild(projectChip('原文：' + payload.novel));
    }
  }
  stages.forEach(function (stage) {
    list.appendChild(pipeStageCard(stage, run, past));
  });
}

// 按「开跑…」：手里有这一部的最新计划就直接用那份，没有才去问一趟 ——
// 每按一次都重问，人按下到看清字之间界面会白跳一下，而刚才看过的计划并没有过期。
function askPipelineRun() {
  var open = function (payload) {
    if (!payload) return null;
    fillPipelineRunForm(payload);
    togglePopup(PIPELINE_FORM_ID, PIPELINE_FORM_HINT_ID, PIPELINE_FROM_ID, true);
    return null;
  };
  if (STATE.pipeline && STATE.pipeline.project) return open(STATE.pipeline);
  return planPipeline().then(open);
}

// 填那张确认卡：一段话 + 起止段两个下拉。话里那几个数全出自 plan 的回话（跑过的段、待渲染的段），
// 面板不自己算 —— 自己算就得再判一次"哪一段算跑过"，而那个判据在宿主手里（产物在不在）。
function fillPipelineRunForm(payload) {
  var stages = (payload && payload.stages) || [];
  var past = (payload && payload.state) || {};
  var codes = stages.map(function (stage) {
    return String(stage.code || '');
  });
  var settled = codes.filter(function (code) {
    return past[code] && past[code].status === 'done';
  });
  var text = document.getElementById(PIPELINE_FORM_TEXT_ID);
  if (text) {
    text.textContent =
      '一段一段跑下来要不少时间（这次的表共 ' + codes.length + ' 段）。' +
      '产物还在的段会跳过，现在算跑过的是 ' +
      (settled.length ? settled.join('、') : '一段都没有') +
      '；跑完还有 ' + ((payload && payload.render_required) || []).length +
      ' 段得回引擎侧出图/视频。';
  }
  // 起止下拉的选项就是这一趟的段，顺序照宿主给的来（S0 → S7）；
  // 默认从头跑到尾，跟宿主 run 没给 from/to 时的默认一致。
  [
    { id: PIPELINE_FROM_ID, pick: 'first' },
    { id: PIPELINE_TO_ID, pick: 'last' },
  ].forEach(function (spec) {
    var select = document.getElementById(spec.id);
    if (!select) return;
    select.textContent = '';
    codes.forEach(function (code) {
      var option = document.createElement('option');
      option.value = code;
      option.textContent = code;
      select.appendChild(option);
    });
    select.value = spec.pick === 'first' ? codes[0] || '' : codes[codes.length - 1] || '';
  });
  // 每次都从"不重做"起（宿主那边也是这样：没给 force 就跳过已落盘的）。
  var force = document.getElementById(PIPELINE_FORCE_ID);
  if (force) force.checked = false;
}

// 跑的时候把这一页那几颗按钮按下去：不按的话，人会以为"再按一下能催它快一点"，
// 而它按下去只会撞上宿主那道同项目互斥（见 pipeline.py 的 RUNNING_PROJECTS）。
function lockPipelineButtons(busy) {
  var view = document.getElementById(PIPELINE_VIEW_ID);
  if (!view) return;
  var buttons = view.querySelectorAll('.cs-proj-bar button');
  for (var i = 0; i < buttons.length; i += 1) buttons[i].disabled = !!busy;
}

// 真跑。参数与确认卡上看到的逐项对应：起止段、要不要重做跑过的。
// 跑的过程**不靠这一趟的回话来画**（它要十几分钟才回），而是靠宿主逐段推的 pipeline/event。
function runPipeline() {
  if (STATE.pipelineBusy) {
    pipelineHint('上一趟还在跑，等它跑完。', 'error');
    return null;
  }
  var params = pipelineArgs();
  if (!params.name) {
    pipelineHint('先挑一部戏。', 'error');
    return null;
  }
  var from = document.getElementById(PIPELINE_FROM_ID);
  var to = document.getElementById(PIPELINE_TO_ID);
  var force = document.getElementById(PIPELINE_FORCE_ID);
  if (from && from.value) params.from = from.value;
  if (to && to.value) params.to = to.value;
  if (force && force.checked) params.force = true;

  togglePopup(PIPELINE_FORM_ID, PIPELINE_FORM_HINT_ID, null, false);
  STATE.pipelineBusy = true;
  STATE.pipelineStages = {};
  lockPipelineButtons(true);
  paintPipeline(STATE.pipeline);
  pipelineHint(
    '跑起来了：' + (params.from || '头') + ' → ' + (params.to || '尾') + '。这一页会一段一段亮起来。',
    'info'
  );

  var asked = Promise.resolve(bridge.request('pipeline/run', params));
  return asked.then(
    function (response) {
      STATE.pipelineBusy = false;
      STATE.pipelineStages = null;
      lockPipelineButtons(false);
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        pipelineHint('跑不动：' + (error.message || '未知错误'), 'error');
        return null;
      }
      var report = response.result || {};
      // 收尾一律重问一遍计划：run 的回话是它自己那一刻的快照，而"现在到底跑到哪儿了"
      // 唯一的事实源是宿主那份进度账（它顺便会把刚落盘的段一起算进来）。
      planPipeline();
      pipelineHint(
        '这一趟跑完了：' + (report.ran || []).length + ' 段有产物、' +
          (report.not_ran || []).length + ' 段没动，其中 ' +
          (report.render_required || []).length + ' 段还得回引擎侧出图/视频。',
        'info'
      );
      return report;
    },
    function (err) {
      STATE.pipelineBusy = false;
      STATE.pipelineStages = null;
      lockPipelineButtons(false);
      pipelineHint('跑不动：' + message(err), 'error');
      return null;
    }
  );
}

// 改一段的归宿，只重画那一张卡：一段一段跑十几分钟，人正盯着某一段时整页重画会把滚动位置
// 一起掀掉。卡还没画过（或者计划还没到手）就退回整页重画，代价是多刷一次。
function setPipelineStage(code, outcome) {
  var key = String(code || '');
  if (!key) return;
  STATE.pipelineStages = STATE.pipelineStages || {};
  STATE.pipelineStages[key] = outcome;
  var list = document.getElementById(PIPELINE_LIST_ID);
  var stages = (STATE.pipeline && STATE.pipeline.stages) || [];
  var stage = null;
  stages.forEach(function (row) {
    if (String(row.code) === key) stage = row;
  });
  if (!list || !stage) {
    paintPipeline(STATE.pipeline);
    return;
  }
  var card = pipeStageCard(stage, STATE.pipelineStages, (STATE.pipeline && STATE.pipeline.state) || {});
  var old = list.querySelector('[data-code="' + key + '"]');
  if (old) list.replaceChild(card, old);
  else list.appendChild(card);
}

// 宿主逐段推过来的进度（pipeline/event）。**只认这一页正在跑的那一趟**：
// stage 与 stage_start 这两条**不带项目名**（只有 start / finished 带），没法核对是哪部戏，
// 所以用"这一页现在跑着没有"当门 —— 而 run 与面板是一对一（同项目第二条会被宿主拒），
// 这道门就够把别处跑起来的进度挡在外面。不设门，隔壁窗口的进度会画到这一页上。
function onPipelineEvent(payload) {
  var params = (payload && payload.params) || {};
  if (params.type !== 'pipeline') return;
  if (!STATE.pipelineBusy) return;
  var phase = String(params.phase || '');
  if (phase === 'start') {
    // start 带的是这一趟要跑哪几段（代码）。拿它先把卡片复位成"还没跑"，
    // 免得上一趟留下的"跑过了"顶在这一趟的第一段上。
    STATE.pipelineStages = {};
    (params.stages || []).forEach(function (code) {
      STATE.pipelineStages[String(code)] = { status: 'todo' };
    });
    paintPipeline(STATE.pipeline);
    return;
  }
  if (phase === 'stage_start') {
    setPipelineStage(params.code, { status: 'running' });
    pipelineHint(
      '正在跑 ' + String(params.code || '') + ' ' + String(params.name || '') +
        '（' + String(params.actor || '') + '）…',
      'info'
    );
    return;
  }
  if (phase === 'stage') {
    setPipelineStage(params.code, params);
    return;
  }
  // finished 带的是整趟的 report，与 run 的回话同一份 —— 收尾统一在 runPipeline 的 then 里做。
  // 两条路都写一遍的话，事件先到、回话后到，同一句话会被说两次。
}

function buildProjectView() {
  var view = document.createElement('div');
  view.id = PROJECT_VIEW_ID;
  view.style.cssText = 'flex:1;min-height:0;display:none;flex-direction:column;';
  view.setAttribute('role', 'tabpanel');

  var bar = document.createElement('div');
  bar.className = 'cs-proj-bar';
  bar.appendChild(
    projectButton('刷新', '重新列一遍项目目录（一剧一目录）', function () {
      loadProjects();
    })
  );
  bar.appendChild(
    projectButton('新建项目…', '给一部新戏建目录：填名字与集数，还能从原文库里挑一本原著', function () {
      // 表单里的原著下拉要现填：原文库是别的程序也会动的东西（导入、删除都在小说那页）。
      // 只在"确实打开了"这一趟填 —— 收起来的时候没必要再问一遍原文库。
      if (toggleProjectForm()) fillNovelOptions();
    })
  );
  bar.appendChild(
    projectButton('发到对话', '把当前这部戏的现状写成一段话放进输入框（自己改完再发）', function () {
      sendProjectBrief();
    })
  );

  // 建项目表单：剧名、集数、原著（可从原文库里挑）。原著是**可选**的 ——
  // 有的是原创，有的还没把原文接进来；没选就只是不登记来源，不影响建目录。
  // 它是个弹窗（搭法见 buildPopup），这几个字段一个占一行。
  var popup = buildPopup(PROJECT_FORM_ID, PROJECT_FORM_HINT_ID, '新建项目 / 补落点');
  var form = popup.layer;

  var nameInput = document.createElement('input');
  nameInput.id = PROJECT_FORM_NAME_ID;
  nameInput.className = 'cs-proj-input';
  nameInput.type = 'text';
  nameInput.placeholder = '例如 长夜';
  nameInput.title = '这一部戏的目录名：manju/projects/<剧名>/';
  popup.body.appendChild(popupField('剧名（就是目录名）', nameInput));

  var episodes = document.createElement('input');
  episodes.id = PROJECT_FORM_EPISODES_ID;
  episodes.className = 'cs-proj-input';
  episodes.type = 'number';
  episodes.min = '1';
  episodes.max = '9999';
  episodes.value = '12';
  episodes.title = '分多少集：写进模板占位符（以后改集数不用重建目录）';
  popup.body.appendChild(popupField('集数', episodes));

  var novel = document.createElement('select');
  novel.id = PROJECT_FORM_NOVEL_ID;
  novel.className = 'cs-proj-select';
  novel.title = '这一部改的是哪本原著：登记进 00_PROJECT/07_素材归档/素材来源登记.md（可选）';
  popup.body.appendChild(popupField('原著（可选）', novel));

  var upgrade = document.createElement('input');
  upgrade.id = PROJECT_FORM_UPGRADE_ID;
  upgrade.type = 'checkbox';
  var upgradeWrap = document.createElement('label');
  upgradeWrap.className = 'cs-popup-check';
  upgradeWrap.title = '目录已经有了时：补上缺少的那些格子（已经写进去的东西一律不动）';
  upgradeWrap.appendChild(upgrade);
  upgradeWrap.appendChild(document.createTextNode('已存在就补齐落点'));
  popup.body.appendChild(upgradeWrap);

  popup.actions.appendChild(
    projectButton('取消', '关掉这个弹窗（不建目录）', function () {
      toggleProjectForm(false);
    })
  );
  var submit = projectButton('建', '按这份表单建目录 / 补落点（只补不覆盖）', function () {
    createProjectFromForm();
  });
  submit.dataset.primary = '1';
  popup.actions.appendChild(submit);

  var hint = document.createElement('div');
  hint.id = PROJECT_HINT_ID;
  hint.className = 'cs-proj-hint';
  // 平时空着（CSS 里 :empty 连位子都不占）：这一行说的是"刚才那件事怎么样了"——建项目、
  // 读文件、列不出项目。这块面板怎么用那两句，放在右边的空态里说，不必在页顶再占一行。
  hint.textContent = '';

  var body = document.createElement('div');
  body.className = 'cs-proj-body';
  var list = document.createElement('div');
  list.id = PROJECT_LIST_ID;
  list.className = 'cs-proj-list';
  list.appendChild(projectEmpty('正在列项目…'));
  var main = document.createElement('div');
  main.id = PROJECT_MAIN_ID;
  main.className = 'cs-proj-main';
  var head = document.createElement('div');
  head.id = PROJECT_HEAD_ID;
  head.className = 'cs-proj-head';
  head.textContent = '左边点一部剧，右边就是它的资料落到哪几格了。';
  var shelves = document.createElement('div');
  shelves.id = PROJECT_SHELVES_ID;
  shelves.className = 'cs-proj-shelves';
  var reader = document.createElement('div');
  reader.id = PROJECT_READER_ID;
  reader.className = 'cs-proj-reader';
  reader.textContent = '点一格里的文件名，它的内容就出现在这里。';
  var pager = document.createElement('div');
  pager.id = PROJECT_PAGER_ID;
  pager.className = 'cs-proj-pager';
  main.appendChild(head);
  main.appendChild(shelves);
  main.appendChild(buildProjectFileFind());
  main.appendChild(reader);
  main.appendChild(pager);
  body.appendChild(list);
  body.appendChild(main);
  view.appendChild(bar);
  view.appendChild(hint);
  // 筛项目那一行与总览紧挨着：它们说的是同一件事（这一屏列出来了几部、什么光景）。
  // 中间夹一个建项目表单的话，读完计数还得往上翻回去找。
  view.appendChild(buildProjectFind());
  view.appendChild(buildProjectOverview());
  view.appendChild(body);
  // 弹窗摆在最后：它是绝对定位、不吃布局（放哪儿都不推别人），摆最后只是为了让它在这一页
  // 所有内容上面。
  view.appendChild(form);
  return view;
}

// 列项目：每次切到这一页都重列（见 switchView）。这一趟拿个票，回来时票不对就丢掉 ——
// 连点两下刷新时，先发的请求后回来会把新列表盖成旧的。
function loadProjects() {
  // 筛项目那串字交给宿主去匹配（见 buildProjectFind）：面板不在这里自己过滤 ——
  // 宿主那份列表本来就可能被截断，面板再筛一遍只会把"没列出来的"永远藏起来。
  var query = String(STATE.projectFind || '').trim();
  var list = document.getElementById(PROJECT_LIST_ID);
  if (list) {
    list.textContent = '';
    list.appendChild(projectEmpty(query ? '正在找「' + query + '」…' : '正在列项目…'));
  }
  STATE.projectListToken = (STATE.projectListToken || 0) + 1;
  var ticket = STATE.projectListToken;
  return Promise.resolve(bridge.request('projects/list', query ? { name: query } : {})).then(
    function (response) {
      if (STATE.projectListToken !== ticket) return null;
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        var reason = error.message || '未知错误';
        if (list) {
          list.textContent = '';
          list.appendChild(projectEmpty('列不出项目：' + reason));
        }
        projectHint('列不出项目：' + reason, 'error');
        return null;
      }
      STATE.projects = response.result || {};
      paintProjects(STATE.projects);
      return STATE.projects;
    },
    function (err) {
      if (STATE.projectListToken !== ticket) return null;
      if (list) {
        list.textContent = '';
        list.appendChild(projectEmpty('宿主不在，列不出项目'));
      }
      projectHint('列不出项目: ' + message(err), 'error');
      return null;
    }
  );
}

//: 敲字到发请求之间等一会儿（毫秒）：一个字一趟请求太吵。
var PROJECT_FIND_DEBOUNCE_MS = 250;

// ---- 筛项目：把字交给宿主去筛 ------------------------------------------
//
// 项目目录会越攒越多（宿主一次只列 DEFAULT_LIST_LIMIT 部，多出来的它自己会报 truncated），
// 在**已经拿回来的这一屏**里过滤，只能筛到运气好的那几部。所以这一行不自己过滤，而是把字交给
// 宿主（projects/list 的 name 子串，见 projects.py 的 list(query)），由它先在全部项目里筛、
// 再取前若干部 —— 这样"找一部戏"才真的找得到。跟原文那页的全文搜索同一个道理：面板不假装
// 自己手里有全量数据。
function buildProjectFind() {
  var row = document.createElement('div');
  row.className = 'cs-proj-find';
  var box = document.createElement('input');
  box.id = PROJECT_FIND_ID;
  box.type = 'text';
  box.placeholder = '按名字筛项目（在整个项目目录里找）';
  box.title = '这串字交给宿主在项目目录里做子串匹配；敲字就重列一遍，回车立刻再来一趟，Esc 清掉';
  box.addEventListener('input', function () {
    STATE.projectFind = box.value || '';
    scheduleProjectFind();
  });
  box.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      clearProjectFind();
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      loadProjects();
    }
  });
  var count = document.createElement('span');
  count.id = PROJECT_FIND_COUNT_ID;
  count.className = 'cs-proj-find-count';
  row.appendChild(box);
  row.appendChild(count);
  return row;
}

function scheduleProjectFind() {
  if (STATE.projectFindTimer) window.clearTimeout(STATE.projectFindTimer);
  STATE.projectFindTimer = window.setTimeout(function () {
    STATE.projectFindTimer = null;
    loadProjects();
  }, PROJECT_FIND_DEBOUNCE_MS);
}

// 把筛项目那串字清掉，只清状态与输入框、不发请求：给"建完一部新的要先看见它"这种场合用
// （见 createProjectFromForm），免得同一趟重列两遍。
function clearProjectFindQuietly() {
  STATE.projectFind = '';
  if (STATE.projectFindTimer) {
    window.clearTimeout(STATE.projectFindTimer);
    STATE.projectFindTimer = null;
  }
  var box = document.getElementById(PROJECT_FIND_ID);
  if (box) box.value = '';
}

function clearProjectFind() {
  clearProjectFindQuietly();
  return loadProjects();
}

// 筛项目那一行右边的计数：两个数都出自宿主这一趟的返回（matched 是筛完之后的匹配数），
// 面板不自己数一遍。
function paintProjectFindCount(result) {
  var count = document.getElementById(PROJECT_FIND_COUNT_ID);
  if (!count) return;
  if (!result || result.exists !== true) {
    count.textContent = '';
    return;
  }
  var query = String(result.query || '');
  count.textContent = query ? '匹配 ' + result.matched + ' 部' : '共 ' + result.matched + ' 部';
}

// ---- 跨项目总览：把每一部的那两个数加起来 --------------------------------
//
// 项目一多，"这个检出现在什么光景"就不是盯着单部能看出来的（左边一屏也就放得下五六行）。
// 这一行只做聚合，几个数全部出自宿主 projects/list 每一行自带的字段（stages_done /
// stages_total / missing_count，见 projects.py 的 _summary）—— 不新造任何判据：哪一步算落齐
// 仍然是宿主按落点里有没有产物判的。所以措辞只说"阶段全落齐"，不说"这部戏做完了"（详情页里
// 也是同一句提醒）。列表被截断时只算得到列出来的那几部，这一点写在句子里。
// 总览里的一枚小签。数还是那几个数（都出自宿主 projects/list 的行，见 paintProjectOverview），
// 只是不再连成一长句 —— tone 只管语气：'' 普通、"zero" 这个数是 0（淡下去：它是"没有"，
// 不是"有问题"）、"action" 有要人去补的、"warn" 这一屏只算到了一部分。
function projectChip(text, tone) {
  var chip = document.createElement('span');
  chip.className = 'cs-proj-chip';
  chip.textContent = text;
  if (tone) chip.dataset.tone = tone;
  return chip;
}

function buildProjectOverview() {
  var line = document.createElement('div');
  line.id = PROJECT_OVERVIEW_ID;
  line.className = 'cs-proj-overview';
  return line;
}

function paintProjectOverview(result) {
  var line = document.getElementById(PROJECT_OVERVIEW_ID);
  if (!line) return;
  var rows = (result && result.projects) || [];
  if (!result || result.exists !== true || rows.length === 0) {
    line.textContent = '';
    return;
  }
  var untouched = 0;
  var running = 0;
  var settled = 0;
  var missing = 0;
  var sumDone = 0;
  var sumTotal = 0;
  rows.forEach(function (row) {
    var done = Number(row.stages_done) || 0;
    var total = Number(row.stages_total) || 0;
    sumDone += done;
    sumTotal += total;
    missing += Number(row.missing_count) || 0;
    if (done === 0) untouched += 1;
    else if (total > 0 && done >= total) settled += 1;
    else running += 1;
  });
  line.textContent = '';
  // 每一枚签的文案跟原来那一句里的片段逐字一致：数一个都没变，只是不再连成一整句。
  // 两枚签之间留一个空格，复制出去还是断得开的。
  var add = function (chip) {
    if (line.childNodes.length > 0) line.appendChild(document.createTextNode(' '));
    line.appendChild(chip);
  };
  add(projectChip((result.query ? '筛出的 ' : '列出来的 ') + rows.length + ' 部'));
  add(projectChip('还没动工 ' + untouched + ' 部', untouched === 0 ? 'zero' : ''));
  add(projectChip('进行中 ' + running + ' 部', running === 0 ? 'zero' : ''));
  add(projectChip('阶段全落齐 ' + settled + ' 部', settled === 0 ? 'zero' : ''));
  if (sumTotal > 0) add(projectChip('阶段合计 ' + sumDone + '/' + sumTotal));
  if (missing > 0) add(projectChip('缺落点共 ' + missing + ' 格', 'action'));
  if (result.truncated === true) {
    add(projectChip('还有 ' + (result.matched - result.returned) + ' 部没算进来', 'warn'));
  }
}

function paintProjects(result) {
  var list = document.getElementById(PROJECT_LIST_ID);
  if (!list) return;
  list.textContent = '';
  var query = (result && result.query) || '';
  var rows = (result && result.projects) || [];
  if (!result || result.exists !== true) {
    list.appendChild(
      projectEmpty(
        '这个检出还没建过项目（' + ((result && result.dir) || '项目目录不明') + '）。点上面「新建项目…」建第一部。'
      )
    );
    paintProjectFindCount(result);
    paintProjectOverview(result);
    return;
  }
  if (rows.length === 0) {
    list.appendChild(
      projectEmpty(
        query
          ? '没有名字含「' + query + '」的项目（筛的是整个项目目录，不只是上面列过的那几部）。'
          : '这个目录下还没有项目。'
      )
    );
    paintProjectFindCount(result);
    paintProjectOverview(result);
    return;
  }
  rows.forEach(function (row) {
    list.appendChild(projectRow(row));
  });
  if (result.truncated === true) {
    list.appendChild(
      projectEmpty(
        '还有 ' + (result.matched - result.returned) + ' 部没列出来（一次最多 ' + result.limit +
          ' 部，把名字写细一点能筛出来）。'
      )
    );
  }
  paintProjectFindCount(result);
  paintProjectOverview(result);
}

function projectRow(row) {
  var line = document.createElement('button');
  line.type = 'button';
  line.className = 'cs-proj-row';
  line.dataset.name = row.name;
  if (STATE.projectOpen && STATE.projectOpen.name === row.name) line.dataset.open = 'true';
  line.title = row.path || row.name;
  var name = document.createElement('div');
  name.className = 'cs-proj-name';
  name.textContent = row.name;
  var meta = document.createElement('div');
  meta.className = 'cs-proj-meta';
  // 只报数，不报"完成度百分之几"：阶段有几步是宿主按落点里有没有产物判的（见 summary.stages），
  // 面板自己算一个百分比，就等于又抄了一份判据。下面那条进度条画的是同两个数（见 projectBar）。
  meta.textContent =
    row.stages_done + '/' + row.stages_total + ' 段 · ' + row.files + ' 个文件' +
    (row.missing_count > 0 ? ' · 缺 ' + row.missing_count + ' 格' : '') +
    ' · ' + formatTime(row.mtime);
  line.appendChild(name);
  line.appendChild(meta);
  line.appendChild(
    projectBar(row.stages_done, row.stages_total, row.stages_done + '/' + row.stages_total + ' 段有产物')
  );
  line.addEventListener('click', function () {
    openProject(row.name);
  });
  return line;
}

function clearProjectDetail(name) {
  var head = document.getElementById(PROJECT_HEAD_ID);
  if (head) head.textContent = '正在读 ' + name + ' 的落点…';
  var shelves = document.getElementById(PROJECT_SHELVES_ID);
  if (shelves) shelves.textContent = '';
  // 换项目（或重读）时把页内找字的旧命中清掉，框里那串字留着：等新文件读出来自然会对上。
  var open = STATE.projectOpen;
  if (open) open.page = null;
  STATE.projectFileFindHits = [];
  STATE.projectFileFindAt = -1;
  // 留白而不是写"没找到"：新项目那一页还没读出来，此刻屏幕上一个字都没有，
  // 报"没找到"等于替一次还没做的检索下结论。
  blankProjectFileFindCount();
  var reader = document.getElementById(PROJECT_READER_ID);
  if (reader) reader.textContent = '点一格里的文件名，它的内容就出现在这里。';
  var pager = document.getElementById(PROJECT_PAGER_ID);
  if (pager) pager.textContent = '';
}

// 打开一部剧：拉它那趟 tree（落点 + 阶段 + 原著登记），回来整屏重画。
function openProject(name) {
  var open = STATE.projectOpen;
  if (!open || open.name !== name) {
    open = { name: name, token: 0, tree: null, file: null };
    STATE.projectOpen = open;
    clearProjectDetail(name);
    if (STATE.projects) paintProjects(STATE.projects);
  }
  open.token += 1;
  var ticket = open.token;
  return Promise.resolve(bridge.request('projects/tree', { name: name })).then(
    function (response) {
      if (!STATE.projectOpen || STATE.projectOpen.name !== name || STATE.projectOpen.token !== ticket) {
        return null;
      }
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        var reason = error.message || '未知错误';
        projectDetailError('这一部读不出来：' + reason);
        projectHint('读不了 ' + name + '：' + reason, 'error');
        return null;
      }
      STATE.projectOpen.tree = response.result || {};
      paintProjectDetail(STATE.projectOpen.tree);
      return STATE.projectOpen.tree;
    },
    function (err) {
      if (!STATE.projectOpen || STATE.projectOpen.name !== name || STATE.projectOpen.token !== ticket) {
        return null;
      }
      projectDetailError('这一部读不出来：宿主不在');
      projectHint('读不了 ' + name + ': ' + message(err), 'error');
      return null;
    }
  );
}

function projectDetailError(text) {
  var head = document.getElementById(PROJECT_HEAD_ID);
  if (head) head.textContent = text;
  var shelves = document.getElementById(PROJECT_SHELVES_ID);
  if (shelves) shelves.textContent = '';
  // 读不出来就没有"这一页正文"了：页内找字的命中与位置一起作废（跟 clearProjectDetail 同一个口径）。
  var open = STATE.projectOpen;
  if (open) open.page = null;
  STATE.projectFileFindHits = [];
  STATE.projectFileFindAt = -1;
  paintProjectFileFindCount(0);
  var pager = document.getElementById(PROJECT_PAGER_ID);
  if (pager) pager.textContent = '';
}

// 详情里的一行备注。文案由各处自己写（只有它知道那件事的来龙去脉），语气在这一处定 ——
// 以前四种事都穿同一件红衣服：下一步往哪走是**路标**，不是报警，用红字说它，人一进来就以为
// 出事了。tone：plain 事实登记 / next 下一步 / action 要人去补的 / bug 面板自己的毛病。
function projectNote(text, tone) {
  var line = document.createElement('div');
  if (!text) return line;
  line.className = 'cs-proj-note';
  line.dataset.tone = tone || 'plain';
  line.textContent = text;
  return line;
}

// 原文库里有没有这一篇：只有"这一列已经列过"的时候才有答案（那边没打开过就是"不知道"，
// 不拿"应该有"当"有"）。
function novelHas(name) {
  var rows = (STATE.novels && STATE.novels.novels) || [];
  for (var index = 0; index < rows.length; index += 1) {
    if (rows[index].name === name) return true;
  }
  return false;
}

// 进度条：把宿主**已经给好的两个数**（stages_done / stages_total，见 lib/comfy_studio/projects.py
// 的 _summary）按同一个比例画成一条。这不是面板新算的判据 —— 哪一步算完成仍然是宿主按落点里
// 有没有产物判的；面板只做一件事：让人一眼看出还剩几步。数字照旧写在它旁边，
// 条形只当"余量"看，别让人只能对着一条虚线猜还剩多少（这也是为什么这里不写"完成 67%"）。
function projectBar(done, total, label) {
  var bar = document.createElement('div');
  bar.className = 'cs-proj-meter';
  var fill = document.createElement('div');
  fill.className = 'cs-proj-meter-fill';
  fill.style.width = (total > 0 ? (Number(done) || 0) / total * 100 : 0).toFixed(2) + '%';
  bar.appendChild(fill);
  if (label) bar.title = label;
  return bar;
}

// 阶段里的一步，一枚小签。文案照宿主念（label 与文件数都出自 projects/tree 的 summary.stages，
// 见 projects.py 的 _summary）；做没做只看 done 这一位 —— 面板不自己判断哪一步算完成了。
function projectStage(stage) {
  var chip = document.createElement('span');
  chip.className = 'cs-proj-stage';
  chip.dataset.done = stage.done === true ? '1' : '0';
  chip.textContent = stage.label + '（' + stage.files + '）';
  return chip;
}

// 画一部剧：顶上三行事实（阶段 / 原著 / 缺什么），下面一格一格摆资料。
// 「缺落点」与「面板格子跟规范对不上」是两码事，所以分两条写：
// 前者让人去补目录，后者是**面板自己的 bug**（要改 PROJECT_SHELVES），不能混在一起说。
function paintProjectDetail(tree) {
  var head = document.getElementById(PROJECT_HEAD_ID);
  var summary = tree.summary || {};
  var stages = summary.stages || [];
  if (head) {
    head.textContent = '';
    // 剧名一行、路径一行：路径常常比面板还长，跟剧名挤一行会把剧名一起拽断。
    var title = document.createElement('div');
    title.className = 'cs-proj-title';
    title.textContent = tree.name;
    head.appendChild(title);
    var pathLine = document.createElement('div');
    pathLine.className = 'cs-proj-path';
    pathLine.textContent = tree.path;
    head.appendChild(pathLine);
    var stageLine = document.createElement('div');
    stageLine.className = 'cs-proj-stages';
    var stageLabel = document.createElement('span');
    stageLabel.className = 'cs-proj-stages-label';
    stageLabel.textContent = '阶段：';
    stageLine.appendChild(stageLabel);
    if (stages.length > 0) {
      stages.forEach(function (stage) {
        stageLine.appendChild(projectStage(stage));
      });
    } else {
      stageLine.appendChild(document.createTextNode('宿主没给阶段判据'));
    }
    head.appendChild(stageLine);
    // 还剩几步、下一步是哪一步：条还是宿主那两个数画的（见 projectBar），名字也照宿主的念
    // （stages[].label / stages_done / stages_total 都出自 projects/tree 的 summary）——
    // 面板不自己排"该先做哪件事"的顺序，顺序就是宿主给阶段的顺序。
    var done = Number(summary.stages_done) || 0;
    var total = Number(summary.stages_total) || stages.length;
    if (total > 0) {
      // 数字照旧写在条旁边：条形只当"余量"看，别让人只能对着一条虚线猜还剩多少（见 projectBar）。
      var meterNote = document.createElement('div');
      meterNote.className = 'cs-proj-meter-note';
      meterNote.textContent = done + '/' + total + ' 段有产物';
      head.appendChild(meterNote);
      head.appendChild(projectBar(done, total, done + '/' + total + ' 段有产物'));
      var nextStage = null;
      for (var stageIndex = 0; stageIndex < stages.length; stageIndex += 1) {
        if (stages[stageIndex].done !== true) {
          nextStage = stages[stageIndex];
          break;
        }
      }
      head.appendChild(
        projectNote(
          nextStage
            ? '下一步：' + nextStage.label + '（这一步现在 ' + nextStage.files + ' 个产物）—— 资料放进去之后回来看这条就会往前走'
            : '这几步都落上产物了（这是宿主按落点判的，不等于整部戏做完了）',
          'next'
        )
      );
    }
    // 原著登记这一行：登记过的话右边接一颗"去读原文"（见 novel 分支）。
    var novel = document.createElement('div');
    novel.className = 'cs-proj-novel';
    if (!tree.novel) {
      novel.textContent = '原著：未登记（建项目时挑一本，或自己写进 00_PROJECT/07_素材归档/素材来源登记.md）';
    } else {
      // 项目里"这一部改的是哪本"与「管理小说」那页是同一样东西，却分在两页上：登记了就把路铺过去，
      // 省得人自己再去找一遍。原文库这一列没列过（STATE.novels 为空）就只摆一句"去那儿打开"——
      // 那边自己会如实说有没有这一篇，面板不在这儿替它编一个"应该有"。
      var known = STATE.novels ? novelHas(tree.novel) : null;
      novel.textContent =
        '原著：' + tree.novel + (known === false ? '（原文库里没这一篇：可能没接进来，或已经删了）' : '');
      novel.appendChild(
        projectButton(known === false ? '去看看原文库' : '去读原文', '切到「管理小说」把这一篇打开', function () {
          switchView('novel');
          openNovel(tree.novel, 0);
        })
      );
    }
    head.appendChild(novel);
    // 缺落点是要人去补目录（action）；下面两条是**面板自己的 bug**（bug）——
    // 一个要去补目录、一个要改面板，两件事不共用一种颜色。
    head.appendChild(
      projectNote(
        (summary.missing || []).length > 0
          ? '缺 ' + summary.missing_count + ' 个落点：' + summary.missing.join('、') + '（勾上「已存在就补齐落点」再建一次）'
          : '',
        'action'
      )
    );
    head.appendChild(
      projectNote(
        (tree.gaps || []).length > 0
          ? '规范里有落点没被面板归到任何一格：' + tree.gaps.join('、') + '（面板该补格子了）'
          : '',
        'bug'
      )
    );
    head.appendChild(
      projectNote(
        (tree.unknown || []).length > 0 ? '面板写了规范里没有的落点：' + tree.unknown.join('、') : '',
        'bug'
      )
    );
  }
  var shelves = document.getElementById(PROJECT_SHELVES_ID);
  if (shelves) {
    shelves.textContent = '';
    (tree.shelves || []).forEach(function (shelf) {
      shelves.appendChild(shelfBlock(shelf));
    });
  }
}

// 一格。空格子照样画出来（只是淡一点）：整格不出现，人就以为这部戏根本不需要那份资料。
function shelfBlock(shelf) {
  var box = document.createElement('div');
  box.className = 'cs-proj-shelf';
  box.dataset.empty = shelf.count > 0 ? '0' : '1';
  var head = document.createElement('button');
  head.type = 'button';
  head.className = 'cs-proj-shelf-head';
  head.title =
    shelf.dirs && shelf.dirs.length > 0
      ? '这一格对应：' + shelf.dirs.map(function (dir) { return dir.rel; }).join('、')
      : '项目根下的文件（总纲、README 这类不在格子里的）';
  // 有东西/空着用一个 6px 的点说（样式在 CSS，这里只占位），不用 ✅/☐：
  // 勾选框摆在这一列最左边，九行连起来像一排待勾的多选框，而这九行是
  // "去哪一格里找资料"，不是一件件要人去勾的事。
  var mark = document.createElement('span');
  mark.className = 'cs-proj-shelf-mark';
  mark.setAttribute('aria-hidden', 'true');
  var title = document.createElement('span');
  title.textContent = shelf.title;
  var count = document.createElement('span');
  count.className = 'cs-proj-shelf-count';
  count.textContent = shelf.count > 0 ? shelf.count + ' 个文件' : '还空着';
  head.appendChild(mark);
  head.appendChild(title);
  head.appendChild(count);
  head.addEventListener('click', function () {
    box.dataset.open = box.dataset.open === '1' ? '0' : '1';
  });
  var files = document.createElement('div');
  files.className = 'cs-proj-files';
  var dirs = shelf.dirs && shelf.dirs.length > 0 ? shelf.dirs : [];
  var groups = shelf.groups && shelf.groups.length > 0 ? shelf.groups : [];
  if (shelf.count === 0) {
    files.appendChild(
      projectEmpty(
        '这一格还空着：' + (dirs.length > 0 ? dirs.map(function (dir) { return dir.rel; }).join('、') : '（项目根）')
      )
    );
  }
  // 分组格（一个标题下好几个落点）与根格（只有文件、没有落点）形状不同，这里统一成一种。
  // 一格里的落点再按**粒度**（全剧级 / 分集级）分段 —— 数据由宿主给（见 projects.py 的 tree），
  // 面板这边不判"哪个落点是哪一级"：判错了不会报错，只会把一集的东西摆进"全剧共用"那一栏。
  // 只有一段时不摆小标题：一条"分集级"标题底下全是分集级，那是噪声（空着那格同理，
  // 一句"还空着"已经说完了，再来两个"还空着"的分段只是把格子撑长）。
  var sections;
  if (dirs.length === 0) {
    sections = [{ title: '', count: shelf.count, dirs: [{ rel: '', files: shelf.files || [], truncated: false }] }];
  } else if (groups.length > 1 && shelf.count > 0) {
    sections = groups.map(function (group) {
      return { title: group.title, count: group.count, dirs: group.dirs || [] };
    });
  } else {
    sections = [{ title: '', count: shelf.count, dirs: dirs }];
  }
  sections.forEach(function (section) {
    if (section.title) files.appendChild(projectGroupLabel(section));
    section.dirs.forEach(function (bucket) {
      (bucket.files || []).forEach(function (file) {
        files.appendChild(projectFileRow(file));
      });
      if (bucket.truncated === true) {
        files.appendChild(projectEmpty('这里只列了前 ' + (bucket.files || []).length + ' 个，还有更多没列出来。'));
      }
    });
  });
  box.appendChild(head);
  box.appendChild(files);
  return box;
}

// 一格里的粒度小标题（全剧级 / 分集级）。旁边带一段这一组有几个文件 ——
// 光秃秃一个小标题，人会以为下面那几行就是这一格的全部，其实这一格还有别的组。
function projectGroupLabel(section) {
  var label = document.createElement('div');
  label.className = 'cs-proj-group';
  label.dataset.scope = section.title;
  var name = document.createElement('span');
  name.className = 'cs-proj-group-name';
  name.textContent = section.title;
  var count = document.createElement('span');
  count.className = 'cs-proj-group-count';
  count.textContent = section.count > 0 ? section.count + ' 个文件' : '还空着';
  label.appendChild(name);
  label.appendChild(count);
  return label;
}

function projectFileRow(file) {
  var line = document.createElement('button');
  line.type = 'button';
  line.className = 'cs-proj-file';
  line.dataset.rel = file.rel;
  line.dataset.read = file.readable === true ? '1' : '0';
  line.title = file.rel + '（' + formatBytes(file.bytes) + '，' + formatTime(file.mtime) + '）';
  var name = document.createElement('span');
  name.textContent = file.name;
  var size = document.createElement('span');
  size.className = 'cs-proj-file-size';
  size.textContent = formatBytes(file.bytes);
  line.appendChild(name);
  line.appendChild(size);
  // 图片、音频、视频照样列出来（它们就躺在那一格里），但不给点：这个面板不播它们，
  // 读成文本只会是一片乱码 —— 让按钮点得动却给出乱码，比灰着更让人恼火。
  if (file.readable !== true) {
    line.disabled = true;
    return line;
  }
  line.addEventListener('click', function () {
    readProjectFile(file.rel, 0);
  });
  return line;
}

// 读一份资料。不带 chars：一页多少字按宿主那份来（lib/comfy_studio/projects.py），
// 翻页要用的页长从回话里的 requested_chars 拿 —— 面板手抄一份数字，两边对不上时是静默的。
function readProjectFile(rel, offset) {
  var open = STATE.projectOpen;
  if (!open) return null;
  var token = (open.file && open.file.token ? open.file.token : 0) + 1;
  open.file = { rel: rel, token: token };
  var reader = document.getElementById(PROJECT_READER_ID);
  if (reader) reader.textContent = '正在读 ' + rel + ' …';
  return Promise.resolve(bridge.request('projects/read', { name: open.name, rel: rel, offset: offset || 0 })).then(
    function (response) {
      // 读的过程中换了一部剧、或又点了别的文件：这份回话已经过期，丢掉。
      if (!STATE.projectOpen || STATE.projectOpen.file !== open.file) return null;
      if (!response || response.ok !== true) {
        var reason = ((response && response.error) || {}).message || '未知错误';
        if (reader) reader.textContent = '读不了 ' + rel + '：' + reason;
        var pager = document.getElementById(PROJECT_PAGER_ID);
        if (pager) pager.textContent = '';
        projectHint('读不了 ' + rel + '：' + reason, 'error');
        return null;
      }
      paintProjectPage(response.result || {});
      return response.result;
    },
    function (err) {
      if (!STATE.projectOpen || STATE.projectOpen.file !== open.file) return null;
      if (reader) reader.textContent = '读不了 ' + rel + '：宿主不在';
      projectHint('读不了 ' + rel + ': ' + message(err), 'error');
      return null;
    }
  );
}

// ---- 在这一页正文里找字 ------------------------------------------------
//
// 与原文那页的全文搜索**不是一回事**，这一点必须写清（也就必须写在界面上）：宿主有
// novels/search（在整本原文里找），项目资料这边只有 projects/read（接 name/rel/offset/chars，
// 见 projects.py 的 read）—— 没有一个"在项目资料里搜"的口子。所以这里只找**已经读出来的这一页**；
// 想找下一页、或另一份文件，得先翻页或先点开那个文件。把这里假装成全文搜索就是骗人。
//
// 手法也与对话页不同：那边只给行打 [data-hit]、不往字里插东西，因为消息区是增量画上去的、
// 整块重建会把工具卡拆掉；项目阅读区是整块重画（paintProjectPage 一次写完），所以这里敢把命中处
// 包一层 <mark>，也就有了浏览器 Ctrl+F 那种"一眼看见字在哪儿"的效果。
function buildProjectFileFind() {
  var row = document.createElement('div');
  row.className = 'cs-find cs-proj-file-find';
  var box = document.createElement('input');
  box.id = PROJECT_FILE_FIND_ID;
  box.type = 'text';
  box.placeholder = '在这一页正文里找一串字';
  box.title =
    '只找已经读出来的这一页（宿主没有"在项目资料里搜"的口子，跟原文那页的全文搜索不是一回事）；' +
    'Enter 下一处，Shift+Enter 上一处，Esc 清空';
  box.addEventListener('input', function () {
    runProjectFileFind(box.value || '');
  });
  box.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      event.preventDefault();
      clearProjectFileFind();
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      moveProjectFileFind(event.shiftKey ? -1 : 1);
    }
  });
  var count = document.createElement('span');
  count.id = PROJECT_FILE_FIND_COUNT_ID;
  count.className = 'cs-find-count';
  row.appendChild(box);
  row.appendChild(count);
  row.appendChild(
    projectFindButton(PROJECT_FILE_FIND_PREV_ID, '上一处', '往上找（到头了绕回最后一处）', function () {
      moveProjectFileFind(-1);
    })
  );
  row.appendChild(
    projectFindButton(PROJECT_FILE_FIND_NEXT_ID, '下一处', '往下找（到底了绕回第一处）', function () {
      moveProjectFileFind(1);
    })
  );
  row.appendChild(
    projectFindButton(PROJECT_FILE_FIND_CLEAR_ID, '清空', '清掉找字（正文恢复原样）', function () {
      clearProjectFileFind();
    })
  );
  return row;
}

// 这几个按钮直接用对话页那一套 .cs-find-btn：三页的检索长一个样，人才不用每页重新认一遍。
function projectFindButton(id, text, title, onClick) {
  var button = projectButton(text, title, onClick);
  button.id = id;
  button.className = 'cs-find-btn';
  return button;
}

// 不重叠地数出每一处的位置：从上一个命中之后再往后找（同 3 个字叠着算一处，跟浏览器一致）。
function projectFileFindHits(text, query) {
  var hits = [];
  var needle = String(query || '').toLowerCase();
  if (!text || needle === '') return hits;
  var haystack = String(text).toLowerCase();
  var at = haystack.indexOf(needle);
  while (at >= 0) {
    hits.push(at);
    at = haystack.indexOf(needle, at + needle.length);
  }
  return hits;
}

// 画正文：没在找字就原样一段文本；在找字就把命中处包起来，当前那一处再标 [data-cur]。
// 每一趟都整块重画 —— 正文不是增量卡，重启一遍不会丢东西。
function paintProjectReader(scroll) {
  var reader = document.getElementById(PROJECT_READER_ID);
  if (!reader) return;
  var open = STATE.projectOpen;
  var page = open && open.page;
  reader.textContent = '';
  if (!page) {
    reader.textContent = '点一格里的文件名，它的内容就出现在这里。';
    blankProjectFileFindCount();
    return;
  }
  var text = page.text || '';
  var query = String(STATE.projectFileFind || '');
  var hits = projectFileFindHits(text, query);
  STATE.projectFileFindHits = hits;
  if (hits.length === 0) {
    reader.textContent = text;
    STATE.projectFileFindAt = -1;
    paintProjectFileFindCount(0);
    return;
  }
  if (STATE.projectFileFindAt < 0 || STATE.projectFileFindAt >= hits.length) STATE.projectFileFindAt = 0;
  var at = STATE.projectFileFindAt;
  var frag = document.createDocumentFragment();
  var cursor = 0;
  for (var index = 0; index < hits.length; index += 1) {
    if (hits[index] > cursor) frag.appendChild(document.createTextNode(text.slice(cursor, hits[index])));
    var mark = document.createElement('mark');
    mark.className = 'cs-proj-hit';
    if (index === at) mark.dataset.cur = 'true';
    // 取的是原文那一段（不是输入框里那串）：大小写不同时，屏幕上仍该是文件里本来的写法。
    mark.textContent = text.slice(hits[index], hits[index] + query.length);
    frag.appendChild(mark);
    cursor = hits[index] + query.length;
  }
  if (cursor < text.length) frag.appendChild(document.createTextNode(text.slice(cursor)));
  reader.appendChild(frag);
  if (scroll !== false) {
    var current = reader.querySelector('.cs-proj-hit[data-cur="true"]');
    if (current && typeof current.scrollIntoView === 'function') current.scrollIntoView({ block: 'center' });
  }
  paintProjectFileFindCount(hits.length);
}

// 没有正文可读时（还没点开文件、或刚换了一部戏）计数处**留白**，不写"没找到"：
// "没找到"是"读过这一页、这页里没有"的结论，还没读就下这个结论是编的（框里那串字留着，
// 等新文件读出来自然会重数）。
function blankProjectFileFindCount() {
  var count = document.getElementById(PROJECT_FILE_FIND_COUNT_ID);
  if (!count) return;
  count.textContent = '';
  count.dataset.tone = 'info';
}

function paintProjectFileFindCount(total) {
  var count = document.getElementById(PROJECT_FILE_FIND_COUNT_ID);
  if (!count) return;
  if (String(STATE.projectFileFind || '') === '') {
    count.textContent = '';
    count.dataset.tone = 'info';
    return;
  }
  if (total === 0) {
    count.textContent = '没找到';
    count.dataset.tone = 'error';
    return;
  }
  count.textContent = STATE.projectFileFindAt + 1 + '/' + total + ' 处';
  count.dataset.tone = 'info';
}

// 敲字就重找：这一趟只在屏幕上转，不麻烦宿主（projects/read 没有搜索参数）。
function runProjectFileFind(query) {
  STATE.projectFileFind = query;
  STATE.projectFileFindAt = 0;
  paintProjectReader();
  return (STATE.projectFileFindHits || []).length;
}

// 上一处 / 下一处：到头了绕回去（跟对话页同一套）。
function moveProjectFileFind(step) {
  var hits = STATE.projectFileFindHits || [];
  if (String(STATE.projectFileFind || '') === '' || hits.length === 0) return 0;
  STATE.projectFileFindAt = ((STATE.projectFileFindAt + step) % hits.length + hits.length) % hits.length;
  paintProjectReader();
  return STATE.projectFileFindAt;
}

function clearProjectFileFind() {
  STATE.projectFileFind = '';
  STATE.projectFileFindAt = -1;
  STATE.projectFileFindHits = [];
  var box = document.getElementById(PROJECT_FILE_FIND_ID);
  if (box) box.value = '';
  paintProjectReader(false);
}

function paintProjectPage(page) {
  var reader = document.getElementById(PROJECT_READER_ID);
  // 这一页正文原样留着：页内找字（见 paintProjectReader）与翻页之后的重画都要用到它那一份。
  var open = STATE.projectOpen;
  if (open) open.page = page;
  // 新读出的一页，找字从那页的头数起：上一页的第 3 处跟这一页没关系。
  STATE.projectFileFindAt = 0;
  if (reader) reader.scrollTop = 0;
  // scroll 传 false：刚翻完页先让人看页首，别一上来就跳到某一处命中上。
  paintProjectReader(false);
  // 格子里那一行跟着亮：一屏正文看不出自己在读哪份文件（尤其文件名都差不多的时候）。
  var shelves = document.getElementById(PROJECT_SHELVES_ID);
  if (shelves) {
    var rows = shelves.querySelectorAll('.cs-proj-file');
    for (var index = 0; index < rows.length; index += 1) {
      rows[index].dataset.open = rows[index].dataset.rel === page.rel ? 'true' : 'false';
    }
  }
  var pager = document.getElementById(PROJECT_PAGER_ID);
  if (!pager) return;
  pager.textContent = '';
  var chars = page.chars || 0;
  var offset = page.offset || 0;
  var want = page.requested_chars || chars || 1;
  var prev = projectButton('上一页', '往回一页', function () {
    readProjectFile(page.rel, Math.max(0, offset - want));
  });
  if (offset <= 0) prev.disabled = true;
  var next = projectButton('下一页', '往下一页', function () {
    readProjectFile(page.rel, offset + chars);
  });
  if (page.truncated !== true || chars === 0) next.disabled = true;
  pager.appendChild(prev);
  pager.appendChild(next);
  var info = document.createElement('span');
  info.className = 'cs-proj-pos';
  // 文件名单独拎成一个 span（提亮加粗，见 CSS）：正文是一整块长的，读着读着最容易忘
  // "这是哪一份"。只是分开上色，textContent 还是原来那一句。
  var rel = document.createElement('span');
  rel.className = 'cs-proj-pos-rel';
  rel.textContent = page.rel;
  info.appendChild(rel);
  info.appendChild(
    document.createTextNode(
      ' · ' +
        page.encoding +
        ' · ' +
        (chars === 0 ? '空' : offset + 1 + '~' + (offset + chars)) +
        ' / ' +
        page.total_chars +
        ' 字'
    )
  );
  pager.appendChild(info);
}

// 建项目 / 补落点。落盘的活整个是宿主的（那边的 create_project 只补不覆盖），
// 这一层只把它回的话说成人话 —— 包括"原著登记了没、为什么没登记"。
function createProjectFromForm() {
  var nameEl = document.getElementById(PROJECT_FORM_NAME_ID);
  var episodesEl = document.getElementById(PROJECT_FORM_EPISODES_ID);
  var novelEl = document.getElementById(PROJECT_FORM_NOVEL_ID);
  var upgradeEl = document.getElementById(PROJECT_FORM_UPGRADE_ID);
  var name = nameEl ? (nameEl.value || '').trim() : '';
  if (name === '') {
    projectHint('先给这部戏起个名字（就是它的目录名）。', 'error');
    if (nameEl) nameEl.focus();
    return null;
  }
  var episodes = parseInt(episodesEl ? episodesEl.value : '', 10);
  if (!isFinite(episodes) || episodes < 1) {
    projectHint('集数要是 1 以上的整数。', 'error');
    if (episodesEl) episodesEl.focus();
    return null;
  }
  var params = { name: name, episodes: episodes };
  if (upgradeEl && upgradeEl.checked) params.upgrade = true;
  var novel = novelEl ? novelEl.value || '' : '';
  if (novel !== '') params.novel = novel;
  projectHint('正在建 ' + name + ' …', 'info');
  return Promise.resolve(bridge.request('projects/create', params)).then(
    function (response) {
      if (!response || response.ok !== true) {
        var reason = ((response && response.error) || {}).message || '未知错误';
        // "已经有了"不是意外：要不要往别人的目录里补东西，得人来定 —— 面板不替人勾那个勾。
        projectHint('没建成 ' + name + '：' + reason, 'error');
        return null;
      }
      var result = response.result || {};
      var note =
        '建好了 ' +
        result.name +
        '（新目录 ' +
        (result.dirs || []).length +
        ' 个，新文件 ' +
        (result.files || []).length +
        ' 份）' +
        novelNote(result.novel);
      // 建成了就把弹窗收掉（开关只有 toggleProjectForm 一个作者）。
      toggleProjectForm(false);
      // 筛词要先清掉（只清状态与输入框，不发请求）：留着的话这一趟重列带着旧筛词，
      // 刚建好的那部戏名字多半对不上筛词，用户建完却"看不见自己"。
      clearProjectFindQuietly();
      // 建完直接打开它：建目录只是第一步，接着要往里放东西。
      return loadProjects().then(function () {
        return openProject(result.name);
      }).then(function () {
        projectHint(note + '，右边就是它的落点。', 'info');
        return result;
      });
    },
    function (err) {
      projectHint('没建成 ' + name + ': ' + message(err), 'error');
      return null;
    }
  );
}

// 登记原著那一步的结果：每一种"没登记成"都有各自的修法，所以分开说，不笼统写"失败"。
function novelNote(novel) {
  if (!novel) return '';
  var reason = novel.reason;
  if (reason === 'filled') return '，原著登记为「' + novel.novel + '」';
  if (reason === 'already') return '，原著那一行已经填着「' + novel.current + '」，没动它';
  if (reason === 'missing_novel') return '，但原文库里没有「' + novel.novel + '」，所以没登记来源';
  if (reason === 'no_registry') return '，但 00_PROJECT/07_素材归档/素材来源登记.md 不在，没登记来源';
  if (reason === 'no_row') return '，但登记表里没有「原著名」那一行，没登记来源';
  return '，原著登记的情况：' + (reason || '不明');
}

// 原著下拉：从原文库里现取（导入、删除都发生在「管理小说」那页）。
// 取不到不是错误：不登记原著照样能建项目 —— 原创的戏本来就没有原著。
function fillNovelOptions() {
  var select = document.getElementById(PROJECT_FORM_NOVEL_ID);
  if (!select) return null;
  var keep = select.value || '';
  select.textContent = '';
  var none = document.createElement('option');
  none.value = '';
  none.textContent = '（不登记原著）';
  select.appendChild(none);
  return Promise.resolve(bridge.request('novels/list', {})).then(
    function (response) {
      if (!response || response.ok !== true) {
        var missing = document.createElement('option');
        missing.value = '';
        missing.textContent = '原文库没挂上（不登记原著也能建）';
        select.appendChild(missing);
        return null;
      }
      var rows = (response.result && response.result.novels) || [];
      rows.forEach(function (row) {
        var option = document.createElement('option');
        option.value = row.name;
        option.textContent = row.name;
        select.appendChild(option);
      });
      if (rows.length === 0) {
        var empty = document.createElement('option');
        empty.value = '';
        empty.textContent = '原文库是空的（可以在「管理小说」那页导入）';
        select.appendChild(empty);
      }
      select.value = keep;
      return rows;
    },
    function () {
      var down = document.createElement('option');
      down.value = '';
      down.textContent = '问不到原文库（不登记原著也能建）';
      select.appendChild(down);
      return null;
    }
  );
}

// "发到对话"：把这部戏的现状写进对话输入框，然后**停手**。跟「管理小说」那页的"拿去对话"
// 同一个规矩：拿哪一部开工、怎么开工是用户的事，替他发出去等于替他下了这个决定。
function sendProjectBrief() {
  var open = STATE.projectOpen;
  if (!open) {
    projectHint('先在左边点一部剧，再把它发到对话。', 'error');
    return null;
  }
  return Promise.resolve(bridge.request('projects/brief', { name: open.name })).then(
    function (response) {
      if (!response || response.ok !== true) {
        var reason = ((response && response.error) || {}).message || '未知错误';
        projectHint('写不出简报：' + reason, 'error');
        return null;
      }
      var brief = response.result || {};
      var text = typeof brief.text === 'string' ? brief.text : '';
      if (text === '') {
        projectHint('这部没什么可说的。', 'error');
        return null;
      }
      projectToChat(text);
      return text;
    },
    function (err) {
      projectHint('写不出简报: ' + message(err), 'error');
      return null;
    }
  );
}

function projectToChat(text) {
  switchView('chat');
  var input = document.getElementById(INPUT_ID);
  if (!input) return;
  if ((input.value || '').trim() === '') {
    input.value = text;
  } else {
    // 人家可能正打着半句话：接着往下写，别覆盖掉。
    // 这一段 JS 住在 TS 模板字符串里，反斜杠要写两遍（见 novelToChat 里同一处坑）。
    input.value = input.value.replace(/\\s+$/, '') + '\\n\\n' + text;
  }
  input.focus();
  setStatus('已把「' + (STATE.projectOpen ? STATE.projectOpen.name : '') + '」的现状放进对话框：添上要求再发。');
}

// ---- 侧栏按钮 ----------------------------------------------------------

function buildButton() {
  var btn = document.createElement('button');
  btn.id = BTN_ID;
  btn.type = 'button';
  btn.className = 'side-bar-button comfy-studio-chat-btn';
  btn.setAttribute('aria-label', 'comfy-studio 对话');
  btn.title = 'comfy-studio 对话';
  btn.style.cssText =
    'display:flex;align-items:center;justify-content:center;overflow:visible;' +
    'width:var(--sidebar-width);height:var(--sidebar-item-height);' +
    'border:none;border-radius:0;flex-shrink:0;cursor:pointer;background:transparent;' +
    'color:' + MUTED + ';transition:background-color 120ms ease,color 120ms ease;';
  btn.addEventListener('mouseenter', function () {
    btn.style.backgroundColor = 'var(--interface-panel-hover-surface)';
    btn.style.color = 'var(--content-hover-fg)';
  });
  btn.addEventListener('mouseleave', function () {
    btn.style.backgroundColor = 'transparent';
    btn.style.color = MUTED;
  });

  var icon = document.createElement('i');
  icon.className = 'icon-[lucide--sparkles] side-bar-button-icon';
  icon.style.fontSize = 'var(--sidebar-icon-size)';

  var content = document.createElement('div');
  content.className = 'side-bar-button-content flex flex-col items-center gap-2';
  content.appendChild(icon);
  btn.appendChild(content);
  btn.addEventListener('click', function () {
    if (STATE.open) closeDrawer();
    else openDrawer();
  });
  return btn;
}

function bottomCluster() {
  var help = document.querySelector('[data-testid="help-center-button"]');
  if (help) {
    var group = help.closest('.mt-auto') || help.parentElement;
    if (group) return { group: group, before: help };
  }
  var toolbar = document.querySelector('[data-testid="side-toolbar"]');
  if (toolbar) {
    var mt = toolbar.querySelector('.mt-auto');
    if (mt) return { group: mt, before: mt.firstChild };
  }
  return null;
}

function inject() {
  if (document.getElementById(BTN_ID)) return true;
  var target = bottomCluster();
  if (!target) return false;
  target.group.insertBefore(buildButton(), target.before);
  return true;
}

function start() {
  if (STATE.started) return;
  STATE.started = true;
  // 先认回"上次停在哪一段"：面板一重载（切画面、宿主重启）就只剩一个空抽屉，
  // 而宿主那边那段对话还在 —— 不认回来，下一句就说到默认那段上去了。
  restoreSession();
  STATE.unsubscribe = bridge.onEvent(onEvent);
  // 流水线的事件**另挂一份**：onEvent 头一句就是"没有一轮在跑就直接丢"（那是对话那条路的
  // 守卫），而流水线跑起来的时候对话那边根本没在跑 —— 挂在那里面等于一条都收不到。
  // preload 那个 onEvent 是 ipcRenderer.on，可以挂多份，各自退各自的。
  STATE.pipelineUnsub = bridge.onEvent(onPipelineEvent);

  var injected = inject();
  var tries = 0;
  var settle = setInterval(function () {
    tries++;
    if (inject() || tries > 100) clearInterval(settle);
  }, 200);

  STATE.observer = new MutationObserver(function () {
    if (!document.getElementById(BTN_ID)) inject();
  });
  try {
    STATE.observer.observe(document.body, { childList: true, subtree: true });
  } catch (e) {}
  return injected;
}

// ---- 画布通道 ----------------------------------------------------------
//
// 桌面壳用 executeJavaScript 直接调 STATE.canvasCall(op, args)，宿主那侧的
// canvas__snapshot / canvas__load_workflow 两个工具发的动作就落到这里（整条回家
// 路线写在 lib/comfy_studio/canvas.py）。真正碰图的是页面里的 ComfyUI 前端，
// 也就是 window.comfyAPI.app.app 那个 ComfyApp 实例；符号取自引擎 venv 里
// comfyui_frontend_package 的打包产物。拿不到这个全局就明确报错——读不到画布和
// 画布是空的不是一回事，不能糊过去。

function canvasApp() {
  var api = window.comfyAPI;
  var app = api && api.app && api.app.app;
  if (!app) {
    throw new Error('这个前端没有 window.comfyAPI.app.app：读不到画布');
  }
  return app;
}

function canvasGraph(app) {
  var root = app.rootGraph;
  if (!root || typeof root.serialize !== 'function') {
    throw new Error('这个前端没有 app.rootGraph.serialize()：读不到画布');
  }
  return root.serialize() || {};
}

// 一次快照最多带这么多节点：画布可以很大，而这份摘要整个要塞进模型的上下文。
var CANVAS_MAX_NODES = 80;

function canvasNodeSummary(node, includeWidgets) {
  var item = { id: node.id, type: node.type };
  if (node.title) item.title = String(node.title);
  if (typeof node.mode === 'number' && node.mode !== 0) item.mode = node.mode;
  if (includeWidgets && node.widgets_values != null) {
    item.widgets = JSON.stringify(node.widgets_values).slice(0, 400);
  }
  return item;
}

function canvasLinks(data) {
  var out = [];
  var raw = data.links || [];
  for (var i = 0; i < raw.length; i++) {
    var link = raw[i];
    if (!link) continue;
    // 图数据里一条连线是 [id, from_node, from_slot, to_node, to_slot, type]；
    // 有的版本给对象形状，两种都认。
    if (Object.prototype.toString.call(link) === '[object Array]' && link.length >= 5) {
      out.push({ from: link[1], from_slot: link[2], to: link[3], to_slot: link[4] });
    } else if (typeof link === 'object') {
      out.push({
        from: link.origin_id,
        from_slot: link.origin_slot,
        to: link.target_id,
        to_slot: link.target_slot,
      });
    }
  }
  return out;
}

function canvasSnapshot(args) {
  var app = canvasApp();
  var data = canvasGraph(app);
  var includeWidgets = !!(args && args.include_widgets);
  var all = data.nodes || [];
  var nodes = [];
  for (var i = 0; i < all.length && i < CANVAS_MAX_NODES; i++) {
    nodes.push(canvasNodeSummary(all[i], includeWidgets));
  }
  var shot = {
    node_count: all.length,
    link_count: (data.links || []).length,
    nodes: nodes,
    links: canvasLinks(data),
    truncated: all.length > nodes.length,
  };
  var ds = (data.extra && data.extra.ds) || {};
  if (ds.filename) shot.workflow_name = String(ds.filename);
  return shot;
}

function canvasLoadWorkflow(args) {
  var app = canvasApp();
  if (typeof app.loadGraphData !== 'function') {
    throw new Error('这个前端没有 app.loadGraphData()：载不进工作流');
  }
  var graph = args && args.graph;
  if (!graph || typeof graph !== 'object') {
    throw new Error('graph 必须是工作流 JSON 对象');
  }
  var name = args.name;
  // 后两个 true 是前端自己在“共享工作流”那条路上用的同款参数（clear / 重置视图），
  // 没给名字就只传三个参数，免得塞一个 undefined 进去。
  var call = name
    ? app.loadGraphData(graph, true, true, name)
    : app.loadGraphData(graph, true, true);
  return Promise.resolve(call).then(function () {
    var data = canvasGraph(app);
    return { loaded: true, node_count: (data.nodes || []).length };
  });
}

var CANVAS_OPS = { snapshot: canvasSnapshot, load_workflow: canvasLoadWorkflow };

// 壳那边只认 {ok, result} / {ok:false, error}：抛出去会变成一次 executeJavaScript
// 的 reject，措辞就丢了，所以这里自己把错误翻成结构化的回话。
STATE.canvasCall = function (op, args) {
  function failed(err) {
    return { ok: false, error: String((err && err.message) || err) };
  }
  var run = CANVAS_OPS[op];
  if (!run) {
    return Promise.resolve(failed(new Error('不认识的画布动作: ' + op)));
  }
  try {
    return Promise.resolve(run(args || {})).then(function (result) {
      return { ok: true, result: result };
    }, failed);
  } catch (err) {
    return Promise.resolve(failed(err));
  }
};

// ---- 审核节点：agent 停下来问用户 ---------------------------------------

// 宿主那张 review__ask_user 会一直挂着等回答（见 lib/comfy_studio/review.py），
// 这张卡片就是它等的那个回答。答完用 agent/answer 送回去；送晚了（宿主那边已经超时、
// 或者这一轮被停掉）不算错误——宿主回 delivered:false，这里把卡片标成"没被用上"。
function addAskUser(params) {
  var card = makeRow('ask');
  card.setAttribute('data-state', 'waiting');
  var callId = params && params.call_id != null ? String(params.call_id) : '';

  var question = document.createElement('div');
  question.className = 'cs-ask-q';
  // 没有 question 是宿主/模型那头的问题，但卡片照样画出来让人看见，不静默吞掉。
  question.textContent = String((params && params.question) || '（没问题内容）');
  card.appendChild(question);

  var note = document.createElement('div');
  note.className = 'cs-ask-note';

  function finish(text) {
    // 一次只送一条：state 一离开 waiting 就锁住，省得双击把同一个回答送两遍。
    if (card.getAttribute('data-state') !== 'waiting') return;
    if (text === '') return;
    if (callId === '') {
      card.setAttribute('data-state', 'failed');
      note.textContent = '这张卡片没带 call_id，回答送不回去';
      return;
    }
    card.setAttribute('data-state', 'sending');
    note.textContent = '正在送回宿主…';
    Promise.resolve(bridge.request('agent/answer', { call_id: callId, answer: text })).then(
      function (response) {
        if (!response || response.ok !== true) {
          var error = (response && response.error) || {};
          card.setAttribute('data-state', 'failed');
          note.textContent = '回答没送到: ' + (error.message || '未知错误');
          return;
        }
        if (!response.result || response.result.delivered !== true) {
          // 幂等：这一轮已经不等了（超时、被停、已经收过）。人答晚了不是错误。
          card.setAttribute('data-state', 'stale');
          note.textContent = '这一轮已经不等了（超时或已停），回答没被用上';
          return;
        }
        card.setAttribute('data-state', 'answered');
        note.textContent = '已回答：' + text;
      },
      function (err) {
        card.setAttribute('data-state', 'failed');
        note.textContent = '回答没送到: ' + message(err);
      }
    );
  }

  var options = (params && params.options) || [];
  if (options.length) {
    var row = document.createElement('div');
    row.className = 'cs-ask-options';
    for (var i = 0; i < options.length; i++) {
      var option = document.createElement('button');
      option.type = 'button';
      option.className = 'cs-ask-option';
      var label = String(options[i]);
      option.textContent = label;
      // 点选项 = 拿那一条当回答，跟手打进去走同一条路。
      option.addEventListener(
        'click',
        (function (chosen) {
          return function () {
            finish(chosen);
          };
        })(label)
      );
      row.appendChild(option);
    }
    card.appendChild(row);
  }

  var form = document.createElement('form');
  form.className = 'cs-ask-form';
  var input = document.createElement('input');
  input.type = 'text';
  input.className = 'cs-ask-input';
  input.placeholder = options.length ? '或直接回答…' : '直接回答…';
  input.setAttribute('aria-label', '回答 agent 的问题');
  var send = document.createElement('button');
  send.type = 'submit';
  send.className = 'cs-ask-send';
  send.textContent = '回答';
  form.appendChild(input);
  form.appendChild(send);
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    finish(input.value.trim());
  });
  card.appendChild(form);
  card.appendChild(note);

  appendNode(card);
  // 抽屉开着就把光标送进输入框：问题是为它弹出来的，人正要回它。
  if (STATE.open) input.focus();
  return card;
}

// ---- 灵感输入：一句话拆成多步清单 ---------------------------------------

// 宿主那张 plan__submit（见 lib/comfy_studio/plan.py）会挂着等用户过目：
// 点「就按这个来」= approved:true；点「改一下」再写一句 = approved:false + feedback。
// 两条都经 agent/plan_result 送回宿主；送晚了（超时、或这一轮已经停了）宿主回
// delivered:false —— 跟审核一样是"晚了"而不是"错了"。
var PLAN_STEP_LABEL = { running: '进行中', done: '完成', failed: '失败', skipped: '跳过' };

function addPlan(params) {
  var card = makeRow('plan');
  card.setAttribute('data-state', 'waiting');
  var callId = params && params.call_id != null ? String(params.call_id) : '';

  var goal = document.createElement('div');
  goal.className = 'cs-plan-goal';
  // 没有 goal 是宿主/模型那头的问题，清单照样画出来让人看见，别静默吞掉。
  goal.textContent = String((params && params.goal) || '（没说要做什么）');
  card.appendChild(goal);

  var steps = (params && params.steps) || [];
  var list = document.createElement('ol');
  list.className = 'cs-plan-steps';
  for (var i = 0; i < steps.length; i++) {
    var item = steps[i] || {};
    var step = document.createElement('li');
    step.className = 'cs-plan-step';
    step.setAttribute('data-step', String(i + 1));
    step.setAttribute('data-step-state', 'pending');
    var title = document.createElement('div');
    title.textContent = String(item.title || '（这一步没写做什么）');
    step.appendChild(title);
    if (item.tool) {
      var tool = document.createElement('div');
      tool.className = 'cs-plan-tool';
      tool.textContent = String(item.tool);
      step.appendChild(tool);
    }
    if (item.detail) {
      var detail = document.createElement('div');
      detail.className = 'cs-plan-detail';
      detail.textContent = String(item.detail);
      step.appendChild(detail);
    }
    list.appendChild(step);
  }
  card.appendChild(list);

  if (params && params.notes) {
    var notes = document.createElement('div');
    notes.className = 'cs-plan-notes';
    notes.textContent = String(params.notes);
    card.appendChild(notes);
  }

  var note = document.createElement('div');
  note.className = 'cs-plan-note';

  function finish(approved, feedback) {
    // 一次只送一条：state 一离开 waiting/editing 就锁住，省得双击送两遍。
    var state = card.getAttribute('data-state');
    if (state !== 'waiting' && state !== 'editing') return;
    if (callId === '') {
      card.setAttribute('data-state', 'failed');
      note.textContent = '这张清单没带 call_id，态度送不回去';
      return;
    }
    card.setAttribute('data-state', 'sending');
    note.textContent = approved ? '已认可，正在送回宿主…' : '正在把要改的地方送回宿主…';
    Promise.resolve(
      bridge.request('agent/plan_result', {
        call_id: callId,
        approved: approved,
        feedback: feedback,
      })
    ).then(
      function (response) {
        if (!response || response.ok !== true) {
          var error = (response && response.error) || {};
          card.setAttribute('data-state', 'failed');
          note.textContent = '没送到: ' + (error.message || '未知错误');
          return;
        }
        var result = response.result || {};
        if (result.delivered !== true) {
          card.setAttribute('data-state', 'stale');
          note.textContent = '这一轮已经不等了（超时或已停），这份态度没被用上';
          return;
        }
        card.setAttribute('data-state', approved ? 'approved' : 'rejected');
        note.textContent = approved ? '已认可，照清单走' : '已经说了要改：' + feedback;
      },
      function (err) {
        card.setAttribute('data-state', 'failed');
        note.textContent = '没送到: ' + message(err);
      }
    );
  }

  var actions = document.createElement('div');
  actions.className = 'cs-plan-actions';
  var approve = document.createElement('button');
  approve.type = 'button';
  approve.className = 'cs-plan-ok';
  approve.textContent = '就按这个来';
  approve.addEventListener('click', function () {
    finish(true, '');
  });
  var change = document.createElement('button');
  change.type = 'button';
  change.className = 'cs-plan-change';
  change.textContent = '改一下';
  change.addEventListener('click', function () {
    card.setAttribute('data-state', 'editing');
    note.textContent = '要改哪里？写一句再送';
    feedback.focus();
  });
  actions.appendChild(approve);
  actions.appendChild(change);
  card.appendChild(actions);

  var form = document.createElement('form');
  form.className = 'cs-plan-feedback';
  var feedback = document.createElement('textarea');
  feedback.className = 'cs-plan-input';
  feedback.rows = 2;
  feedback.placeholder = '例如：第 2 步换成 Flux 那套';
  feedback.setAttribute('aria-label', '要改的地方');
  var send = document.createElement('button');
  send.type = 'submit';
  send.className = 'cs-plan-ok';
  send.textContent = '把改动送回去';
  form.appendChild(feedback);
  form.appendChild(send);
  form.addEventListener('submit', function (event) {
    event.preventDefault();
    var text = feedback.value.trim();
    if (text === '') {
      // 否掉却没说改什么，宿主那边也会挡（agent/plan_result 要求 feedback 非空）：
      // 就地提示一句，省得白跑一趟再被退回来。
      note.textContent = '要改哪里，写一句再送';
      feedback.focus();
      return;
    }
    finish(false, text);
  });
  card.appendChild(form);
  card.appendChild(note);

  appendNode(card);
  // 记下这一轮的清单卡：plan__progress 的事件要回来找它打勾（每轮至多一张）。
  STATE.planCard = card;
  if (STATE.open) feedback.focus();
  return card;
}

// plan__progress：单向通知。回来要么给清单里的某一步打勾，要么另起一行说明。
function markPlanStep(params) {
  var step = params && params.step != null ? String(params.step) : '';
  var status = String((params && params.status) || '');
  var note = params && params.note ? String(params.note) : '';
  var label = PLAN_STEP_LABEL[status] || status || '更新';
  var card = STATE.planCard && STATE.planCard.parentNode ? STATE.planCard : null;
  var item = card ? card.querySelector('.cs-plan-step[data-step="' + step + '"]') : null;
  if (!item) {
    // 对不上清单也照样让人看见（模型可能自己报进度，或者面板刚重开）：
    // 宁可多一行，也别把进度静默丢掉。
    var line = makeRow('agent');
    line.textContent = '计划第 ' + (step || '?') + ' 步 ' + label + (note ? '：' + note : '');
    return appendNode(line);
  }
  item.setAttribute('data-step-state', status || 'pending');
  if (note !== '') {
    var detail = item.querySelector('.cs-plan-progress');
    if (!detail) {
      detail = document.createElement('div');
      detail.className = 'cs-plan-progress';
      item.appendChild(detail);
    }
    detail.textContent = note;
  }
  scrollLog(logEl());
  return item;
}

start();
`

export function getComfyStudioChatContentScript(): string {
  if (cachedScript) return cachedScript
  cachedScript =
    `(function () {\n` +
    `'use strict';\n` +
    `if (typeof window === 'undefined' || !window.__comfyDesktop2) return;\n` +
    `if (!window.__comfyDesktop2.ComfyStudio) return;\n` +
    `if (window.__comfyStudioChat) return;\n` +
    `window.__comfyStudioChat = { started: false, open: false, busy: false, turn: null, ` +
    `model: '', agent: '', session: 'default', sessions: null, closeArmed: false, ` +
    `remembered: '', archive: null, pending: null, paint: 0, cards: {}, planCard: null, ` +
    // 一轮在飞时的读数：什么时候开始的、每秒刷新的计时器、宿主报的重试说明，以及等太久
    // 之后摆出来的"强制复位"按钮（见 paintTurnClock / offerForceReset）。
    `pendingLabel: null, turnStartedAt: 0, turnTimer: null, turnNote: '', forceReset: null, ` +
    `finishTurn: null, softWarned: false, ` +
    // 界面已经放手、宿主那一轮却还占着这个会话（强行复位之后就是这个局面，见 forceResetTurn）。
    // 它决定"停止"键以哪种身份露面（见 setStopVisible），也决定那颗键还能不能按。
    `detached: false, ` +
    // 抽屉里的四页（'chat' / 'novel' / 'project' / 'pipeline'）与小说那一页的当前状态：
    // 列表那一趟的票、正开着的是哪一篇（含它自己那趟读的票）、删除按到第二步的是哪一行。
    `view: 'chat', novels: null, novelOpen: null, novelDeleteArmed: null, novelListToken: 0, ` +
    // 项目那一页的当前状态：项目列表那一趟的票、正开着的是哪一部（含它那趟 tree 的票、
    // 正读着哪份文件与第几页）。票都是为了防止"慢回话盖掉新界面"：换一部剧时旧请求还在飞。
    `projects: null, projectOpen: null, projectListToken: 0, projectFind: '', projectFindTimer: null, ` +
    // 流水线那一页（见 buildPipelineView）：计划那一趟的票、下拉里选中的剧目、
    // 跑起来之后逐段收到的归宿（按阶段代码索引，pipeline/event 推一条更新一格）、
    // 以及"现在跑着没有"。跑的时候这一页不接受第二次按键 —— 宿主那边同项目第二条本来也会拒。
    `pipeline: null, pipelineToken: 0, pipelineProject: '', pipelineStages: null, ` +
    `pipelineBusy: false, ` +
    // 项目正文里的"页内找字"（见 paintProjectReader）：找的是哪串字、命中在哪几处、现在停在第几处。
    `projectFileFind: '', projectFileFindHits: [], projectFileFindAt: -1, ` +
    // 左栏（目录树 / 搜索结果）：开着没有，以及里面是哪一篇的哪一趟（含它自己那趟的票）。
    `novelSideOpen: true, novelSide: null, ` +
    // 输入框上方那几张引用卡（下一轮要带上的原文；发出去就清）。
    `quotes: [], ` +
    // 引擎报回来的 skill 目录，以及"现在正跑着哪一个"（同一时刻只跑一个：引擎那边跑一次
    // 要占住显存，叠着跑只会两边都慢）。
    `skills: null, skill: '', skillRunning: '', ` +
    // 引擎报回来的渲染目标（那 12 张生产工作流 + 工作流目录在哪），以及"现在正跑着哪一个"。
    // 与 skill 那一份同一个道理：一次只跑一个（渲染一次要占满显存好些分钟）。
    `renders: null, render: '', renderRunning: '', rendersDir: '', rendersNote: '', ` +
    // 抽屉宽度（像素，0 = 占满整屏）与"窗口变窄要收回来"的监听装没装。
    `width: 0, widthWatcher: false, shortcuts: false, ` +
    // 这一份实例建的那面抽屉（见 buildDrawer）。宿主刷新网页后旧实例还在监听按键，
    // 靠它认得出"我已经不在页面上了"，不至于伸手去动新实例那面抽屉。
    `drawer: null };\n` +
    STUDIO_CHAT_MAIN_JS +
    `})();\n`
  return cachedScript
}
