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
var AGENT_ID = 'comfy-desktop-studio-chat-agent';
var SESSION_ID = 'comfy-desktop-studio-chat-session';
var SESSION_NEW_ID = 'comfy-desktop-studio-chat-session-new';
var SESSION_CLOSE_ID = 'comfy-desktop-studio-chat-session-close';
var STORAGE_ID = 'comfy-desktop-studio-chat-storage';

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
  '#' + DRAWER_ID + ' .cs-tool{align-self:stretch;border:1px solid ' + BORDER + ';padding:0;overflow:hidden;}' +
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
  '#' + DRAWER_ID + ' .cs-plan:not([data-state="waiting"]):not([data-state="editing"]) .cs-plan-feedback{display:none;}';

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

// ---- 抽屉 --------------------------------------------------------------

function buildDrawer() {
  ensureStyle();
  var drawer = document.createElement('aside');
  drawer.id = DRAWER_ID;
  drawer.style.cssText =
    'position:fixed;top:0;right:0;z-index:2000;display:none;flex-direction:column;' +
    'width:380px;max-width:45vw;height:100%;box-sizing:border-box;' +
    'background:' + SURFACE + ';color:' + FG + ';border-left:1px solid ' + BORDER + ';' +
    'font-size:13px;line-height:1.5;';

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

  controls.appendChild(modelLabel);
  controls.appendChild(model);

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
  sessions.style.cssText = 'display:flex;align-items:center;gap:6px;padding:0 12px 8px;';

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

  sessions.appendChild(sessionLabel);
  sessions.appendChild(session);
  sessions.appendChild(sessionNew);
  sessions.appendChild(sessionClose);

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

  var composer = document.createElement('div');
  composer.style.cssText = 'display:flex;gap:6px;padding:10px 12px;border-top:1px solid ' + BORDER + ';';

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
  header.appendChild(title);
  header.appendChild(stop);
  header.appendChild(close);
  drawer.appendChild(header);
  drawer.appendChild(controls);
  drawer.appendChild(agents);
  drawer.appendChild(sessions);
  drawer.appendChild(status);
  drawer.appendChild(storage);
  drawer.appendChild(log);
  drawer.appendChild(composer);
  document.body.appendChild(drawer);
  return drawer;
}

