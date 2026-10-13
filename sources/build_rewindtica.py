#!/usr/bin/env python3
"""Build Rewindtica v0.1 from the user's Unbounded Google Fonts ZIP.

Rewindtica is a modified version of Unbounded, licensed under SIL OFL 1.1.
The original font binaries are NOT bundled with this builder.

Dependencies: fonttools. Optional for specimen: pillow.
"""
from __future__ import annotations
import argparse
import io
import math
import re
import zipfile
from pathlib import Path
from fontTools.ttLib import TTFont
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib.tables.ttProgram import Program

FAMILY = 'Rewindtica'
VERSION = '0.1.0'
# Optical compression is deliberately weight-dependent: the sturdy display
# weight is compact while the light weight keeps open counters and spacing.
WEIGHTS = {
    'Light':  {'weight': 300, 'xscale': 0.925},
    'Medium': {'weight': 500, 'xscale': 0.895},
    'Bold':   {'weight': 700, 'xscale': 0.870},
}
# Signature logo / interface letters receive additional width shaping.
# This is not a font rename: every outline is modified; these letters have
# individual adjustments, and the i/j accents are redesigned.
SIGNS = {
    'R': 0.97, 'e': 0.975, 'w': 0.930,
    'i': 0.99, 'n': 0.98, 'd': 0.970, 'a': 0.98,
    'uni0421': 0.96,  # С
    'uni0441': 0.97,  # с
    'uni0445': 0.965, # х
    'uni0440': 0.985, # р
    'uni0430': 0.98,  # а
    'uni043D': 0.975, # н
    'uni0438': 0.97,  # и
    'uni0442': 0.965, # т
    'uni044C': 0.975, # ь
}


def r(n):
    return int(round(n))


def transform_outline(g, sx: float, glyph_table) -> None:
    if g.isComposite():
        for component in g.components:
            if hasattr(component, 'x'):
                component.x = r(component.x * sx)
    elif g.numberOfContours > 0:
        g.coordinates.toInt()
        g.coordinates = type(g.coordinates)([(r(x * sx), y) for (x, y) in g.coordinates])
    if not g.isComposite() and g.numberOfContours > 0:
        # Source hints no longer fit modified contours. Install an empty
        # instruction program; TrueType compiler expects the field to exist.
        p = Program(); p.fromBytecode(b''); g.program = p


def make_squircle_dot(xmin: int, ymin: int, xmax: int, ymax: int):
    """Original contour: compact, deliberately squarish dot, soft corners."""
    pen = TTGlyphPen(None)
    width = xmax-xmin
    height = ymax-ymin
    rad = r(min(width,height) * 0.17)
    # Quadratic rounded rectangle, in clockwise outline direction.
    pen.moveTo((xmin+rad, ymin))
    pen.lineTo((xmax-rad, ymin))
    pen.qCurveTo((xmax, ymin), (xmax, ymin+rad))
    pen.lineTo((xmax, ymax-rad))
    pen.qCurveTo((xmax, ymax), (xmax-rad, ymax))
    pen.lineTo((xmin+rad, ymax))
    pen.qCurveTo((xmin, ymax), (xmin, ymax-rad))
    pen.lineTo((xmin, ymin+rad))
    pen.qCurveTo((xmin, ymin), (xmin+rad, ymin))
    pen.closePath()
    glyph = pen.glyph()
    p = Program(); p.fromBytecode(b''); glyph.program = p
    return glyph


def scale_gpos(obj, factor: float, seen: set[int]):
    """Scale x-position fields in GPOS (including extension lookups).

    Preserves source feature topology; vertical anchor coordinates stay fixed.
    Traversal is structural and uses a visited set to avoid duplicate edits.
    """
    if obj is None or isinstance(obj,(int,float,str,bytes,tuple)):
        if isinstance(obj,tuple):
            for value in obj:
                scale_gpos(value, factor, seen)
        return
    if isinstance(obj,list):
        for value in obj:
            scale_gpos(value, factor, seen)
        return
    obj_id = id(obj)
    if obj_id in seen:
        return
    seen.add(obj_id)
    if not hasattr(obj,'__dict__'):
        return
    # OpenType ValueRecords and Anchor formats store x measurements.
    for field in ('XPlacement','XAdvance','XCoordinate','BaseCoordX','LigatureCaretByPos'):
        val = getattr(obj, field, None)
        if isinstance(val,int):
            setattr(obj,field,r(val*factor))
    for field,val in vars(obj).items():
        if field.startswith('_') or field in ('XPlacement','XAdvance','XCoordinate','BaseCoordX','LigatureCaretByPos'):
            continue
        if isinstance(val,(list,tuple)) or hasattr(val,'__dict__'):
            scale_gpos(val,factor,seen)


