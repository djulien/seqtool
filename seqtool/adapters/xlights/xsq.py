"""Minimal .xsq reader (format observed in xLights 2025.x files).

  <xsequence> <head><version>...</version><sequenceTiming>50 ms</sequenceTiming>...
              <ColorPalettes><ColorPalette>C_BUTTON_Palette1=#FFFFFF,...</ColorPalette>
              <EffectDB><Effect>E_SLIDER_x=1,E_CHOICE_y=Left,...</Effect>
              <DisplayElements><Element type="model|timing" name=.../>
              <ElementEffects><Element type name><EffectLayer>
                   <Effect ref="EffectDB index" name="SingleStrand" startTime(ms) endTime palette="index"/>
Settings strings are comma-separated key=value pairs.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path


def norm(name: str | None) -> str:
    """Effect names compared loosely: 'Single Strand' == 'SingleStrand'."""
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def parse_settings(text: str | None) -> dict[str, str]:
    out = {}
    for part in (text or "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v
    return out


@dataclass
class EffectInst:
    element: str
    element_type: str
    layer: int
    name: str
    start: float
    end: float
    settings: dict = field(default_factory=dict)
    palette: dict = field(default_factory=dict)
    label: str = ""
    settings_raw: str = ""                 # the EffectDB / ColorPalette text as it is (0.20.4: borrowing)
    palette_raw: str = ""


@dataclass
class Xsq:
    version: str | None
    timing: str | None
    duration: float | None
    effects: list[EffectInst]
    layers: dict[str, int]                 # element -> number of effect layers in use
    timing_tracks: dict[str, int] = field(default_factory=dict)   # timing track -> number of marks
    sub_layers: list = field(default_factory=list)   # (parent, tag, attrs) of submodel/strand layers with effects
    display_children: dict = field(default_factory=dict)  # DisplayElements model -> [(tag, attrs)]

    def of(self, name: str | None = None, element_type: str = "model") -> list[EffectInst]:
        return [e for e in self.effects if e.element_type == element_type
                and (name is None or norm(e.name) == norm(name))]

    def rightmost(self, name: str | None = None) -> EffectInst | None:
        effs = self.of(name)
        return max(effs, key=lambda e: (e.start, e.end)) if effs else None


def read(path: Path) -> Xsq:
    root = ET.parse(path).getroot()
    head = root.find("head")
    g = (lambda t: (head.findtext(t) or "").strip() or None) if head is not None else (lambda t: None)
    db_raw = [(e.text or "") for e in root.findall("./EffectDB/Effect")]
    pal_raw = [(p.text or "") for p in root.findall("./ColorPalettes/ColorPalette")]
    db = [parse_settings(t) for t in db_raw]
    pals = [parse_settings(t) for t in pal_raw]

    def raw(lst, ix):
        return lst[int(ix)] if ix and ix.isdigit() and int(ix) < len(lst) else ""
    effects, layers = [], {}
    tracks: dict[str, int] = {}
    disp_children: dict[str, list] = {}
    for el in root.findall("./DisplayElements/Element"):
        if el.get("type") == "timing":
            tracks.setdefault(el.get("name", ""), 0)
        kids = [(c.tag, dict(c.attrib)) for c in el]
        if kids:
            disp_children[el.get("name", "")] = kids
    subs: list = []
    for el in root.findall("./ElementEffects/Element"):
        if el.get("type") == "timing":
            tracks[el.get("name", "")] = sum(len(l.findall("Effect")) for l in el.findall("EffectLayer"))
        etype, ename = el.get("type", "model"), el.get("name", "")
        used = 0
        for li, layer in enumerate(el.findall("EffectLayer")):
            effs = layer.findall("Effect")
            used += bool(effs)
            for e in effs:
                ref, pal = e.get("ref"), e.get("palette")
                effects.append(EffectInst(
                    element=ename, element_type=etype, layer=li, name=e.get("name", ""),
                    start=int(e.get("startTime", 0)) / 1000, end=int(e.get("endTime", 0)) / 1000,
                    settings=db[int(ref)] if ref and ref.isdigit() and int(ref) < len(db) else {},
                    palette=pals[int(pal)] if pal and pal.isdigit() and int(pal) < len(pals) else {},
                    label=e.get("label", ""), settings_raw=raw(db_raw, ref), palette_raw=raw(pal_raw, pal)))
        for child in el:                       # submodel / strand rows inside a model element
            if child.tag == "EffectLayer":
                continue
            effs = child.findall("Effect")
            if not effs:
                continue
            sname = child.get("name") or child.get("index") or child.tag
            subs.append((ename, child.tag, dict(child.attrib)))
            for e in effs:
                ref, pal = e.get("ref"), e.get("palette")
                effects.append(EffectInst(
                    element=f"{ename}/{sname}", element_type="submodel", layer=int(child.get("layer", 0) or 0),
                    name=e.get("name", ""),
                    start=int(e.get("startTime", 0)) / 1000, end=int(e.get("endTime", 0)) / 1000,
                    settings=db[int(ref)] if ref and ref.isdigit() and int(ref) < len(db) else {},
                    palette=pals[int(pal)] if pal and pal.isdigit() and int(pal) < len(pals) else {},
                    label=e.get("label", ""), settings_raw=raw(db_raw, ref), palette_raw=raw(pal_raw, pal)))
        if used:
            layers[ename] = used
    try:
        dur = float(g("sequenceDuration")) if g("sequenceDuration") else None
    except ValueError:
        dur = None
    return Xsq(g("version"), g("sequenceTiming"), dur, effects, layers, tracks, subs, disp_children)


def enabled_colors(palette: dict) -> list[str]:
    return [palette.get(f"C_BUTTON_Palette{i}", "").upper() for i in range(1, 9)
            if palette.get(f"C_CHECKBOX_Palette{i}") == "1"]