function setStatus(text, tone) {
  var status = document.getElementById(STATUS_ID);
  if (!status) return;
  status.textContent = text;
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
function setStopVisible(visible) {
  var stop = document.getElementById(STOP_ID);
  if (!stop) return;
  stop.style.display = visible ? 'inline-block' : 'none';
  stop.style.opacity = '1';
  stop.disabled = false;
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
  var ids = [SESSION_ID, SESSION_NEW_ID, SESSION_CLOSE_ID];
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
  return row;
}

function addUser(text) {
  var row = makeRow('user');
  row.textContent = text;
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
  return row;
}

function removePending() {
  var row = STATE.pending;
  STATE.pending = null;
  if (row && row.parentNode) row.parentNode.removeChild(row);
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

// ---- 模型切换 ----------------------------------------------------------

function setModelHint(text) {
  var model = document.getElementById(MODEL_ID);
  if (!model) return;
  model.title = text;
}

function fillModels(models, current) {
  var model = document.getElementById(MODEL_ID);
  if (!model) return;
  var list = models || [];
  model.textContent = '';
  for (var i = 0; i < list.length; i++) {
    var option = document.createElement('option');
    option.value = String(list[i]);
    option.textContent = String(list[i]);
    model.appendChild(option);
  }
  if (current) model.value = String(current);
  STATE.model = model.value || '';
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
      fillModels(result.models, result.current);
      if (result.error) {
        // 宿主拿不到服务端清单，只回了当前配置的这一个：说清原因，别让人以为模型就这些
        setModelHint('服务端没给模型列表（' + result.error + '）；这里只有当前配置的模型');
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
  STATE.cards = {};
  STATE.planCard = null;
  STATE.paint = (STATE.paint || 0) + 1;
}

// 新会话的 id 由面板挑：宿主只认"一个字符串"，没聊起来之前这一段在它那儿根本不存在
// （也就不占会话位）。用时间戳生成，宿主那个目录里一眼看得出先后。
function nextSessionId() {
  return 'chat-' + Date.now().toString(36);
}

function newSession() {
  if (STATE.busy) return;
  STATE.closeArmed = false;
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

  setStorage(parts.join('；'), '', where.join(' ｜ '));
}

function switchModel(name) {
  var model = document.getElementById(MODEL_ID);
  if (!model || STATE.busy || name === '' || name === STATE.model) return;
  var previous = STATE.model;
  setModelEnabled(false);
  setStatus('正在切到 ' + name + '…');

  var settle = function () {
    refreshModelEnabled();
  };
  Promise.resolve(bridge.request('agent/model', { model: name })).then(
    function (response) {
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        model.value = previous;
        addError('切换模型失败: ' + (error.message || '未知错误'), error.code);
        setStatus('模型仍是 ' + (previous || '未知'), 'error');
        return;
      }
      var result = response.result || {};
      STATE.model = String(result.model || name);
      model.value = STATE.model;
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
  if (text === '') return;

  STATE.busy = true;
  STATE.closeArmed = false;
  setSendEnabled(false);
  setStopVisible(true);
  refreshModelEnabled(); // 一轮在飞时不换模型、不换会话，免得把这一轮打断或答到别的段上
  refreshAgentEnabled();
  refreshSessionEnabled();
  input.value = '';
  addUser(text);
  setStatus('agent 正在处理…');

  STATE.turn = {};
  STATE.cards = {};
  STATE.planCard = null;
  addPending();
  var finish = function () {
    // 收尾统一摘掉"正在思考"：成功时回答已经插在它前面，失败时错误行也是。
    removePending();
    STATE.turn = null;
    STATE.cards = {};
    STATE.planCard = null;
    STATE.busy = false;
    setSendEnabled(true);
    setStopVisible(false);
    refreshModelEnabled();
    refreshAgentEnabled();
    refreshSessionEnabled();
    // 这一轮可能刚记下一条事或刚把记忆文件弄坏：再看一眼，别让那一行停在旧话上。
    loadStorage();
    // 智能体清单是从盘上现读的：用户可能刚往里丢了一份 md，聊完这句就该看得见。
    loadAgents();
    // 这一轮过后这段对话的样子也变了（第一句话成了它的标题、条数加了）：
    // 清单跟着刷新，用户才看得见"它现在叫什么"。
    loadSessions();
  };

  bridge.request('agent/chat', { text: text, session_id: STATE.session }).then(
    function (response) {
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        addError('失败: ' + (error.message || '未知错误'), error.code);
        setStatus('这一轮失败了', 'error');
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
      setStatus('这一轮失败了', 'error');
    }
  ).then(finish, finish);
}

// 叫停这一轮。真正的收尾（摘下"正在思考"、放开发送键）仍走上面那条 finish，
// 因为停下之后 agent/chat 会正常回一个 cancelled 结果——这里只负责把请求发出去。
function cancelTurn() {
  if (!STATE.busy) return;
  var stop = document.getElementById(STOP_ID);
  if (stop) {
    stop.disabled = true;
    stop.style.opacity = '0.5';
  }
  setStatus('正在停下这一轮…');

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
        // 正常结果正在回来的路上，什么都不用改。
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
  // 关抽屉就把"关掉"的第二次点击收回去：隔了半天再点一下不该把一段对话丢掉。
  STATE.closeArmed = false;
  var input = document.getElementById(INPUT_ID);
  if (input) input.focus();
  refreshStatus();
  loadModels();
  loadAgents();
  loadHistory();
  loadSessions();
  loadStorage();
}

function closeDrawer() {
  var drawer = document.getElementById(DRAWER_ID);
  if (drawer) drawer.style.display = 'none';
  STATE.open = false;
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
    `remembered: '', archive: null, pending: null, paint: 0, cards: {}, planCard: null };\n` +
    STUDIO_CHAT_MAIN_JS +
    `})();\n`
  return cachedScript
}
