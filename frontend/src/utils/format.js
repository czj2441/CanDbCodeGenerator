export function toHex(n) {
  return '0x' + n.toString(16).toUpperCase().padStart(3, '0')
}

export function parseHex(s) {
  return parseInt(s, 16) || 0
}

export function escHtml(s) {
  if (s == null) return ''
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

export function escAttr(s) {
  if (s == null) return ''
  return String(s).replace(/"/g, '&quot;')
}

export function expandTemplate(template, n) {
  return template.replace(/{n(?::(\d+)[dD]?)?}/g, (match, width) => {
    const numStr = String(n)
    if (width) {
      return numStr.padStart(parseInt(width), '0')
    }
    return numStr
  })
}
