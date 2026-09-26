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
 * Turn model: one turn at a time. `agent/event` notifications are not addressed
 * to a specific turn (they carry the request id, not something the surface
 * tracks), so the drawer only paints events while a turn is in flight and
 * ignores `final` — the final answer already comes back as the request result,
 * and painting both would duplicate it.
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

function appendMessage(kind, text) {
  var log = document.getElementById(LOG_ID);
  if (!log) return null;
  var row = document.createElement('div');
  row.setAttribute('data-kind', kind);
  var base = 'white-space:pre-wrap;word-break:break-word;padding:6px 8px;border-radius:6px;';
  if (kind === 'user') {
    row.style.cssText = base + 'align-self:flex-end;max-width:85%;background:var(--comfy-input-bg,#3a3a3a);';
  } else if (kind === 'agent') {
    row.style.cssText = base + 'align-self:flex-start;max-width:90%;background:transparent;';
  } else if (kind === 'tool') {
    row.style.cssText =
      base + 'align-self:flex-start;max-width:90%;color:' + MUTED + ';font-family:monospace;font-size:11px;';
  } else {
    row.style.cssText = base + 'align-self:stretch;color:#ff8080;';
  }
  row.textContent = text;
  log.appendChild(row);
  log.scrollTop = log.scrollHeight;
  return row;
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
        appendMessage('error', '切换模型失败: ' + (error.message || '未知错误'));
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
      appendMessage('error', '切换模型失败: ' + message(err));
      setStatus('模型仍是 ' + (previous || '未知'), 'error');
    }
  ).then(settle, settle);
}

// ---- 事件与请求 --------------------------------------------------------

function onEvent(payload) {
  // 只有一轮在跑：这期间来的事件都属于它。
  if (!STATE.turn) return;
  var params = (payload && payload.params) || {};
  var type = params.type;
  if (type === 'assistant') {
    appendMessage('agent', String(params.text || ''));
    return;
  }
  if (type === 'tool_call') {
    appendMessage('tool', '调用 ' + params.name + ' ' + JSON.stringify(params.arguments || {}));
    return;
  }
  if (type === 'tool_result') {
    appendMessage('tool', '← ' + truncate(String(params.text || ''), 400));
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
  appendMessage('user', text);
  setStatus('agent 正在处理…');

  STATE.turn = {};
  var finish = function () {
    STATE.turn = null;
    STATE.busy = false;
    setSendEnabled(true);
    refreshModelEnabled();
  };

  bridge.request('agent/chat', { text: text }).then(
    function (response) {
      if (!response || response.ok !== true) {
        var error = (response && response.error) || {};
        appendMessage('error', '失败: ' + (error.message || '未知错误'));
        setStatus('这一轮失败了', 'error');
        return;
      }
      var answer = response.result && response.result.text;
      appendMessage('agent', typeof answer === 'string' ? answer : JSON.stringify(response.result));
      setStatus('就绪');
    },
    function (err) {
      appendMessage('error', '失败: ' + message(err));
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
    `window.__comfyStudioChat = { started: false, open: false, busy: false, turn: null, model: '' };\n` +
    STUDIO_CHAT_MAIN_JS +
    `})();\n`
  return cachedScript
}
