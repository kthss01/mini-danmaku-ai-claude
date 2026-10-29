#!/usr/bin/env python3
"""자전거 테마 캐릭터 이미지 준비 도구.

ChatGPT에서 받은 콘셉트 이미지를 Taisei 아틀라스 규격(docs/design/BICYCLE_THEME.md 4·5절)으로
검사하고 가공한다. 의존성은 Pillow뿐이다(pip install Pillow).

  check-frames     전투 스프라이트 프레임들의 캔버스·투명 배경·기준점 편차 검사
  split-sheet      스프라이트 시트(행×열 격자)를 프레임 PNG로 분할
  check-portraits  초상화 세트(같은 포즈, 표정만 다름)의 캔버스·실루엣 일치 검사
  make-faces       기본 초상화와 달라진 영역을 잘라 표정 패치(.webp)와 padding(.spr) 생성

모든 명령은 결과 표를 출력하고, 규격에 어긋나면 종료 코드 1을 돌려준다.
"""

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageChops

# 아틀라스 스프라이트 표시 배율 (game/taisei/scripts/taiseilib/atlas.py DEFAULT_SPRITE_SCALE)
DISPLAY_SCALE = 0.5
ALPHA_THRESHOLD = 8


def load_rgba(path):
    return Image.open(path).convert('RGBA')


def alpha_mask(img, threshold=ALPHA_THRESHOLD):
    return img.getchannel('A').point(lambda v: 255 if v > threshold else 0)


def alpha_bbox(img):
    return alpha_mask(img).getbbox()


