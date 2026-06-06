const dict = {
  zh: {
    // TopBar
    'topbar.new': '新建',
    'topbar.history': '历史',
    'topbar.import': '导入',
    'topbar.export': '导出',
    'topbar.save': '保存',
    'topbar.undo': '撤销',
    'topbar.redo': '重做',
    'topbar.log': '操作日志',
    'topbar.connected': '已连接',
    'topbar.offline': '离线',
    'topbar.newConfirmTitle': '创建新会话？',
    'topbar.newConfirmDesc': '当前会话将保存到历史记录，稍后可以从历史记录中恢复。',
    'topbar.newConfirmCancel': '取消',
    'topbar.newConfirmCreate': '创建新会话',
    'topbar.newNamePlaceholder': '输入会话名称...',

    // StatusBar
    'status.message': '报文',
    'status.messages': '报文',
    'status.signal': '信号',
    'status.signals': '信号',
    'status.modified': '已修改',

    // MessageList
    'msglist.title': '报文列表',
    'msglist.addTooltip': '添加报文',
    'msglist.empty': '暂无报文。<br>点击 + 添加一个。',
    'msglist.unnamed': '（未命名）',

    // SignalTable
    'signal.selectMessage': '从左侧选择一个报文以查看其信号。',
    'signal.empty': '未定义信号。<br>点击 + 信号 添加一个。',
    'signal.add': '+ 信号',
    'signal.batch': '批量 +',
    'signal.deleteMsg': '删除报文',
    'signal.thIdx': '#',
    'signal.thName': '名称',
    'signal.thStart': '起始位',
    'signal.thLen': '长度',
    'signal.thOrder': '字节序',
    'signal.thFactor': '系数',
    'signal.thOffset': '偏移',
    'signal.thMin': '最小值',
    'signal.thMax': '最大值',
    'signal.thUnit': '单位',
    'signal.thComment': '注释',

    // MessagePanel
    'panel.empty': '未选择报文。<br>点击左侧报文以编辑其属性。',
    'panel.properties': '报文属性',
    'panel.signalProperties': '信号属性',
    'panel.id': 'ID (hex)',
    'panel.name': '名称',
    'panel.signalName': '名称',
    'panel.dlc': '数据长度',
    'panel.cycle': '周期 (ms)',
    'panel.sender': '发送方',
    'panel.comment': '注释',
    'panel.signalComment': '注释',
    'panel.signalStart': '起始位',
    'panel.signalLength': '长度',
    'panel.signalByteOrder': '字节序',
    'panel.signalFactor': '系数',
    'panel.signalOffset': '偏移',
    'panel.signalMin': '最小值',
    'panel.signalMax': '最大值',
    'panel.signalUnit': '单位',
    'panel.intel': '小端 (Intel)',
    'panel.motorola': '大端 (Motorola)',
    'panel.actions': '操作',
    'panel.signalActions': '信号操作',
    'panel.duplicate': '复制报文',
    'panel.copySignal': '复制信号',
    'panel.deleteSignal': '删除信号',

    // BatchModal
    'batch.title': '批量添加信号',
    'batch.nameTemplate': '名称模板（使用 {n} 表示序号）',
    'batch.nameHint': '使用 {n} 表示 1,2,3 或使用 {n:02d} 表示 01,02,03',
    'batch.count': '数量',
    'batch.startNum': '起始序号',
    'batch.startBit': '起始位',
    'batch.bitStep': '位步长',
    'batch.length': '长度',
    'batch.byteOrder': '字节序',
    'batch.intel': '小端',
    'batch.motorola': '大端',
    'batch.factor': '系数',
    'batch.offset': '偏移',
    'batch.min': '最小值',
    'batch.max': '最大值',
    'batch.unit': '单位',
    'batch.commentTemplate': '注释模板（可选，使用 {n}）',
    'batch.commentHint': '例如：ADC 通道 {n} 原始值',
    'batch.cancel': '取消',
    'batch.create': '创建',

    // HistoryModal
    'history.title': '会话历史',
    'history.empty': '未找到历史会话。',
    'history.delete': '删除',
    'history.deleteConfirm': '永久删除此会话？',

    // ContextMenu
    'ctx.copySignal': '复制信号',
    'ctx.cutSignal': '剪切信号',
    'ctx.pasteSignal': '粘贴信号',
    'ctx.deleteSignal': '删除信号',
    'ctx.copyMessage': '复制报文',
    'ctx.pasteMessage': '粘贴报文',
    'ctx.duplicateMessage': '复制报文',
    'ctx.deleteMessage': '删除报文',

    // Toast messages
    'toast.messageAdded': '报文已添加',
    'toast.messageDeleted': '报文已删除',
    'toast.signalAdded': '信号已添加',
    'toast.signalDeleted': '信号已删除',
    'toast.renamed': '已重命名',
    'toast.sessionLoaded': '会话已加载',
    'toast.sessionDeleted': '会话已删除',
    'toast.newSessionCreated': '新会话已创建',
    'toast.signalCopied': '信号已复制',
    'toast.signalCut': '信号已剪切',
    'toast.signalPasted': '信号已粘贴',
    'toast.messageCopied': '报文已复制',
    'toast.messagePasted': '报文已粘贴',
    'toast.messageDuplicated': '报文已复制',
    'toast.undoSuccess': '已撤销',
    'toast.undoEmpty': '没有可撤销的操作',
    'toast.restored': '已恢复：{name}',
    'toast.serverOffline': '请启动 API 服务器',
    'toast.batchCreated': '已创建 {count} 个信号',
    'toast.batchFailed': '批量创建在第 #{idx} 个失败：{msg}',
    'toast.signalOutOfBounds': '信号 "{name}" 超出范围（DLC={dlc}，最大位 {max}）',
    'toast.signalOverlap': '信号 "{name}" 与 "{other}" 在位 {bits} 重叠',
    'toast.signalAutoFixed': '已自动调整 "{name}" 的起始位为 {start}',
    // Signal validation errors
    'signal.errorsTitle': '信号布局错误',
    'signal.errorOutOfBounds': '{name}：超出范围（位 {bits} > {max}）',
    'signal.errorOverlap': '{name} 与 {other}：重叠（位 {bits}）',
    'signal.fixBtn': '自动修复',
    'signal.noErrors': '无布局错误',

    // Layout view
    'layout.backToTable': '返回表格',
    'layout.viewLayout': '布局视图',
    'layout.noSignals': '未定义信号。',
    'layout.byteLabel': '字节',
    'layout.bitHeader': '位',

    // Log Panel
    'log.title': '操作日志',
    'log.clear': '清空',
    'log.empty': '暂无操作记录',
    'log.type.undo': '撤销',
    'log.type.redo': '重做',
    'log.type.update': '修改',
    'log.type.add': '添加',
    'log.type.delete': '删除',
    'log.type.batch': '批量',
    'log.type.info': '信息',
  },
  en: {
    // TopBar
    'topbar.new': 'New',
    'topbar.history': 'History',
    'topbar.import': 'Import',
    'topbar.export': 'Export',
    'topbar.save': 'Save',
    'topbar.undo': 'Undo',
    'topbar.redo': 'Redo',
    'topbar.log': 'Operation Log',
    'topbar.connected': 'Connected',
    'topbar.offline': 'Offline',
    'topbar.newConfirmTitle': 'Create New Session?',
    'topbar.newConfirmDesc': 'Current session will be saved to history. You can recover it later from History.',
    'topbar.newConfirmCancel': 'Cancel',
    'topbar.newConfirmCreate': 'Create New',
    'topbar.newNamePlaceholder': 'Enter session name...',

    // StatusBar
    'status.message': 'message',
    'status.messages': 'messages',
    'status.signal': 'signal',
    'status.signals': 'signals',
    'status.modified': 'Modified',

    // MessageList
    'msglist.title': 'Messages',
    'msglist.addTooltip': 'Add message',
    'msglist.empty': 'No messages yet.<br>Click + to add one.',
    'msglist.unnamed': '(unnamed)',

    // SignalTable
    'signal.selectMessage': 'Select a message from the sidebar to view its signals.',
    'signal.empty': 'No signals defined.<br>Click + Signal to add one.',
    'signal.add': '+ Signal',
    'signal.batch': 'Batch +',
    'signal.deleteMsg': 'Delete Msg',
    'signal.thIdx': '#',
    'signal.thName': 'Name',
    'signal.thStart': 'Start',
    'signal.thLen': 'Len',
    'signal.thOrder': 'Order',
    'signal.thFactor': 'Factor',
    'signal.thOffset': 'Offset',
    'signal.thMin': 'Min',
    'signal.thMax': 'Max',
    'signal.thUnit': 'Unit',
    'signal.thComment': 'Comment',

    // MessagePanel
    'panel.empty': 'No message selected.<br>Click a message to edit its properties.',
    'panel.properties': 'Message Properties',
    'panel.signalProperties': 'Signal Properties',
    'panel.id': 'ID (hex)',
    'panel.name': 'Name',
    'panel.signalName': 'Name',
    'panel.dlc': 'DLC',
    'panel.cycle': 'Cycle (ms)',
    'panel.sender': 'Sender',
    'panel.comment': 'Comment',
    'panel.signalComment': 'Comment',
    'panel.signalStart': 'Start Bit',
    'panel.signalLength': 'Length',
    'panel.signalByteOrder': 'Byte Order',
    'panel.signalFactor': 'Factor',
    'panel.signalOffset': 'Offset',
    'panel.signalMin': 'Min Value',
    'panel.signalMax': 'Max Value',
    'panel.signalUnit': 'Unit',
    'panel.intel': 'Little Endian (Intel)',
    'panel.motorola': 'Big Endian (Motorola)',
    'panel.actions': 'Actions',
    'panel.signalActions': 'Signal Actions',
    'panel.duplicate': 'Duplicate Message',
    'panel.copySignal': 'Copy Signal',
    'panel.deleteSignal': 'Delete Signal',

    // BatchModal
    'batch.title': 'Batch Add Signals',
    'batch.nameTemplate': 'Name template (use {n} for number)',
    'batch.nameHint': 'Use {n} for 1,2,3 or {n:02d} for 01,02,03',
    'batch.count': 'Count',
    'batch.startNum': 'Start number',
    'batch.startBit': 'Start bit',
    'batch.bitStep': 'Bit step',
    'batch.length': 'Length',
    'batch.byteOrder': 'Byte order',
    'batch.intel': 'intel',
    'batch.motorola': 'motorola',
    'batch.factor': 'Factor',
    'batch.offset': 'Offset',
    'batch.min': 'Min',
    'batch.max': 'Max',
    'batch.unit': 'Unit',
    'batch.commentTemplate': 'Comment template (optional, use {n})',
    'batch.commentHint': 'Example: ADC channel {n} raw value',
    'batch.cancel': 'Cancel',
    'batch.create': 'Create',

    // HistoryModal
    'history.title': 'Session History',
    'history.empty': 'No history sessions found.',
    'history.delete': 'Delete',
    'history.deleteConfirm': 'Delete this session permanently?',

    // ContextMenu
    'ctx.copySignal': 'Copy Signal',
    'ctx.cutSignal': 'Cut Signal',
    'ctx.pasteSignal': 'Paste Signal',
    'ctx.deleteSignal': 'Delete Signal',
    'ctx.copyMessage': 'Copy Message',
    'ctx.pasteMessage': 'Paste Message',
    'ctx.duplicateMessage': 'Duplicate Message',
    'ctx.deleteMessage': 'Delete Message',

    // Toast messages
    'toast.messageAdded': 'Message added',
    'toast.messageDeleted': 'Message deleted',
    'toast.signalAdded': 'Signal added',
    'toast.signalDeleted': 'Signal deleted',
    'toast.renamed': 'Renamed',
    'toast.sessionLoaded': 'Session loaded',
    'toast.sessionDeleted': 'Session deleted',
    'toast.newSessionCreated': 'New session created',
    'toast.signalCopied': 'Signal copied',
    'toast.signalCut': 'Signal cut',
    'toast.signalPasted': 'Signal pasted',
    'toast.messageCopied': 'Message copied',
    'toast.messagePasted': 'Message pasted',
    'toast.messageDuplicated': 'Message duplicated',
    'toast.undoSuccess': 'Undone',
    'toast.undoEmpty': 'Nothing to undo',
    'toast.restored': 'Restored: {name}',
    'toast.serverOffline': 'Start API server to begin',
    'toast.batchCreated': 'Created {count} signals',
    'toast.batchFailed': 'Batch create failed at #{idx}: {msg}',
    'toast.signalOutOfBounds': 'Signal "{name}" out of bounds (DLC={dlc}, max bit {max})',
    'toast.signalOverlap': 'Signal "{name}" overlaps with "{other}" at bits {bits}',
    'toast.signalAutoFixed': 'Auto-adjusted "{name}" start bit to {start}',
    // Signal validation errors
    'signal.errorsTitle': 'Signal Layout Errors',
    'signal.errorOutOfBounds': '{name}: out of bounds (bits {bits} > {max})',
    'signal.errorOverlap': '{name} vs {other}: overlap at bits {bits}',
    'signal.fixBtn': 'Auto Fix',
    'signal.noErrors': 'No layout errors',

    // Layout view
    'layout.backToTable': 'Back to Table',
    'layout.viewLayout': 'Layout View',
    'layout.noSignals': 'No signals defined.',
    'layout.byteLabel': 'Byte',
    'layout.bitHeader': 'Bit',

    // Log Panel
    'log.title': 'Operation Log',
    'log.clear': 'Clear',
    'log.empty': 'No operations yet',
    'log.type.undo': 'UNDO',
    'log.type.redo': 'REDO',
    'log.type.update': 'Update',
    'log.type.add': 'Add',
    'log.type.delete': 'Delete',
    'log.type.batch': 'Batch',
    'log.type.info': 'Info',
  }
}

let currentLocale = localStorage.getItem('canmatrix_locale') || 'zh'

export function t(key, vars = {}) {
  let text = dict[currentLocale]?.[key] || key
  for (const [k, v] of Object.entries(vars)) {
    text = text.replace(new RegExp(`\\{${k}\\}`, 'g'), v)
  }
  return text
}

export function setLocale(locale) {
  currentLocale = locale
  localStorage.setItem('canmatrix_locale', locale)
}

export function getLocale() {
  return currentLocale
}

export function toggleLocale() {
  const next = currentLocale === 'zh' ? 'en' : 'zh'
  setLocale(next)
  return next
}
