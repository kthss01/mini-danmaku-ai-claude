#!/usr/bin/env python3
"""콘셉트 시트(전신 + 초상 + 전투 패널 합성 이미지)에서 임시 게임 자산을 뽑아낸다.

  python scripts/theme/sheet_extract.py <sheet> --name cirno --fork game/taisei --bg-name minivelobg
  python scripts/theme/sheet_extract.py <sheet> --name wriggle --fork game/taisei --sprites wriggle,wriggleex --no-bg
  python scripts/theme/sheet_extract.py <sheet> --name iku --fork game/taisei --sprites iku --single iku_mid --no-bg

출력(fork 안):
  atlas/common/boss/<sprite>.frameNNNN.png   전투 스프라이트. 프레임 수는 gfx/boss/<sprite>.ani의 @sprite_count를 따른다
  atlas/common/boss/<single>.png             단일 프레임 스프라이트(예: iku_mid)
  atlas/portraits/dialog/<name>.webp         기본 초상화 640×1000. 표정 패치는 atlas/config/dialog/<name>_face_*.spr에 있는
                                             표정 전부, 변형은 기존 <name>_variant_*.webp 전부를 같은 그림으로 만든다(임시)
  resources/00-taisei.pkgdir/gfx/stage1/<bg-name>.webp   (--bg-name) 전투 패널로 만든 스펠 배경 타일 1024×1024
또한 기존 <name>*.alphamap.webp를 지운다(새 그림에 옛 알파맵이 적용되지 않도록).

배경 제거는 rembg(isnet-anime, 없으면 u2net)를 쓴다. 품질은 임시용이다: pip install "rembg[cpu]" scipy Pillow numpy
"""

import argparse
import math
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

HERE = Path(__file__).resolve().parent


def log(*a):
    print(*a, flush=True)


def find_gutters(img, axis, lo, hi, min_run=4):
    """밝은(거의 흰색) 선이 연속으로 min_run px 이상 이어지는 위치를 찾는다. axis=0: 세로선(x), 1: 가로선(y)."""
    arr = np.asarray(img.convert('RGB')).astype(np.int16)
    bright = (arr.min(axis=2) >= 225)
    frac = bright[lo:hi, :].mean(axis=0) if axis == 0 else bright[:, lo:hi].mean(axis=1)
    lines = np.where(frac > 0.9)[0]
    runs, start = [], None
    for i, v in enumerate(lines):
        if start is None:
            start = v
        if i + 1 == len(lines) or lines[i + 1] != v + 1:
            if v - start + 1 >= min_run:
                runs.append((start, v))
            start = None
    return runs


def detect_panels(sheet, args):
    w, h = sheet.size
    if args.gutter_x:
        gx = args.gutter_x
    else:
        runs = [r for r in find_gutters(sheet, 0, int(h * 0.2), int(h * 0.8)) if w * 0.45 < r[0] < w * 0.75]
        gx = runs[0][0] if runs else int(w * 0.59)
    if args.gutter_y:
        gy = args.gutter_y
    else:
        runs = [r for r in find_gutters(sheet, 1, gx + 10, w - 10) if h * 0.3 < r[0] < h * 0.7]
        gy = runs[0][0] if runs else int(h * 0.5)
    log(f'패널 경계: 세로 x={gx}, 가로 y={gy} (시트 {w}x{h})')
    return (0, 0, gx, h), (gx, 0, w, gy), (gx, gy, w, h)


def remove_background(img):
    from rembg import new_session, remove
    for model in ('isnet-anime', 'u2net'):
        try:
            session = new_session(model)
            log(f'배경 제거 모델: {model}')
            return remove(img, session=session, alpha_matting=False)
        except Exception as e:  # 모델 다운로드 실패 등
            log(f'{model} 실패: {e}')
    raise SystemExit('rembg 모델을 쓸 수 없다')


def keep_largest_component(rgba, min_alpha=40):
    """알파가 있는 영역 중 가장 큰 연결 성분만 남긴다(옆에 붙은 자전거·소품 제거)."""
    try:
        from scipy import ndimage
    except ImportError:
        log('scipy 없음: 연결 성분 정리 생략')
        return rgba
    a = np.asarray(rgba)[:, :, 3]
    mask = a > min_alpha
    labels, n = ndimage.label(mask)
    if n <= 1:
        return rgba
    sizes = ndimage.sum(mask, labels, range(1, n + 1))
    keep = labels == (int(np.argmax(sizes)) + 1)
    keep = ndimage.binary_dilation(keep, iterations=6)  # 경계 6px은 남겨 부드러운 가장자리 보존
    arr = np.array(rgba)
    arr[:, :, 3] = np.where(keep, arr[:, :, 3], 0)
    log(f'연결 성분 {n}개 중 가장 큰 것만 유지')
    return Image.fromarray(arr, 'RGBA')


