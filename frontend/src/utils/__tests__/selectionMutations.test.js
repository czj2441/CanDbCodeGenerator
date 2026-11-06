import { test } from 'node:test'
import assert from 'node:assert'
import { readdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const componentDir = join(dirname(fileURLToPath(import.meta.url)), '../../components')
const files = readdirSync(componentDir).filter(f => f.endsWith('.vue'))

const FORBIDDEN = [
  { pattern: /\.selectedSignalName\s*=(?!=)/, hint: 'ui.selectSignal() 或 ui.clearSignalSelection()' },
  { pattern: /\.selectedVtName\s*=(?!=)/, hint: 'ui.selectValueTable()' },
  { pattern: /\.selectedMsgId\s*=(?!=)/, hint: 'messages.selectMessage()' },
]

test('组件不得直接赋值选中状态', () => {
  const offenders = []
  for (const file of files) {
    const source = readFileSync(join(componentDir, file), 'utf8')
    for (const { pattern, hint } of FORBIDDEN) {
      const match = source.match(pattern)
      if (match) offenders.push(`${file}: "${match[0]}" — 请使用 ${hint}`)
    }
  }
  assert.deepEqual(offenders, [])
})