def corners_transparent(img):
    w, h = img.size
    corners = [img.getpixel((x, y))[3] for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    return max(corners) <= ALPHA_THRESHOLD, corners


def print_table(rows, columns):
    if not rows:
        return
    print('| ' + ' | '.join(columns) + ' |')
    print('|' + '---|' * len(columns))
    for row in rows:
        print('| ' + ' | '.join(str(row.get(c, '')) for c in columns) + ' |')


def finish(rows, columns, problems, args):
    if getattr(args, 'json', False):
        print(json.dumps({'rows': rows, 'problems': problems}, ensure_ascii=False, indent=2))
    else:
        print_table(rows, columns)
        if problems:
            print('\n문제:')
            for p in problems:
                print(f'- {p}')
        else:
            print('\n문제 없음')
    return 1 if problems else 0


def cmd_check_frames(args):
    paths = sorted(Path(p) for p in args.frames)
    rows, problems, sizes = [], [], set()

    for p in paths:
        im = load_rgba(p)
        sizes.add(im.size)
        bb = alpha_bbox(im)

        if bb is None:
            problems.append(f'{p.name}: 불투명 픽셀이 없다')
            continue

        ok, corners = corners_transparent(im)
        if not ok:
            problems.append(f'{p.name}: 모서리가 투명하지 않다 (alpha {corners})')

        rows.append({
            'frame': p.name,
            'canvas': f'{im.width}x{im.height}',
            'center_dx': round((bb[0] + bb[2]) / 2 - im.width / 2, 1),
            'top_margin': bb[1],
            'bottom_margin': im.height - bb[3],
            'height_ratio': round((bb[3] - bb[1]) / im.height, 3),
        })

    if len(sizes) > 1:
        problems.append(f'캔버스 크기가 서로 다르다: {sorted(sizes)}')

    if rows:
        dxs = [r['center_dx'] for r in rows]
        bms = [r['bottom_margin'] for r in rows]
        if max(dxs) - min(dxs) > args.tolerance:
            problems.append(f'프레임 간 수평 중심 편차 {max(dxs) - min(dxs):.1f}px > 허용 {args.tolerance}px')
        if max(bms) - min(bms) > args.tolerance:
            problems.append(f'프레임 간 발끝 높이 편차 {max(bms) - min(bms)}px > 허용 {args.tolerance}px')
        for r in rows:
            if r['height_ratio'] < args.min_height_ratio:
                problems.append(f"{r['frame']}: 캐릭터 높이 비율 {r['height_ratio']} < {args.min_height_ratio}")

    if args.expect_count and len(rows) != args.expect_count:
        problems.append(f'프레임 수 {len(rows)} != 기대 {args.expect_count}')

    return finish(rows, ['frame', 'canvas', 'center_dx', 'top_margin', 'bottom_margin', 'height_ratio'], problems, args)


def cmd_split_sheet(args):
    sheet = load_rgba(args.sheet)
    cols, rows_n = args.cols, args.rows

    if args.cell:
        cw, ch = (int(v) for v in args.cell.lower().split('x'))
    else:
        cw, ch = sheet.width // cols, sheet.height // rows_n

    ox, oy = (int(v) for v in args.origin.split(','))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    index = args.start

    for r in range(rows_n):
        for c in range(cols):
            x0 = ox + c * (cw + args.gap)
            y0 = oy + r * (ch + args.gap)
            if x0 + cw > sheet.width or y0 + ch > sheet.height:
                print(f'셀 ({r},{c})이 시트 밖이다: {x0},{y0},{cw}x{ch} / 시트 {sheet.width}x{sheet.height}', file=sys.stderr)
                return 1
            cell = sheet.crop((x0, y0, x0 + cw, y0 + ch))
            dst = out_dir / f'{args.name}.frame{index:04d}.png'
            cell.save(dst, optimize=True)
            written.append(str(dst))
            index += 1

    print(f'{len(written)}개 프레임 저장 ({cw}x{ch}):')
    for w in written:
        print(f'  {w}')
    return 0


def cmd_check_portraits(args):
    paths = [Path(p) for p in args.images]
    base = load_rgba(paths[0])
    rows, problems = [], []

    for p in paths:
        im = load_rgba(p)
        bb = alpha_bbox(im)
        if bb is None:
            problems.append(f'{p.name}: 불투명 픽셀이 없다')
            continue
        ok, corners = corners_transparent(im)
        if not ok:
            problems.append(f'{p.name}: 모서리가 투명하지 않다 (alpha {corners})')
        if im.size != base.size:
            problems.append(f'{p.name}: 캔버스 {im.size}가 기준 {base.size}와 다르다')
            mismatch = None
        else:
            # 알파 실루엣이 기준과 얼마나 다른지 (표정만 다르면 거의 0)
            diff = ImageChops.difference(alpha_mask(base), alpha_mask(im))
            hist = diff.histogram()
            mismatch = round(hist[255] / (im.width * im.height), 4)
            if p != paths[0] and mismatch > args.max_silhouette_diff:
                problems.append(f'{p.name}: 실루엣 불일치 {mismatch:.2%} > 허용 {args.max_silhouette_diff:.0%} (포즈가 다르다)')

        rows.append({
            'image': p.name,
            'canvas': f'{im.width}x{im.height}',
            'display': f'{im.width * DISPLAY_SCALE:g}x{im.height * DISPLAY_SCALE:g}',
            'top_margin': bb[1],
            'bottom_margin': im.height - bb[3],
            'silhouette_diff': '' if mismatch is None else mismatch,
        })

        if bb[1] > args.max_top_margin:
            problems.append(f'{p.name}: 머리 위 여백 {bb[1]}px > 권장 {args.max_top_margin}px')

    return finish(rows, ['image', 'canvas', 'display', 'top_margin', 'bottom_margin', 'silhouette_diff'], problems, args)


def diff_bbox(base, other, threshold):
    # RGBA 네 채널 중 하나라도 threshold보다 다르면 달라진 픽셀로 본다
    diff = ImageChops.difference(base, other)
    bands = [b.point(lambda v: 255 if v > threshold else 0) for b in diff.split()]
    merged = bands[0]
    for b in bands[1:]:
        merged = ImageChops.lighter(merged, b)
    return merged.getbbox()


def expand_box(box, pad, size):
    x0, y0, x1, y1 = box
    return (max(0, x0 - pad), max(0, y0 - pad), min(size[0], x1 + pad), min(size[1], y1 + pad))


def write_spr(path, box, size):
    x0, y0, x1, y1 = box
    w, h = size
    lines = [
        f'padding_top = {y0 * DISPLAY_SCALE:g}',
        f'padding_bottom = {(h - y1) * DISPLAY_SCALE:g}',
        f'padding_left = {x0 * DISPLAY_SCALE:g}',
        f'padding_right = {(w - x1) * DISPLAY_SCALE:g}',
    ]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')


def save_webp(img, path):
    img.save(path, 'WEBP', lossless=True, method=6)


def cmd_make_faces(args):
    base = load_rgba(args.base)
    out_dir, config_dir = Path(args.out_dir), Path(args.config_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    name = args.name
    rows, problems = [], []

    faces = {}
    for spec in args.face:
        expr, path = spec.split('=', 1)
        faces[expr] = load_rgba(path)

    variants = {}
    for spec in args.variant or []:
        vname, path = spec.split('=', 1)
        variants[vname] = load_rgba(path)

    for expr, im in faces.items():
        if im.size != base.size:
            problems.append(f'{expr}: 캔버스 {im.size}가 기본 초상화 {base.size}와 다르다')

    if problems:
        return finish(rows, [], problems, args)

    # 표정별로 기본 초상화와 달라진 영역을 구한다
    boxes = {}
    for expr, im in faces.items():
        bb = diff_bbox(base, im, args.diff_threshold)
        if bb is not None:
            boxes[expr] = expand_box(bb, args.pad, base.size)

    if args.region:
        rx, ry, rw, rh = (int(v) for v in args.region.split(','))
        union = (rx, ry, rx + rw, ry + rh)
    elif boxes:
        xs0 = min(b[0] for b in boxes.values())
        ys0 = min(b[1] for b in boxes.values())
        xs1 = max(b[2] for b in boxes.values())
        ys1 = max(b[3] for b in boxes.values())
        union = (xs0, ys0, xs1, ys1)
    else:
        problems.append('기본 초상화와 다른 표정이 하나도 없다. --region으로 얼굴 영역을 지정한다')
        return finish(rows, [], problems, args)

    # 모든 패치는 같은 영역(union)을 쓴다. 코드가 패치를 padding으로 배치하므로 영역이 같아야 표정 전환 때 튀지 않는다
    save_webp(base, out_dir / f'{name}.webp')
    rows.append({'file': f'{name}.webp', 'canvas': f'{base.width}x{base.height}', 'region': ''})

    for expr, im in faces.items():
        patch = im.crop(union)
        dst = out_dir / f'{name}_face_{expr}.webp'
        save_webp(patch, dst)
        write_spr(config_dir / f'{name}_face_{expr}.spr', union, base.size)
        rows.append({'file': dst.name, 'canvas': f'{patch.width}x{patch.height}', 'region': f'{union[0]},{union[1]} {union[2] - union[0]}x{union[3] - union[1]}'})

    for vname, im in variants.items():
        if im.size != base.size:
            problems.append(f'변형 {vname}: 캔버스 {im.size}가 기본 초상화 {base.size}와 다르다')
            continue
        save_webp(im, out_dir / f'{name}_variant_{vname}.webp')
        rows.append({'file': f'{name}_variant_{vname}.webp', 'canvas': f'{im.width}x{im.height}', 'region': ''})
        if vname not in faces:
            # 변형 전용 표정 패치: 변형 그림의 같은 영역을 잘라 둔다(같은 이름의 표정이 없을 때)
            patch = im.crop(union)
            dst = out_dir / f'{name}_face_{vname}.webp'
            save_webp(patch, dst)
            write_spr(config_dir / f'{name}_face_{vname}.spr', union, base.size)
            rows.append({'file': dst.name, 'canvas': f'{patch.width}x{patch.height}', 'region': f'{union[0]},{union[1]} {union[2] - union[0]}x{union[3] - union[1]}'})

    print(f'padding 단위는 표시 단위(원본 px × {DISPLAY_SCALE})이며 {config_dir}에 기록했다.')
    return finish(rows, ['file', 'canvas', 'region'], problems, args)


def main():
    # Windows 콘솔(cp949)에서도 한국어 메시지가 깨지지 않게 한다
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('check-frames', help='전투 스프라이트 프레임 검사')
    p.add_argument('frames', nargs='+', help='프레임 PNG 파일들')
    p.add_argument('--tolerance', type=float, default=10, help='프레임 간 중심·발끝 편차 허용 px (기본 10)')
    p.add_argument('--min-height-ratio', type=float, default=0.8, help='캐릭터 높이/캔버스 높이 최소 비율 (기본 0.8)')
    p.add_argument('--expect-count', type=int, default=0, help='기대 프레임 수 (0이면 검사 안 함)')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_check_frames)

    p = sub.add_parser('split-sheet', help='스프라이트 시트를 프레임으로 분할')
    p.add_argument('sheet')
    p.add_argument('--cols', type=int, required=True)
    p.add_argument('--rows', type=int, required=True)
    p.add_argument('--cell', help='셀 크기 WxH (생략하면 시트 크기를 행·열로 나눈다)')
    p.add_argument('--origin', default='0,0', help='첫 셀의 왼쪽 위 x,y (기본 0,0)')
    p.add_argument('--gap', type=int, default=0, help='셀 사이 간격 px')
    p.add_argument('--name', required=True, help='출력 이름 (예: cirno → cirno.frame0000.png)')
    p.add_argument('--start', type=int, default=0, help='첫 프레임 번호')
    p.add_argument('--out-dir', required=True)
    p.set_defaults(func=cmd_split_sheet)

    p = sub.add_parser('check-portraits', help='초상화 세트 검사 (첫 파일이 기준)')
    p.add_argument('images', nargs='+')
    p.add_argument('--max-silhouette-diff', type=float, default=0.02, help='기준 대비 실루엣 불일치 허용 비율 (기본 0.02)')
    p.add_argument('--max-top-margin', type=int, default=120, help='머리 위 여백 권장 최대 px (기본 120)')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_check_portraits)

    p = sub.add_parser('make-faces', help='표정 패치와 padding 생성')
    p.add_argument('--base', required=True, help='기본 초상화 (normal 포즈)')
    p.add_argument('--face', action='append', required=True, metavar='EXPR=PATH', help='표정 이름=전신 이미지 (여러 번)')
    p.add_argument('--variant', action='append', metavar='NAME=PATH', help='변형 전신 이미지 (예: defeated=...)')
    p.add_argument('--name', required=True, help='캐릭터 id (예: cirno)')
    p.add_argument('--out-dir', required=True, help='webp 출력 (atlas/portraits/dialog)')
    p.add_argument('--config-dir', required=True, help='.spr 출력 (atlas/config/dialog)')
    p.add_argument('--pad', type=int, default=12, help='달라진 영역 바깥 여유 px (기본 12)')
    p.add_argument('--diff-threshold', type=int, default=12, help='달라진 픽셀 판정 임계값 (기본 12)')
    p.add_argument('--region', help='얼굴 영역 강제 지정 x,y,w,h (원본 px)')
    p.add_argument('--json', action='store_true')
    p.set_defaults(func=cmd_make_faces)

    args = parser.parse_args()
    return args.func(args)


if __name__ == '__main__':
    sys.exit(main())
