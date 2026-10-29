#!/usr/bin/env python3
"""콘셉트 시트(전신 + 초상 + 전투 패널 합성 이미지)에서 임시 게임 자산을 뽑아낸다.

  python scripts/theme/sheet_extract.py <sheet.png> --name cirno --fork game/taisei --bg-name minivelobg

출력(fork 안):
  atlas/common/boss/<name>.frame0000..0011.png   전투 스프라이트 12장(대기 6 + 공격 6, 코드로 변형)
  atlas/portraits/dialog/<name>.webp             기본 초상화 640×1000 (같은 그림을 normal/angry/defeated 패치와 defeated 변형에도 씀)
  atlas/config/dialog/<name>_face_*.spr          표정 패치 위치
  resources/00-taisei.pkgdir/gfx/stage1/<bg-name>.webp   전투 패널로 만든 스펠 배경 타일 1024×1024
또한 기존 <name>.alphamap.webp, <name>_variant_*.alphamap.webp를 지운다(새 그림에 옛 알파맵이 적용되지 않도록).

배경 제거는 rembg(isnet-anime, 없으면 u2net)를 쓴다. 품질은 임시용이다: pip install "rembg[cpu]" scipy Pillow
"""

import argparse
import math
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
    if axis == 0:
        frac = bright[lo:hi, :].mean(axis=0)
    else:
        frac = bright[:, lo:hi].mean(axis=1)
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
    # 가장 큰 성분 주변 6px은 남겨 부드러운 경계를 보존한다
    keep = ndimage.binary_dilation(keep, iterations=6)
    arr = np.array(rgba)
    arr[:, :, 3] = np.where(keep, arr[:, :, 3], 0)
    log(f'연결 성분 {n}개 중 가장 큰 것만 유지')
    return Image.fromarray(arr, 'RGBA')


def fit_into(cutout, canvas_w, canvas_h, top_margin, bottom_margin, max_w):
    """컷아웃을 캔버스에 맞춘다. 높이를 기준으로 맞추되 폭이 넘치면 폭 기준."""
    bb = cutout.getbbox()
    fig = cutout.crop(bb)
    fw, fh = fig.size
    scale = (canvas_h - top_margin - bottom_margin) / fh
    if fw * scale > max_w:
        scale = max_w / fw
    fig = fig.resize((max(1, round(fw * scale)), max(1, round(fh * scale))), Image.LANCZOS)
    return fig


def make_portrait(cutout, out_path):
    W, H = 640, 1000
    fig = fit_into(cutout, W, H, 40, 0, W - 40)
    canvas = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    x = (W - fig.width) // 2
    canvas.alpha_composite(fig, (x, 40))
    canvas.save(out_path, 'WEBP', lossless=True, method=6)
    # 얼굴 영역 추정: 머리 위에서 그림 높이의 3~22%, 가로는 중심 ±17%
    fx0 = int(x + fig.width * 0.33)
    fx1 = int(x + fig.width * 0.67)
    fy0 = int(40 + fig.height * 0.03)
    fy1 = int(40 + fig.height * 0.22)
    log(f'초상화 {W}x{H} 저장, 그림 {fig.width}x{fig.height}, 얼굴 영역 추정 {fx0},{fy0} {fx1 - fx0}x{fy1 - fy0}')
    return (fx0, fy0, fx1 - fx0, fy1 - fy0)


def make_sprites(cutout, out_dir, name):
    W, H = 160, 240
    fig = fit_into(cutout, W, H, 12, 12, 150)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i in range(12):
        t = (i % 6) / 6.0
        canvas = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        if i < 6:
            # 대기: 2px 상하 호흡 + 세로 1% 신축
            dy = round(2 * math.sin(2 * math.pi * t))
            sy = 1 + 0.01 * math.sin(2 * math.pi * t)
            frame = fig.resize((fig.width, max(1, round(fig.height * sy))), Image.LANCZOS)
            angle = 0
        else:
            # 공격: 좌우 4° 기울기 + 3% 확대 펄스
            dy = 0
            angle = 4 * math.sin(2 * math.pi * t)
            s = 1 + 0.03 * (0.5 + 0.5 * math.sin(2 * math.pi * t))
            frame = fig.resize((max(1, round(fig.width * s)), max(1, round(fig.height * s))), Image.LANCZOS)
            frame = frame.rotate(angle, resample=Image.BICUBIC, expand=True, center=(frame.width / 2, frame.height))
        x = (W - frame.width) // 2
        y = H - 12 - frame.height - dy
        canvas.alpha_composite(frame, (x, max(0, y)))
        p = out_dir / f'{name}.frame{i:04d}.png'
        canvas.save(p, optimize=True)
        paths.append(p)
    log(f'전투 스프라이트 12장 저장 ({W}x{H}, 그림 높이 {fig.height})')
    return paths