def fit_into(cutout, canvas_h, top_margin, bottom_margin, max_w):
    """컷아웃을 캔버스 높이에 맞춘다. 폭이 넘치면 폭 기준."""
    fig = cutout.crop(cutout.getbbox())
    fw, fh = fig.size
    scale = (canvas_h - top_margin - bottom_margin) / fh
    if fw * scale > max_w:
        scale = max_w / fw
    return fig.resize((max(1, round(fw * scale)), max(1, round(fh * scale))), Image.LANCZOS)


def make_portrait(cutout, out_path):
    W, H = 640, 1000
    fig = fit_into(cutout, H, 40, 0, W - 40)
    canvas = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    x = (W - fig.width) // 2
    canvas.alpha_composite(fig, (x, 40))
    canvas.save(out_path, 'PNG')
    # 얼굴 영역 추정: 머리 위에서 그림 높이의 3~22%, 가로는 중심 ±17%
    fx0, fx1 = int(x + fig.width * 0.33), int(x + fig.width * 0.67)
    fy0, fy1 = int(40 + fig.height * 0.03), int(40 + fig.height * 0.22)
    log(f'초상화 {W}x{H}, 그림 {fig.width}x{fig.height}, 얼굴 영역 추정 {fx0},{fy0} {fx1 - fx0}x{fy1 - fy0}')
    return (fx0, fy0, fx1 - fx0, fy1 - fy0)


def frame_image(fig, i, W, H):
    """i번 프레임: 0~5 대기(호흡), 6~11 공격(기울기·확대), 12~17 차지(확대 펄스). 모두 발끝 고정."""
    t = (i % 6) / 6.0
    canvas = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    dy = 0
    if i < 6:
        dy = round(2 * math.sin(2 * math.pi * t))
        frame = fig.resize((fig.width, max(1, round(fig.height * (1 + 0.01 * math.sin(2 * math.pi * t))))), Image.LANCZOS)
    elif i < 12:
        angle = 4 * math.sin(2 * math.pi * t)
        s = 1 + 0.03 * (0.5 + 0.5 * math.sin(2 * math.pi * t))
        frame = fig.resize((max(1, round(fig.width * s)), max(1, round(fig.height * s))), Image.LANCZOS)
        frame = frame.rotate(angle, resample=Image.BICUBIC, expand=True, center=(frame.width / 2, frame.height))
    else:
        s = 1 + 0.06 * (0.5 + 0.5 * math.sin(2 * math.pi * t))
        frame = fig.resize((max(1, round(fig.width * s)), max(1, round(fig.height * s))), Image.LANCZOS)
    x = (W - frame.width) // 2
    y = H - 12 - frame.height - dy
    canvas.alpha_composite(frame, (x, max(0, y)))
    return canvas


def sprite_count(fork, sprite):
    ani = fork / 'resources/00-taisei.pkgdir/gfx/boss' / f'{sprite}.ani'
    m = re.search(r'@sprite_count\s*=\s*(\d+)', ani.read_text(encoding='utf-8', errors='replace'))
    if not m:
        raise SystemExit(f'{ani}에서 @sprite_count를 찾지 못했다')
    return int(m.group(1))


def make_sprites(cutout, fork, sprite, count):
    W, H = 160, 240
    fig = fit_into(cutout, H, 12, 12, 150)
    out_dir = fork / 'atlas/common/boss'
    for old in out_dir.glob(f'{sprite}.frame*.png'):
        old.unlink()
    for i in range(count):
        frame_image(fig, i, W, H).save(out_dir / f'{sprite}.frame{i:04d}.png', optimize=True)
    log(f'전투 스프라이트 {sprite}: {count}장 ({W}x{H}, 그림 높이 {fig.height})')


def make_single(cutout, fork, sprite):
    W, H = 160, 240
    fig = fit_into(cutout, H, 12, 12, 150)
    frame_image(fig, 0, W, H).save(fork / 'atlas/common/boss' / f'{sprite}.png', optimize=True)
    log(f'단일 스프라이트 {sprite}.png ({W}x{H})')


