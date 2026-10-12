/* Live runtime for Claude Design ".dc.html" components — Twasta's own.
 *
 * ONE evaluator of the design-component format, used twice:
 *   - a smart page's custom component (`custom_code` with
 *     `component: { format: "dc", source }`) renders a Claude Design component
 *     VERBATIM inside its sandboxed frame — infographics computed in
 *     renderVals(), charts drawn in componentDidMount through a ref, timers,
 *     clickable tabs and toggles (customFrame.ts inlines this file);
 *   - the design importer's capture (backend services/design_import/render.py)
 *     serves this same file in place of the editor's "./support.js", so what
 *     was captured is what a page renders.
 *
 * The format (the Design type's own reference): plain HTML inside <x-dc>;
 * <helmet> for page-level <style>/<link>; {{dotted.path}} holes (never
 * expressions); <sc-if value>, <sc-for list as>, <dc-import name>; and
 * `class Component extends DCLogic { renderVals() }` in
 * <script type="text/x-dc" data-dc-script data-props='{...}'>. We never copy
 * the editor's runtime — this is a small, independent implementation.
 *
 * Live behaviour: setState() re-renders (batched per microtask) by MORPHING
 * the DOM — elements of the same tag are kept and patched, so a canvas, a
 * focused input or a chart a library drew into an empty ref'd <div> survive
 * a state change; a hole bound to an event prop (onClick="{{pick}}") becomes a
 * listener; ref="{{r}}" fills r.current (or calls r(el)); componentDidMount /
 * componentDidUpdate / componentWillUnmount run around renders. A child <dc-import> keeps its
 * instance (and state) across renders by position.
 *
 * Control tags must be parsed as <template data-sc="for|if|import">: an
 * unknown <sc-for> inside a <tbody> is foster-parented out of the table by
 * the HTML parser, a <template> is not. Hosts rewrite them before the
 * document is parsed (customFrame.prepDcSource, render.py _prep_html);
 * prep() below does the same for child sources it parses itself.
 *
 * Hooks for the importer's capture: ?dcstate=<handler> calls that
 * zero-argument top-level handler before the first render (one capture per
 * state); window.__dcInfo = {ok, error, handlers, state, sampleText,
 * sampleImages}; <html data-dc-rendered="1|error"> when done.
 * Hooks for a host: window.__DC_PROPS__ overrides the data-props defaults;
 * window.__DC_CHILDREN__ = {Name: source} supplies <dc-import> children
 * (else a same-folder fetch, as on the capture server).
 */