def set_names(font: TTFont, style: str):
    full = f'{FAMILY} {style}'
    family = FAMILY
    ps = f'{FAMILY}-{style}'
    table = font['name']
    desc = 'Rewindtica — a modified typeface derived from Unbounded, by the Unbounded Project Authors.'
    names = {
        0: 'Copyright 2022 The Unbounded Project Authors. Rewindtica modifications 2026 by enddless8. SIL OFL 1.1.',
        1: family,
        2: style,
        3: f'Rewindtica-{VERSION}-{style}',
        4: full,
        5: f'Version {VERSION}',
        6: ps,
        13: 'This modified font is licensed under the SIL Open Font License, Version 1.1. Copyright 2022 The Unbounded Project Authors. Modifications 2026 enddless8.',
        14: 'https://openfontlicense.org/',
        16: family,
        17: style,
        19: desc,
    }
    # Remove stale names including language-specific names of old family.
    table.names = []
    for name_id, text in names.items():
        table.setName(text,name_id,3,1,0x409)
        table.setName(text,name_id,1,0,0)
    font['OS/2'].usWeightClass = WEIGHTS[style]['weight']
    font['OS/2'].achVendID = 'RWND'
    # fsSelection Regular only for 400. Bold bit for 700. WWS family avoids
    # ghost styles in Font Book and Adobe applications.
    font['OS/2'].fsSelection &= ~(0x01 | 0x20 | 0x40)
    if style == 'Bold': font['OS/2'].fsSelection |= 0x20
    if style == 'Medium': font['OS/2'].fsSelection |= 0x40
    if font['head'].macStyle is not None:
        font['head'].macStyle &= ~0x3
        if style == 'Bold': font['head'].macStyle |= 1
    if 'STAT' in font:
        # Static base STAT AxisValue names still refer to old family axes.
        # Remove stale STAT; Bold/Medium/Light use legacy + typographic names.
        del font['STAT']


def build(src_zip:zipfile.ZipFile, dest:Path, style:str) -> Path:
    source_name = f'static/Unbounded-{style}.ttf'
    raw=src_zip.read(source_name)
    font=TTFont(io.BytesIO(raw),recalcBBoxes=True, recalcTimestamp=False)
    sx=WEIGHTS[style]['xscale']
    glyph_table=font['glyf']
    hmtx=font['hmtx'].metrics
    widths_before={g: hmtx[g][0] for g in hmtx}
    # Horizontal proportion corrections per glyph. Keep all glyphs present,
    # including composite accented Cyrillic and Latin.
    for name in font.getGlyphOrder():
        glyph=glyph_table[name]
        local=sx * SIGNS.get(name,1.0)
        transform_outline(glyph, local, glyph_table)
        aw,lsb=hmtx[name]
        hmtx[name]=(max(1,r(aw*local)),r(lsb*local))
    # New squared off, softened i/j accents. This replaces only a shared
    # combining dot drawing, while retaining Unbounded's built-in composites.
    if 'uni0307' in glyph_table:
        dot=glyph_table['uni0307']
        dot.recalcBounds(glyph_table)
        bbox=(dot.xMin,dot.yMin,dot.xMax,dot.yMax)
        glyph_table['uni0307']=make_squircle_dot(*bbox)
    # Wordmark R: a more compact diagonal sweep than the stock broad tail.
    if style in ('Bold','Medium'):
        g=glyph_table['R']
        if (not g.isComposite()) and g.numberOfContours >= 2:
            start=g.endPtsOfContours[0]+1
            end=g.endPtsOfContours[1]+1
            # Lower right terminal of the leg; reshape only the leg contour.
            for idx in range(start,end):
                x,y=g.coordinates[idx]
                if y<40 and x>r(720*sx):
                    g.coordinates[idx]=(r(x - 38*sx),y)
    # Remove outdated source TrueType instructions, since outlines changed.
    for tag in ('fpgm','prep','cvt '):
        if tag in font: del font[tag]
    if 'maxp' in font:
        font['maxp'].maxSizeOfInstructions=0
    if 'GPOS' in font:
        scale_gpos(font['GPOS'].table,sx,set())
    if 'OS/2' in font:
        font['OS/2'].xAvgCharWidth=r(font['OS/2'].xAvgCharWidth*sx)
    set_names(font,style)
    for glyph_name in font.getGlyphOrder():
        glyph_table[glyph_name].recalcBounds(glyph_table)
    filename=f'{FAMILY}-{style}.ttf'
    out=dest/filename
    font.save(out)
    # Validate that real parser can load emitted result and critical glyphs.
    check=TTFont(out)
    for codepoint in map(ord,'RewindСохранитьНачатьзаписьБыстрыйклип0123456789'):
        if codepoint not in check.getBestCmap():
            raise RuntimeError(f'{filename}: missing U+{codepoint:04X}')
    if check['OS/2'].usWeightClass!=WEIGHTS[style]['weight']:
        raise RuntimeError('wrong weight')
    return out