def make_bg_tile(panel, out_path):
    w, h = panel.size
    # 캐릭터가 있는 가운데를 피해 왼쪽 위 영역으로 타일을 만든다
    tile = panel.convert('RGB').crop((0, 0, int(w * 0.5), int(h * 0.75))).resize((1024, 1024), Image.LANCZOS)
    mean = tuple(int(v) for v in np.asarray(tile).reshape(-1, 3).mean(axis=0))
    tile = Image.blend(tile, Image.new('RGB', tile.size, mean), 0.35).filter(ImageFilter.GaussianBlur(1.2))
    tile.save(out_path, 'WEBP', quality=88, method=6)
    log(f'스펠 배경 타일 1024x1024 저장 (평균색 {mean})')


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('sheet')
    ap.add_argument('--name', required=True, help='초상화 캐릭터 id (atlas/portraits/dialog/<name>)')
    ap.add_argument('--fork', required=True, help='fork 경로 (game/taisei)')
    ap.add_argument('--sprites', help='전투 스프라이트 id들(쉼표). 기본 --name. 프레임 수는 각 .ani의 @sprite_count')
    ap.add_argument('--single', action='append', default=[], help='단일 프레임 스프라이트 id (예: iku_mid)')
    ap.add_argument('--faces', help='표정 이름들(쉼표). 기본: atlas/config/dialog/<name>_face_*.spr 전부')
    ap.add_argument('--variants', help='변형 이름들(쉼표). 기본: 기존 <name>_variant_*.webp 전부')
    ap.add_argument('--bg-name', help='스펠 배경 타일 이름 (gfx/stage1/<bg-name>.webp)')
    ap.add_argument('--no-bg', action='store_true', help='배경 타일을 만들지 않는다')
    ap.add_argument('--gutter-x', type=int)
    ap.add_argument('--gutter-y', type=int)
    ap.add_argument('--char-box', help='전신 패널 안에서 캐릭터만 담은 상자 비율 x0,y0,x1,y1 (0~1)')
    ap.add_argument('--rembg-full', action='store_true', help='배경 제거는 전체 패널로 하고 나서 --char-box로 자른다')
    ap.add_argument('--work', default='build/theme-extract', help='중간 결과 저장 폴더')
    args = ap.parse_args()

    sheet = Image.open(args.sheet).convert('RGBA')
    fork = Path(args.fork)
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)
    portraits = fork / 'atlas/portraits/dialog'
    configs = fork / 'atlas/config/dialog'

    full_box, _face_box, battle_box = detect_panels(sheet, args)
    full = sheet.crop(full_box)
    char_box = None
    if args.char_box:
        fx0, fy0, fx1, fy1 = (float(v) for v in args.char_box.split(','))
        char_box = (int(full.width * fx0), int(full.height * fy0), int(full.width * fx1), int(full.height * fy1))
    if char_box and not args.rembg_full:
        full = full.crop(char_box)
        char_box = None
    full.save(work / f'{args.name}_panel_full.png')
    sheet.crop(battle_box).save(work / f'{args.name}_panel_battle.png')

    # --rembg-full: 전체 패널로 배경을 제거한 뒤 상자로 자른다(좁은 상자에서 모델이 흐린 마스크를 내는 경우)
    removed = remove_background(full)
    if char_box:
        removed = removed.crop(char_box)
    cutout = keep_largest_component(removed)
    # 모델이 확신이 낮아 알파가 전체적으로 옅게 나오면(세피아 배경 등) 상위 1% 알파가 255가 되도록 늘린다
    arr = np.array(cutout)
    a = arr[:, :, 3]
    body = a[a > 40]
    if body.size and np.percentile(body, 99) < 230:
        gain = 255.0 / max(1.0, float(np.percentile(body, 99)))
        arr[:, :, 3] = np.clip(a.astype(np.float32) * gain, 0, 255).astype(np.uint8)
        cutout = Image.fromarray(arr, 'RGBA')
        log(f'알파 보정 ×{gain:.2f}')
    cutout.save(work / f'{args.name}_cutout.png')
    if cutout.getbbox() is None:
        raise SystemExit('컷아웃이 비어 있다. --char-box나 --gutter-x를 확인한다')

    portrait_png = work / f'{args.name}_portrait.png'
    face_region = make_portrait(cutout, portrait_png)

    faces = args.faces.split(',') if args.faces else sorted(
        p.name[len(args.name) + 6:-4] for p in configs.glob(f'{args.name}_face_*.spr'))
    variants = args.variants.split(',') if args.variants else sorted(
        p.name[len(args.name) + 9:-5] for p in portraits.glob(f'{args.name}_variant_*.webp') if '.alphamap' not in p.name)
    log(f'표정 {faces} / 변형 {variants}')

    for p in portraits.glob(f'{args.name}*.alphamap.*'):
        p.unlink()
        log(f'삭제: {p.name}')

    cmd = [sys.executable, str(HERE / 'theme_assets.py'), 'make-faces', '--base', str(portrait_png),
           '--name', args.name, '--out-dir', str(portraits), '--config-dir', str(configs),
           '--region', ','.join(str(v) for v in face_region)]
    for f in faces:
        cmd += ['--face', f'{f}={portrait_png}']
    for v in variants:
        cmd += ['--variant', f'{v}={portrait_png}']
    subprocess.run(cmd, check=True)

    for sprite in (args.sprites.split(',') if args.sprites else [args.name]):
        make_sprites(cutout, fork, sprite, sprite_count(fork, sprite))
    for single in args.single:
        make_single(cutout, fork, single)

    if args.bg_name and not args.no_bg:
        make_bg_tile(sheet.crop(battle_box), fork / 'resources/00-taisei.pkgdir/gfx/stage1' / f'{args.bg_name}.webp')
    log('완료. 다음: gen-atlas.py로 common·portraits 재생성 후 빌드')


if __name__ == '__main__':
    main()
