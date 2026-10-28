"""The demo yard as xLights show files (0.24.36): xlights_rgbeffects.xml (its props and the
Arches group) and xlights_networks.xml (one generic Ethernet controller, DDP), so the demo can
be used like a real show - 'layout' ingests it, xLights can open it, 'bundle' packs it.

Written from demo/layout.py; the props come back from 'layout' with the same shapes and sizes
in lights (xLights' own units for positions: about 100 per metre)."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from .layout import demo_layout

CONTROLLER = "Demo-Controller"
U = 100.0                                              # xLights units per metre (positions only)


def _models(lay: dict) -> list[tuple[dict, int]]:
    """(xLights model attributes, channels) for each demo prop."""
    out = []
    for p in lay["props"]:
        t, pr = p["shape"]["type"], p["shape"]["params"]
        x, y, z = (v * U for v in p["transform"]["position"])
        a = {"name": p["id"], "parm3": "1", "WorldPosX": f"{x:g}", "WorldPosY": f"{y:g}", "WorldPosZ": f"{z:g}",
             "StringType": "RGB Nodes", "LayoutGroup": "Default"}
        if t == "polyline":
            pts = pr["points"]
            a.update(DisplayAs="Poly Line", parm1="1", parm2=str(pr["nodes"]),
                     PointData=",".join(f"{px * U:g},{py * U:g},0" for px, py in pts))
            n = pr["nodes"]
        elif t == "arc":
            a.update(DisplayAs="Arches", parm1="1", parm2=str(pr["nodes"]), ScaleX=f"{pr['width'] * U:g}",
                     ScaleY=f"{pr['height'] * U:g}")
            n = pr["nodes"]
        elif t == "cone":
            a.update(DisplayAs="Tree 360", parm1=str(pr["strings"]), parm2=str(pr["nodes_per_string"]),
                     ScaleX=f"{pr['base_diameter'] * U:g}", ScaleY=f"{pr['height'] * U:g}")
            n = pr["strings"] * pr["nodes_per_string"]
        elif t == "grid":
            a.update(DisplayAs="Horiz Matrix", parm1=str(pr["rows"]), parm2=str(pr["columns"]),
                     ScaleX=f"{pr['width'] * U:g}", ScaleY=f"{pr['height'] * U:g}")
            n = pr["rows"] * pr["columns"]
        elif t == "radial":
            a.update(DisplayAs="Spinner", parm1=str(pr["arms"]), parm2=str(pr["nodes_per_arm"]),
                     Hollow=f"{round(pr.get('hollow', 0.1) * 100):g}", ScaleX=f"{pr['diameter'] * U:g}",
                     ScaleY=f"{pr['diameter'] * U:g}")
            n = pr["arms"] * pr["nodes_per_arm"]
        elif t == "ring":
            a.update(DisplayAs="Wreath", parm1="1", parm2=str(pr["nodes"]), ScaleX=f"{pr['diameter'] * U:g}",
                     ScaleY=f"{pr['diameter'] * U:g}")
            n = pr["nodes"]
        elif t == "star":
            a.update(DisplayAs="Star", parm1="1", parm2=str(pr["nodes"]), parm3=str(pr.get("points", 5)),
                     ScaleX=f"{pr['diameter'] * U:g}", ScaleY=f"{pr['diameter'] * U:g}")
            n = pr["nodes"]
        else:                                          # the moving head: a DMX fixture (not sequenced)
            a.update(DisplayAs="DmxMovingHeadAdv", parm1="1", parm2="1", StringType="Single Color White")
            n = 16
            out.append((a, n))
            continue
        out.append((a, 3 * n))
    return out


def write(folder: Path) -> tuple[Path, Path]:
    """Writes folder/xlights_rgbeffects.xml and folder/xlights_networks.xml; returns their paths."""
    folder.mkdir(parents=True, exist_ok=True)
    lay = demo_layout()
    root = ET.Element("xrgb")
    models = ET.SubElement(root, "models")
    start = 1
    for a, ch in _models(lay):
        ET.SubElement(models, "model", {**a, "Controller": CONTROLLER, "StartChannel": f"!{CONTROLLER}:{start}"})
        start += ch
    groups = ET.SubElement(root, "modelGroups")
    for g in lay.get("groups", []):
        ET.SubElement(groups, "modelGroup", {"name": g["name"], "models": ",".join(g["members"]),
                                             "layout": "Per Model Default" if g.get("render_hint") == "per_prop"
                                             else "minimalGrid", "LayoutGroup": "Default"})
    ET.indent(root)
    rgb = folder / "xlights_rgbeffects.xml"
    ET.ElementTree(root).write(rgb, encoding="UTF-8", xml_declaration=True)
    nets = ET.Element("Networks", {"computer": "demo"})
    c = ET.SubElement(nets, "Controller", {
        "Id": "1", "Name": CONTROLLER, "Description": "seqtool demo: one generic Ethernet controller", "Type": "Ethernet",
        "Vendor": "", "Model": "", "Variant": "", "AutoSize": "1", "ActiveState": "Active", "AutoLayout": "1",
        "AutoUpload": "0", "IP": "192.168.1.100", "Protocol": "DDP"})
    ET.SubElement(c, "network", {"ChannelsPerPacket": "1440", "KeepChannelNumbers": "1", "ComPort": "192.168.1.100",
                                 "BaudRate": "1", "NetworkType": "DDP", "MaxChannels": str(start - 1)})
    ET.indent(nets)
    net = folder / "xlights_networks.xml"
    ET.ElementTree(nets).write(net, encoding="UTF-8", xml_declaration=True)
    return rgb, net
