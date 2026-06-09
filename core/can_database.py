"""纯 IO 序列化工具模块。

本模块不再定义数据类，仅提供 from_toml_str、from_json_str、from_xml_str 等
反序列化辅助函数。所有数据类（Signal、Message、CanDatabase）统一从 models.py 导入。

向后兼容：保留原有的 from_toml_dict、from_json_dict 等方法签名，
但内部委托给 models.CanDatabase 实现。
"""

from __future__ import annotations

from models import CanDatabase, Message, Signal


# ---------------------------------------------------------------------------
# TOML IO
# ---------------------------------------------------------------------------

def from_toml_str(content: str) -> CanDatabase:
    """从 TOML 字符串加载 CanDatabase。"""
    return CanDatabase.from_toml_str(content)


def from_toml_dict(data: dict) -> CanDatabase:
    """从 TOML 字典加载 CanDatabase。"""
    return CanDatabase.from_toml_dict(data)


def to_toml_str(db: CanDatabase) -> str:
    """将 CanDatabase 序列化为 TOML 字符串。"""
    return db.to_toml_str()


def to_toml_dict(db: CanDatabase) -> dict:
    """将 CanDatabase 序列化为 TOML 字典。"""
    return db.to_toml_dict()


# ---------------------------------------------------------------------------
# JSON IO
# ---------------------------------------------------------------------------

def from_json_str(content: str) -> CanDatabase:
    """从 JSON 字符串加载 CanDatabase。"""
    import json
    data = json.loads(content)
    return CanDatabase.from_json_dict(data)


def from_json_dict(data: dict) -> CanDatabase:
    """从 JSON 字典加载 CanDatabase。"""
    return CanDatabase.from_json_dict(data)


def to_json_str(db: CanDatabase) -> str:
    """将 CanDatabase 序列化为 JSON 字符串。"""
    import json
    return json.dumps(db.to_json_dict(), indent=2, ensure_ascii=False)


def to_json_dict(db: CanDatabase) -> dict:
    """将 CanDatabase 序列化为 JSON 字典。"""
    return db.to_json_dict()


# ---------------------------------------------------------------------------
# XML IO
# ---------------------------------------------------------------------------

def from_xml_str(content: str) -> CanDatabase:
    """从 XML 字符串加载 CanDatabase。"""
    import xml.etree.ElementTree as ET
    
    root = ET.fromstring(content)
    data = _xml_to_dict(root)
    return CanDatabase.from_xml_dict(data)


def from_xml_dict(data: dict) -> CanDatabase:
    """从 XML 字典加载 CanDatabase。"""
    return CanDatabase.from_xml_dict(data)


def to_xml_str(db: CanDatabase) -> str:
    """将 CanDatabase 序列化为 XML 字符串。"""
    import xml.etree.ElementTree as ET
    import xml.dom.minidom
    
    root = ET.Element("candatabase")
    name_elem = ET.SubElement(root, "name")
    name_elem.text = db.name
    
    messages_elem = ET.SubElement(root, "messages")
    for msg in sorted(db.messages.values(), key=lambda m: m.id):
        msg_elem = ET.SubElement(messages_elem, "message")
        msg_elem.set("id", f"0x{msg.id:X}")
        msg_elem.set("name", msg.name)
        msg_elem.set("dlc", str(msg.dlc))
        msg_elem.set("cycle_time", str(msg.cycle_time))
        msg_elem.set("sender", msg.sender)
        msg_elem.set("comment", msg.comment)
        
        signals_elem = ET.SubElement(msg_elem, "signals")
        for sig in msg.signals:
            sig_elem = ET.SubElement(signals_elem, "signal")
            sig_elem.set("uuid", sig.uuid)
            sig_elem.set("name", sig.name)
            sig_elem.set("start_bit", str(sig.start_bit))
            sig_elem.set("length", str(sig.length))
            sig_elem.set("byte_order", sig.byte_order)
            sig_elem.set("is_signed", str(sig.is_signed))
            sig_elem.set("factor", str(sig.factor))
            sig_elem.set("offset", str(sig.offset))
            sig_elem.set("min_val", str(sig.min_val))
            sig_elem.set("max_val", str(sig.max_val))
            sig_elem.set("unit", sig.unit)
            sig_elem.set("comment", sig.comment)
            sig_elem.set("multiplexer_mode", sig.multiplexer_mode)
            sig_elem.set("multiplexer_value", str(sig.multiplexer_value))
            if sig.receivers:
                sig_elem.set("receivers", ",".join(sig.receivers))
    
    rough_string = ET.tostring(root, encoding="unicode")
    dom = xml.dom.minidom.parseString(rough_string)
    return dom.toprettyxml(indent="  ", encoding=None)


def to_xml_dict(db: CanDatabase) -> dict:
    """将 CanDatabase 序列化为 XML 字典。"""
    return db.to_xml_dict()


def _xml_to_dict(element: ET.Element) -> dict:
    """将 XML Element 转换为字典（简化版）。"""
    result = {}
    
    for child in element:
        if child.tag == "name":
            result["name"] = child.text
        elif child.tag == "messages":
            messages = []
            for msg_elem in child:
                msg_data = {
                    "id": int(msg_elem.get("id"), 16),
                    "name": msg_elem.get("name", ""),
                    "dlc": int(msg_elem.get("dlc", 8)),
                    "cycle_time": int(msg_elem.get("cycle_time", 0)),
                    "sender": msg_elem.get("sender", ""),
                    "comment": msg_elem.get("comment", ""),
                    "signals": [],
                }
                
                signals_elem = msg_elem.find("signals")
                if signals_elem is not None:
                    for sig_elem in signals_elem:
                        sig_data = {
                            "uuid": sig_elem.get("uuid", ""),
                            "name": sig_elem.get("name", ""),
                            "start_bit": int(sig_elem.get("start_bit", 0)),
                            "length": int(sig_elem.get("length", 8)),
                            "byte_order": sig_elem.get("byte_order", "motorola"),
                            "is_signed": sig_elem.get("is_signed", "False") == "True",
                            "factor": float(sig_elem.get("factor", 1.0)),
                            "offset": float(sig_elem.get("offset", 0.0)),
                            "min_val": float(sig_elem.get("min_val", 0.0)),
                            "max_val": float(sig_elem.get("max_val", 0.0)),
                            "unit": sig_elem.get("unit", ""),
                            "comment": sig_elem.get("comment", ""),
                            "multiplexer_mode": sig_elem.get("multiplexer_mode", "none"),
                            "multiplexer_value": int(sig_elem.get("multiplexer_value", 0)),
                            "receivers": sig_elem.get("receivers", "").split(",") if sig_elem.get("receivers") else [],
                        }
                        msg_data["signals"].append(sig_data)
                
                messages.append(msg_data)
            
            result["messages"] = messages
    
    return {"database": result}


# ---------------------------------------------------------------------------
# DBC IO
# ---------------------------------------------------------------------------

def from_dbc_str(content: str) -> CanDatabase:
    """从 DBC 字符串加载 CanDatabase。"""
    return CanDatabase.from_dbc_str(content)


def to_dbc_str(db: CanDatabase) -> str:
    """将 CanDatabase 序列化为 DBC 字符串。"""
    return db.to_dbc_str()