(function () {
  'use strict'
  var MAX_IMPORT_DEPTH = 4
  var MAX_SAMPLE_CHARS = 20000
  // sampleText: what <sc-for> repeats drew on the FIRST render — a design's
  // SAMPLE rows (product cards, order lines). A page bound to live data shows
  // other rows there, so the importer's fidelity check discounts them.
  var info = { ok: false, error: null, handlers: [], state: null, sampleText: [], sampleImages: [] }
  var sampleChars = 0
  var collecting = true
  window.__dcInfo = info

  function noteSample(node) {
    if (!collecting || sampleChars > MAX_SAMPLE_CHARS) return
    if (node.nodeType === 1) {
      var imgs = node.tagName.toLowerCase() === 'img' ? [node] : node.querySelectorAll('img')
      for (var i = 0; i < imgs.length && info.sampleImages.length < 200; i++) {
        var src = imgs[i].getAttribute('src')
        if (src) info.sampleImages.push(src)
      }
    }
    var t = (node.textContent || '').replace(/\s+/g, ' ').trim()
    if (!t) return
    sampleChars += t.length
    info.sampleText.push(t)
  }

  // ── the component base class ─────────────────────────────────────────────
  var scheduled = false
  var renderRoot = null // set once the root is mounted

  function scheduleRender() {
    if (!renderRoot || scheduled) return
    scheduled = true
    Promise.resolve().then(function () {
      scheduled = false
      renderRoot()
    })
  }

  function DCLogic(props) {
    this.props = props || {}
    this.state = {}
  }
  DCLogic.prototype.setState = function (patch, cb) {
    var next = typeof patch === 'function' ? patch(this.state, this.props) : patch
    if (next && typeof next === 'object') {
      var copy = {}
      for (var k in this.state) if (Object.prototype.hasOwnProperty.call(this.state, k)) copy[k] = this.state[k]
      for (var j in next) if (Object.prototype.hasOwnProperty.call(next, j)) copy[j] = next[j]
      this.state = copy
    }
    if (typeof cb === 'function') afterRender.push(cb)
    scheduleRender()
  }
  DCLogic.prototype.forceUpdate = function (cb) {
    if (typeof cb === 'function') afterRender.push(cb)
    scheduleRender()
  }
  window.DCLogic = DCLogic

  var afterRender = []

  function defaultsFrom(script) {
    var props = {}
    var raw = script && script.getAttribute('data-props')
    if (!raw) return props
    try {
      var spec = JSON.parse(raw)
      for (var k in spec) {
        if (k.charAt(0) === '$') continue
        var v = spec[k]
        if (v && typeof v === 'object' && 'default' in v) props[k] = v['default']
      }
    } catch (e) {
      info.error = 'data-props is not valid JSON: ' + e.message
    }
    return props
  }

  function componentClass(script) {
    var src = (script && script.textContent) || ''
    if (!/class\s+Component\b/.test(src)) return null
    // Classic JS by contract (no import/export). It runs in the page, which
    // every host sandboxes (an opaque-origin frame) and fences.
    return new Function('DCLogic', src + '\n;return Component;')(DCLogic)
  }

  function instantiate(Cls, props) {
    if (!Cls) return null
    var inst = new Cls(props)
    if (!inst.props) inst.props = props
    if (!inst.state) inst.state = {}
    if (typeof inst.componentWillMount === 'function') {
      try { inst.componentWillMount() } catch (e) { report(e) }
    }
    return inst
  }

  function valsOf(inst) {
    if (!inst || typeof inst.renderVals !== 'function') return {}
    var v = inst.renderVals()
    return v && typeof v === 'object' ? v : {}
  }

  // ── holes ────────────────────────────────────────────────────────────────
  var WHOLE = /^\s*\{\{\s*([^{}]+?)\s*\}\}\s*$/
  var ANY = /\{\{\s*([^{}]+?)\s*\}\}/g

  function literal(path) {
    if (path === 'true') return { v: true }
    if (path === 'false') return { v: false }
    if (path === 'null') return { v: null }
    if (/^-?\d+(\.\d+)?$/.test(path)) return { v: Number(path) }
    var m = /^'(.*)'$|^"(.*)"$/.exec(path)
    if (m) return { v: m[1] !== undefined ? m[1] : m[2] }
    return null
  }

  function lookup(path, scope) {
    var lit = literal(path)
    if (lit) return lit.v
    var parts = path.split('.')
    var cur = scope
    for (var i = 0; i < parts.length; i++) {
      if (cur === null || cur === undefined) return undefined
      cur = cur[parts[i]]
    }
    return cur
  }

  function str(v) {
    if (v === null || v === undefined || typeof v === 'function') return ''
    if (typeof v === 'object') return ''
    return String(v)
  }

  function interpolate(text, scope) {
    return text.replace(ANY, function (_m, p) { return str(lookup(p.trim(), scope)) })
  }

  function holeValue(raw, scope) {
    var m = WHOLE.exec(raw || '')
    return m ? lookup(m[1].trim(), scope) : raw
  }

  // JSX-style event prop → DOM event name. React's onChange on a text field
  // fires per keystroke, which is the DOM 'input' event.
  function eventName(prop, el) {
    var ev = prop.slice(2).toLowerCase()
    if (ev === 'change') {
      var t = (el.getAttribute && (el.getAttribute('type') || '')).toLowerCase()
      var tag = el.tagName.toLowerCase()
      if ((tag === 'input' && t !== 'checkbox' && t !== 'radio' && t !== 'file') || tag === 'textarea') return 'input'
    }
    if (ev === 'doubleclick') return 'dblclick'
    return ev
  }

  // ── expansion ────────────────────────────────────────────────────────────
  function scKind(node, tag) {
    if (tag === 'template' && node.hasAttribute('data-sc')) return node.getAttribute('data-sc')
    if (tag === 'sc-for') return 'for'
    if (tag === 'sc-if') return 'if'
    if (tag === 'dc-import') return 'import'
    return null
  }

  function prep(html) {
    return html
      .replace(/<sc-(for|if)\b/gi, '<template data-sc="$1"')
      .replace(/<\/sc-(?:for|if)\s*>/gi, '</template>')
      .replace(/<dc-import\b/gi, '<template data-sc="import"')
      .replace(/<\/dc-import\s*>/gi, '</template>')
  }

  function Ctx(depth) {
    this.depth = depth
    this.importSeq = 0
  }

  function expandChildren(src, scope, ctx) {
    var out = []
    var kids = src.childNodes
    for (var i = 0; i < kids.length; i++) {
      var r = expandNode(kids[i], scope, ctx)
      for (var j = 0; j < r.length; j++) out.push(r[j])
    }
    return out
  }

  function expandNode(node, scope, ctx) {
    if (node.nodeType === 3) {
      var t = node.nodeValue
      return [document.createTextNode(t.indexOf('{{') >= 0 ? interpolate(t, scope) : t)]
    }
    if (node.nodeType !== 1) return []
    var tag = node.tagName.toLowerCase()
    var kind = scKind(node, tag)
    // Inside an <svg> a <template> is an SVG-namespace element with no
    // .content — its children are the body (bars in an <sc-for>).
    var body = node.content || node

    if (kind === 'for') {
      var list = holeValue(node.getAttribute('list'), scope)
      var as = node.getAttribute('as') || 'item'
      var out = []
      if (Array.isArray(list)) {
        for (var i = 0; i < list.length; i++) {
          var s = Object.create(scope)
          s[as] = list[i]
          s.$index = i
          var r = expandChildren(body, s, ctx)
          for (var j = 0; j < r.length; j++) {
            out.push(r[j])
            noteSample(r[j])
          }
        }
      }
      return out
    }
    if (kind === 'if') {
      return holeValue(node.getAttribute('value'), scope) ? expandChildren(body, scope, ctx) : []
    }
    if (kind === 'import') return importChild(node, scope, ctx)
    if (tag === 'script' && node.hasAttribute('data-dc-script')) return []

    // Same namespace as the parsed source: an <svg>/<path> made with plain
    // createElement is an unknown HTML element and draws nothing.
    var el = node.namespaceURI && node.namespaceURI !== 'http://www.w3.org/1999/xhtml'
      ? document.createElementNS(node.namespaceURI, node.localName)
      : document.createElement(tag)
    for (var a = 0; a < node.attributes.length; a++) {
      var name = node.attributes[a].name
      var val = node.attributes[a].value
      var ns = node.attributes[a].namespaceURI
      if (/^hint-/.test(name)) continue
      var whole = WHOLE.exec(val)
      if (whole) {
        var v = lookup(whole[1].trim(), scope)
        // The HTML parser lower-cases attribute names: onClick arrives as
        // "onclick". A hole on an on* attribute is an event prop.
        if (/^on[a-z]/i.test(name)) {
          if (typeof v === 'function') bindEvent(el, name, v)
          continue
        }
        if (name === 'ref') {
          bindRef(el, v)
          continue
        }
        if (typeof v === 'function' || v === false || v === null || v === undefined) continue
        if (name === 'value' && (tag === 'input' || tag === 'textarea' || tag === 'select')) el.__dcValue = str(v)
        if (name === 'checked' && tag === 'input') el.__dcChecked = !!v
        setAttr(el, ns, name, v === true ? '' : str(v))
      } else if (/^on/i.test(name)) {
        continue // inline string handlers never run
      } else {
        setAttr(el, ns, name, val.indexOf('{{') >= 0 ? interpolate(val, scope) : val)
      }
    }
    var srcKids = node.content || node
    // An element the template leaves EMPTY is the script's to fill (a chart
    // drawn into a ref'd <div>, a canvas): a re-render never touches its
    // children — the way React leaves a ref container alone.
    if (!srcKids.childNodes.length) el.__dcEmpty = true
    var kids = expandChildren(srcKids, scope, ctx)
    var host = tag === 'template' ? el.content : el
    for (var k = 0; k < kids.length; k++) host.appendChild(kids[k])
    return [el]
  }

  // Handlers live in el.__dcEvents and run through ONE dispatcher per event
  // type, so a re-render that KEEPS the element only swaps the handler.
  function dispatch(e) {
    var fn = this.__dcEvents && this.__dcEvents[e.type]
    if (typeof fn === 'function') {
      try { fn(e) } catch (err) { report(err) }
    }
  }

  function ensureListeners(el) {
    var evs = el.__dcEvents
    if (!evs) return
    el.__dcBound = el.__dcBound || {}
    for (var t in evs) {
      if (!el.__dcBound[t]) {
        el.addEventListener(t, dispatch)
        el.__dcBound[t] = true
      }
    }
  }

  function bindEvent(el, prop, fn) {
    el.__dcEvents = el.__dcEvents || {}
    el.__dcEvents[eventName(prop, el)] = fn
    ensureListeners(el)
  }

  // Refs are applied once the DOM is final (to the element that SURVIVED
  // the morph, which may be the previous render's).
  function bindRef(el, r) {
    if (r) el.__dcRef = r
  }

  function applyRefs(node) {
    if (node.nodeType !== 1) return
    var all = [node].concat(Array.prototype.slice.call(node.querySelectorAll('*')))
    for (var i = 0; i < all.length; i++) {
      var r = all[i].__dcRef
      if (!r) continue
      if (typeof r === 'function') {
        try { r(all[i]) } catch (e) { report(e) }
      } else if (typeof r === 'object') {
        r.current = all[i]
      }
    }
  }

  // ── morph: patch the live DOM to the new render, keeping nodes ──────────
  function sameKind(a, b) {
    if (a.nodeType !== b.nodeType) return false
    if (a.nodeType !== 1) return true
    return a.localName === b.localName && a.namespaceURI === b.namespaceURI
  }

  function morphElement(live, next) {
    // Attributes: set what changed; remove only ones a render set before.
    var names = []
    for (var i = 0; i < next.attributes.length; i++) {
      var at = next.attributes[i]
      names.push(at.name)
      if (live.getAttribute(at.name) !== at.value) setAttr(live, at.namespaceURI, at.name, at.value)
    }
    var before = live.__dcAttrNames || []
    for (var j = 0; j < before.length; j++) {
      if (names.indexOf(before[j]) < 0) live.removeAttribute(before[j])
    }
    live.__dcAttrNames = names
    live.__dcEvents = next.__dcEvents || null
    ensureListeners(live)
    live.__dcRef = next.__dcRef || null
    if (next.__dcValue !== undefined && live.value !== next.__dcValue) live.value = next.__dcValue
    if (next.__dcChecked !== undefined) live.checked = next.__dcChecked
    if (next.__dcEmpty) {
      live.__dcEmpty = true
      return // the script owns its children
    }
    morphList(live, Array.prototype.slice.call(live.childNodes), Array.prototype.slice.call(next.childNodes), null)
  }

  function adopt(next) {
    // A fresh element joins the DOM: record what a later morph may change.
    if (next.nodeType !== 1) return next
    var all = [next].concat(Array.prototype.slice.call(next.querySelectorAll('*')))
    for (var i = 0; i < all.length; i++) {
      var el = all[i]
      el.__dcAttrNames = Array.prototype.map.call(el.attributes, function (a) { return a.name })
      if (el.__dcValue !== undefined) el.value = el.__dcValue
      if (el.__dcChecked !== undefined) el.checked = el.__dcChecked
    }
    return next
  }

  function morphList(parent, liveNodes, nextNodes, endMarker) {
    var n = Math.max(liveNodes.length, nextNodes.length)
    for (var i = 0; i < n; i++) {
      var live = liveNodes[i]
      var next = nextNodes[i]
      if (!next) {
        parent.removeChild(live)
      } else if (!live) {
        parent.insertBefore(adopt(next), endMarker)
      } else if (!sameKind(live, next)) {
        parent.replaceChild(adopt(next), live)
      } else if (live.nodeType === 1) {
        morphElement(live, next)
      } else if (live.nodeValue !== next.nodeValue) {
        live.nodeValue = next.nodeValue
      }
    }
  }

  function setAttr(el, ns, name, value) {
    try {
      if (ns) el.setAttributeNS(ns, name, value)
      else el.setAttribute(name, value)
    } catch (e) { /* an attribute name the DOM refuses is skipped */ }
  }

  // ── <dc-import> children ─────────────────────────────────────────────────
  var childSources = {}   // name → parsed { tpl, Cls, defaults }
  var childInstances = {} // position key → instance (state survives renders)
  var mountedChildren = []

  function loadChild(name) {
    if (childSources[name] !== undefined) return childSources[name]
    var html = null
    var supplied = window.__DC_CHILDREN__
    if (supplied && typeof supplied[name] === 'string') {
      html = supplied[name]
    } else {
      try {
        var xhr = new XMLHttpRequest()
        xhr.open('GET', name + '.dc.html', false) // same folder only
        xhr.send(null)
        if (xhr.status === 200) html = xhr.responseText
      } catch (e) { html = null }
    }
    if (!html) {
      childSources[name] = null
      return null
    }
    var doc = new DOMParser().parseFromString(prep(html), 'text/html')
    var script = doc.querySelector('script[data-dc-script]')
    var root = doc.querySelector('x-dc')
    if (root) hoistHelmet(root)
    childSources[name] = root ? { tpl: root, Cls: componentClass(script), defaults: defaultsFrom(script) } : null
    return childSources[name]
  }

  function importChild(node, scope, ctx) {
    var name = node.getAttribute('name') || ''
    if (!/^[A-Za-z0-9_][A-Za-z0-9_.-]*$/.test(name) || ctx.depth >= MAX_IMPORT_DEPTH) return []
    var child = loadChild(name)
    if (!child) return []
    var props = {}
    for (var k in child.defaults) props[k] = child.defaults[k]
    for (var a = 0; a < node.attributes.length; a++) {
      var an = node.attributes[a].name
      if (an === 'name' || an === 'data-sc' || /^hint-/.test(an)) continue
      var camel = an.replace(/-([a-z])/g, function (_m, c) { return c.toUpperCase() })
      props[camel] = holeValue(node.attributes[a].value, scope)
    }
    var key = ctx.depth + ':' + name + ':' + (ctx.importSeq++)
    var inst = childInstances[key]
    if (!inst) {
      inst = instantiate(child.Cls, props)
      childInstances[key] = inst
      if (inst) mountedChildren.push(inst)
    } else {
      inst.props = props
    }
    return expandChildren(child.tpl, valsOf(inst), new Ctx(ctx.depth + 1))
  }

  function hoistHelmet(root) {
    var helmets = root.querySelectorAll('helmet')
    for (var i = 0; i < helmets.length; i++) {
      var h = helmets[i]
      while (h.firstChild) document.head.appendChild(h.firstChild)
      h.parentNode.removeChild(h)
    }
  }

  function zeroArgHandlers(vals) {
    var names = []
    for (var k in vals) {
      if (typeof vals[k] === 'function' && vals[k].length === 0) names.push(k)
    }
    return names
  }

  function report(e) {
    var msg = (e && e.message) || String(e)
    info.error = msg
    try { console.error('[design component]', e) } catch (x) { /* no console */ }
  }

  // Keep the field being typed in focused across a re-render (matched by id
  // or name — a re-render replaces the elements).
  function rememberFocus(host) {
    var a = document.activeElement
    if (!a || a === document.body || !host.contains(a)) return null
    var id = a.getAttribute('id')
    var name = a.getAttribute('name')
    if (!id && !name) return null
    var r = { id: id, name: name, start: null, end: null }
    try { r.start = a.selectionStart; r.end = a.selectionEnd } catch (e) { /* not a text field */ }
    return r
  }

  function restoreFocus(host, r) {
    if (!r) return
    var el = r.id ? host.querySelector('#' + CSS.escape(r.id))
      : host.querySelector('[name="' + String(r.name).replace(/"/g, '\\"') + '"]')
    if (!el) return
    try {
      el.focus()
      if (r.start !== null && el.setSelectionRange) el.setSelectionRange(r.start, r.end)
    } catch (e) { /* best effort */ }
  }

  // ── mount ────────────────────────────────────────────────────────────────
  function start() {
    var root = document.querySelector('x-dc')
    var script = document.querySelector('script[data-dc-script]')
    if (!root) {
      info.ok = true // plain HTML: nothing to expand
      return
    }
    var props = defaultsFrom(script)
    var over = window.__DC_PROPS__
    if (over && typeof over === 'object') for (var p in over) props[p] = over[p]
    var inst = instantiate(componentClass(script), props)

    hoistHelmet(root)
    var tpl = root.cloneNode(true) // the template every render expands
    // The rendered nodes sit where <x-dc> was, between two markers — no
    // wrapper element, so the DOM is exactly the design's (a display:contents
    // wrapper has no box, and the capture would see an empty page).
    var host = root.parentNode
    var begin = document.createComment('dc')
    var finish = document.createComment('/dc')
    host.insertBefore(begin, root)
    host.replaceChild(finish, root)
    if (script && script.parentNode) script.parentNode.removeChild(script)

    var first = true
    renderRoot = function () {
      afterRender = afterRender || []
      var focus = first ? null : rememberFocus(host)
      var vals
      try {
        vals = valsOf(inst)
      } catch (e) {
        report(e)
        return
      }
      if (first) info.handlers = zeroArgHandlers(vals)
      var nodes = expandChildren(tpl, vals, new Ctx(0))
      var live = []
      for (var cur = begin.nextSibling; cur && cur !== finish; cur = cur.nextSibling) live.push(cur)
      morphList(host, live, nodes, finish)
      for (var r = begin.nextSibling; r && r !== finish; r = r.nextSibling) applyRefs(r)
      restoreFocus(host, focus)
      var queue = afterRender
      afterRender = []
      for (var q = 0; q < queue.length; q++) {
        try { queue[q]() } catch (e) { report(e) }
      }
      if (first) {
        first = false
        collecting = false
        for (var c = 0; c < mountedChildren.length; c++) lifecycle(mountedChildren[c], 'componentDidMount')
        lifecycle(inst, 'componentDidMount')
      } else {
        lifecycle(inst, 'componentDidUpdate')
      }
    }

    // A capture of one STATE: call that handler before the first render.
    var want = (/[?&]dcstate=([A-Za-z0-9_$]+)/.exec(location.search) || [])[1]
    if (want && inst) {
      var v0 = valsOf(inst)
      if (typeof v0[want] === 'function') {
        v0[want]()
        info.state = want
      }
    }
    scheduled = false
    renderRoot()
    info.ok = !info.error
    window.addEventListener('pagehide', function () {
      lifecycle(inst, 'componentWillUnmount')
      for (var c = 0; c < mountedChildren.length; c++) lifecycle(mountedChildren[c], 'componentWillUnmount')
    })
  }

  function lifecycle(inst, name) {
    if (inst && typeof inst[name] === 'function') {
      try { inst[name]() } catch (e) { report(e) }
    }
  }

  function run() {
    try {
      start()
    } catch (e) {
      report(e)
    }
    info.ok = info.ok && !info.error
    document.documentElement.setAttribute('data-dc-rendered', info.error ? 'error' : '1')
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', run)
  else run()
})()
