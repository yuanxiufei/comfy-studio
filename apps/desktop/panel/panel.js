// 依赖 preload 注入的 window.studio（见 src/preload.ts）
const studio = window.studio

const els = {
  list: document.getElementById('skill-list'),
  detail: document.getElementById('detail'),
  empty: document.getElementById('empty'),
  title: document.getElementById('skill-title'),
  desc: document.getElementById('skill-desc'),
  form: document.getElementById('form'),
  run: document.getElementById('run'),
  progress: document.getElementById('progress'),
  error: document.getElementById('error'),
  results: document.getElementById('results'),
}

let skills = []
let current = null

function fieldFor(p) {
  const wrap = document.createElement('div')
  wrap.className = 'field'

  const label = document.createElement('label')
  const name = document.createElement('span')
  name.textContent = p.name
  label.appendChild(name)
  if (p.required) {
    const req = document.createElement('span')
    req.className = 'req'
    req.textContent = ' *'
    label.appendChild(req)
  }
  wrap.appendChild(label)

  let input
  if (p.type === 'boolean') {
    input = document.createElement('input')
    input.type = 'checkbox'
    input.checked = p.default === true
  } else if (p.type === 'string' && (p.name === 'positive' || p.name === 'negative' || (p.description ?? '').includes('提示词'))) {
    input = document.createElement('textarea')
    input.value = p.default !== undefined ? String(p.default) : ''
  } else {
    input = document.createElement('input')
    if (p.type === 'integer' || p.type === 'number') {
      input.type = 'number'
      if (p.type === 'integer') input.step = '1'
      input.value = p.default !== undefined ? String(p.default) : ''
    } else {
      input.type = 'text'
      input.value = p.default !== undefined ? String(p.default) : ''
    }
  }
  input.dataset.paramName = p.name
  input.dataset.paramType = p.type
  wrap.appendChild(input)

  const hint = document.createElement('div')
  hint.className = 'hint'
  hint.textContent = `${p.type} · 注入 ${p.node}.${p.field}${p.description ? ' · ' + p.description : ''}`
  wrap.appendChild(hint)
  return wrap
}

function showSkill(skill) {
  current = skill
  els.empty.hidden = true
  els.detail.hidden = false
  for (const li of els.list.children) li.classList.toggle('active', li.dataset.id === skill.id)
  els.title.textContent = skill.title
  els.desc.textContent = skill.description
  els.form.textContent = ''
  for (const p of skill.params) els.form.appendChild(fieldFor(p))
  els.progress.textContent = ''
  els.error.textContent = ''
  els.results.textContent = ''
  els.run.disabled = false
}

function collectParams() {
  const params = {}
  for (const input of els.form.querySelectorAll('[data-param-name]')) {
    const { paramName, paramType } = input.dataset
    if (paramType === 'boolean') {
      params[paramName] = input.checked
    } else if (paramType === 'integer' || paramType === 'number') {
      if (input.value.trim() !== '') {
        const n = Number(input.value)
        if (Number.isNaN(n)) throw new Error(`参数 ${paramName} 不是数字: ${input.value}`)
        params[paramName] = paramType === 'integer' ? Math.trunc(n) : n
      }
    } else {
      params[paramName] = input.value
    }
  }
  return params
}

async function run() {
  if (current === null) return
  let params
  try {
    params = collectParams()
  } catch (err) {
    els.error.textContent = err.message
    return
  }
  els.run.disabled = true
  els.error.textContent = ''
  els.results.textContent = ''
  els.progress.textContent = '排队中…'
  try {
    const result = await studio.runSkill(current.id, params)
    els.progress.textContent = `完成（prompt ${result.promptId}）`
    for (const img of result.images) {
      const el = document.createElement('img')
      el.src = img.url
      el.title = img.filename
      els.results.appendChild(el)
    }
    if (result.images.length === 0) {
      els.progress.textContent += '（没有图片输出，工作流里是否有 SaveImage 节点？）'
    }
  } catch (err) {
    els.progress.textContent = ''
    els.error.textContent = err instanceof Error ? err.message : String(err)
  } finally {
    els.run.disabled = false
  }
}

studio.onProgress(msg => {
  if (current === null || msg.skillId !== current.id) return
  if (msg.type === 'progress') {
    els.progress.textContent = `节点 ${msg.node ?? ''}: ${msg.value ?? 0}/${msg.max ?? '?'}`
  } else if (msg.type === 'executing' && msg.node !== null && msg.node !== undefined) {
    els.progress.textContent = `执行节点 ${msg.node}…`
  }
})

els.run.addEventListener('click', run)

studio.listSkills().then(list => {
  skills = list
  for (const skill of skills) {
    const li = document.createElement('li')
    li.dataset.id = skill.id
    li.textContent = skill.title
    li.addEventListener('click', () => showSkill(skill))
    els.list.appendChild(li)
  }
})