def make_bg_tile(panel, out_path):
    tile = panel.convert('RGB').resize((1024, 1024), Image.LANCZOS)
    mean = tuple(int(v) for v in np.asarray(tile).reshape(-1, 3).mean(axis=0))
    flat = Image.new('RGB', tile.size, mean)
    tile = Image.blend(tile, flat, 0.35).filter(ImageFilter.GaussianBlur(1.2))
    tile.save(out_path, 'WEBP', quality=88, method=6)
    log(f'스펠 배경 타일 1024x1024 저장 (평균색 {mean})')


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('sheet')
    ap.add_argument('--name', required=True, help='교체할 캐릭터 내부 id (예: cirno)')
    ap.add_argument('--fork', required=True, help='fork 경로 (game/taisei)')
    ap.add_argument('--bg-name', required=True, help='스펠 배경 타일 이름 (gfx/stage1/<bg-name>.webp)')
    ap.add_argument('--gutter-x', type=int, help='전신 패널과 오른쪽 패널 사이 세로 경계 x (자동 감지 대신)')
    ap.add_argument('--gutter-y', type=int, help='초상 패널과 전투 패널 사이 가로 경계 y')
    ap.add_argument('--char-box', help='전신 패널 안에서 캐릭터만 담은 상자 비율 x0,y0,x1,y1 (0~1, 기본 전체)')
    ap.add_argument('--work', default='build/theme-extract', help='중간 결과 저장 폴더')
    args = ap.parse_args()

    sheet = Image.open(args.sheet).convert('RGBA')
    fork = Path(args.fork)
    work = Path(args.work)
    work.mkdir(parents=True, exist_ok=True)

    full_box, face_box, battle_box = detect_panels(sheet, args)
    full = sheet.crop(full_box)
    if args.char_box:
        fx0, fy0, fx1, fy1 = (float(v) for v in args.char_box.split(','))
        full = full.crop((int(full.width * fx0), int(full.height * fy0), int(full.width * fx1), int(full.height * fy1)))
    full.save(work / f'{args.name}_panel_full.png')
    sheet.crop(battle_box).save(work / f'{args.name}_panel_battle.png')

    cutout = keep_largest_component(remove_background(full))
    cutout.save(work / f'{args.name}_cutout.png')
    bb = cutout.getbbox()
    if bb is None:
        raise SystemExit('컷아웃이 비어 있다. --char-box나 --gutter-x를 확인한다')

    portraits = fork / 'atlas/portraits/dialog'
    configs = fork / 'atlas/config/dialog'
    portrait_png = work / f'{args.name}_portrait.png'
    face_region = make_portrait(cutout, portrait_png)

    # 옛 알파맵 제거(있으면 새 그림에 잘못 적용된다)
    for p in portraits.glob(f'{args.name}*.alphamap.*'):
        p.unlink()
        log(f'삭제: {p.name}')

    # 표정 패치·변형: 같은 그림을 normal/angry/defeated와 defeated 변형에 쓴다(임시)
    cmd = [sys.executable, str(HERE / 'theme_assets.py'), 'make-faces', '--base', str(portrait_png),
           '--face', f'normal={portrait_png}', '--face', f'angry={portrait_png}', '--face', f'defeated={portrait_png}',
           '--variant', f'defeated={portrait_png}', '--name', args.name,
           '--out-dir', str(portraits), '--config-dir', str(configs),
           '--region', ','.join(str(v) for v in face_region)]
    subprocess.run(cmd, check=True)

    make_sprites(cutout, fork / 'atlas/common/boss', args.name)
    make_bg_tile(sheet.crop(battle_box), fork / 'resources/00-taisei.pkgdir/gfx/stage1' / f'{args.bg_name}.webp')
    log('완료. 다음: gen-atlas.py로 common·portraits 재생성, 스펠 배경 참조를 코드에서 바꾼 뒤 빌드')


if __name__ == '__main__':
    main()
