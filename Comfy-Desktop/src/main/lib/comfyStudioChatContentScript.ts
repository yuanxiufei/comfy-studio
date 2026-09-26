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
var MODEL_ID = 'comfy-desktop-studio-chat-model';

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
  'color:' + MUTED + ';cursor:pointer;font:inherit;font-size:11px;padding:1px 6px;margin-top:4px;}';

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

  var status = document.createElement('div');
  status.id = STATUS_ID;
  status.textContent = '正在查询宿主状态…';
  status.style.cssText = 'padding:0 12px 8px;color:' + MUTED + ';font-size:11px;';

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
  composer.appendChild(send);
  header.appendChild(title);
  header.appendChild(stop);
  header.appendChild(close);
  drawer.appendChild(header);
  drawer.appendChild(controls);
  drawer.appendChild(status);
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
  // final 不画：最终文本由请求结果给，画两遍就重复了。
}

function sendTurn() {
  if (STATE.busy) return;
  var input = document.getElementById(INPUT_ID);
  if (!input) return;
  var text = (input.value || '').trim();
  if (text === '') return;

  STATE.busy = true;
  setSendEnabled(false);
  refreshModelEnabled(); // 一轮在飞时不换模型，免得把这一轮打断
  input.value = '';
  addUser(text);
  setStatus('agent 正在处理…');

  STATE.turn = {};
  STATE.cards = {};
  addPending();
  var finish = function () {
    // 收尾统一摘掉"正在思考"：成功时回答已经插在它前面，失败时错误行也是。
    removePending();
    STATE.turn = null;
    STATE.cards = {};
    STATE.busy = false;
    setSendEnabled(true);
    refreshModelEnabled();
  };

  bridge.request('agent/chat', { text: text }).then(
    function (response) {
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        addError('失败: ' + (error.message || '未知错误'), error.code);
        setStatus('这一轮失败了', 'error');
        return;
      }
      var answer = response.result && response.result.text;
      addAssistant(typeof answer === 'string' ? answer : JSON.stringify(response.result), 'final');
      setStatus('就绪');
    },
    function (err) {
      addError('失败: ' + message(err));
      setStatus('这一轮失败了', 'error');
    }
  ).then(finish, finish);
}

function refreshStatus() {
  return Promise.resolve(bridge.status()).then(
    function (status) {
      if (!status || status.available !== true) {
        setStatus(status && status.error ? status.error : '宿主不可用', 'error');
        setSendEnabled(false);
        setModelEnabled(false);
        return status;
      }
      setStatus(status.running ? 'MCP 宿主运行中' : '宿主待启动（发消息时自动拉起）');
      setSendEnabled(true);
      refreshModelEnabled();
      return status;
    },
    function (err) {
      setStatus('查询宿主状态失败: ' + message(err), 'error');
      setSendEnabled(false);
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
  var input = document.getElementById(INPUT_ID);
  if (input) input.focus();
  refreshStatus();
  loadModels();
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
    `model: '', session: 'default', pending: null, cards: {} };\n` +
    STUDIO_CHAT_MAIN_JS +
    `})();\n`
  return cachedScript
}