def render_sample(dest:Path):
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print('Pillow not installed; skipping PNG preview. pip install pillow')
        return
    W,H=1660,1310
    bg=(17,18,21); accent=(116,243,42)
    im=Image.new('RGB',(W,H),bg)
    d=ImageDraw.Draw(im)
    try:
        ui=ImageFont.truetype(str(dest/'Rewindtica-Medium.ttf'),23)
        small=ImageFont.truetype(str(dest/'Rewindtica-Light.ttf'),18)
    except OSError:
        return
    d.text((72,45),'REWINDTICA / PROTOTYPE 01',font=ui,fill=(185,187,192))
    d.line([(72,100),(1590,100)],fill=(77,80,84),width=2)
    for i,style in enumerate(['Bold','Medium','Light']):
        y=140+i*348
        d.text((75,y),style.upper(),font=ui,fill=accent)
        font=ImageFont.truetype(str(dest/f'Rewindtica-{style}.ttf'),122)
        label=ImageFont.truetype(str(dest/f'Rewindtica-{style}.ttf'),40)
        d.text((65,y+30),'Rewind',font=font,fill=(248,249,250))
        word_width=d.textlength('Rewind',font=font)
        xdot=min(1550,70+word_width+20)
        d.ellipse((xdot,y+127,xdot+22,y+149),fill=accent)
        d.text((75,y+195),'Сохранить Rewind',font=label,fill=(246,246,246))
        d.text((75,y+250),'Начать запись   30 сек',font=label,fill=(191,194,198))
        if i<2: d.line([(72,y+316),(1590,y+316)],fill=(57,60,66),width=1)
    d.text((75,1210),'Aa Bb Rr Ee Ww    Аа Бб Жж Йй Яя',font=ImageFont.truetype(str(dest/'Rewindtica-Medium.ttf'),45),fill=(246,246,246))
    d.text((75,1274),'Modified from Unbounded · SIL Open Font License 1.1 · rendering from actual generated TTFs',font=small,fill=(140,142,148))
    im.save(dest/'Rewindtica-Real-TTF-Specimen.png')


def main():
    ap=argparse.ArgumentParser(description='Build Rewindtica derivative fonts from Unbounded.zip')
    ap.add_argument('unbounded_zip',help='Path to official Unbounded.zip')
    ap.add_argument('--output',default='./Rewindtica-build',help='Output directory for generated TTFs')
    args=ap.parse_args()
    dest=Path(args.output)
    dest.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(args.unbounded_zip) as z:
        license=z.read('OFL.txt')
        if b'SIL OPEN FONT LICENSE' not in license:
            raise SystemExit('Expected Unbounded SIL OFL 1.1, not found')
        (dest/'OFL.txt').write_bytes(license)
        for style in WEIGHTS:
            out=build(z,dest,style)
            print('Built:',out)
    render_sample(dest)
    print('Ready! Install the three TTFs in Font Book, then restart Figma.')

if __name__=='__main__':main()
