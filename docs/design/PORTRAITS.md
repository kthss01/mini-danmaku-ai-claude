# 캐릭터 초상화 교체 안내

캐릭터 선택 화면과 대화 장면에 쓰는 초상화를 새 그림으로 바꾸는 절차다. 1단계 UI 현대화([UI_MODERNIZATION.md](UI_MODERNIZATION.md))는 그림 파일을 건드리지 않고 그릴 때만 보정(림라이트·바닥 페이드·채도)하므로, 새 그림은 아래 규칙대로 파일을 바꿔 끼우고 아틀라스를 다시 만들면 된다.

## 1. 파일 위치와 이름

원본 그림은 fork의 `game/taisei/atlas/portraits/dialog/`에 있다(Git 추적).

| 파일 | 역할 | 예 |
| --- | --- | --- |
| `<char>.webp` | 기본 초상화(몸 전체) | `reimu.webp` 621×982 |
| `<char>_face_<expr>.webp` | 표정 파츠(눈·입 주변만 잘라낸 그림) | `reimu_face_normal.webp` 125×115 |
| `<char>_variant_<name>.webp` | 변형 초상화(패배 등) | `cirno_variant_defeated.webp` |
| `<char>.alphamap.webp` | (선택) 알파를 별도 흑백 파일로 둘 때 | `cirno.alphamap.webp` |

캐릭터 이름은 11명(reimu, marisa, youmu, cirno, hina, wriggle, kurumi, iku, elly, scuttle, yumemi)이며 플레이어 3명이 캐릭터 선택 화면에 나온다. png도 되지만 저장소는 webp(무손실)를 쓴다.

표정 파츠 위치는 `game/taisei/atlas/config/dialog/<char>_face_<expr>.spr`의 `padding_top/bottom/left/right`로 정한다. 기본 초상화와 같은 캔버스에서 잘라낸 파츠라면 네 값은 캔버스 안에서 파츠 바깥쪽 여백이다. **단위는 표시 단위(원본 px × 0.5)** 다. 예: `reimu_face_normal.spr`는 top 61, bottom 372.5, left 147, right 101이고 61 + 57.5(파츠 높이 115 × 0.5) + 372.5 = 491 = 982 × 0.5이다.

게임 코드가 참조하는 표정 이름은 다음과 같다. 같은 이름을 유지하면 코드 수정 없이 교체된다.

- 캐릭터 선택: happy, normal, puzzled, smug, surprised, unamused (`src/menu/charselect.c`의 `facedefs`)
- 대화·미리 불러오기: `src/menu/charselect.c`의 `preload_char_menu`, `src/dialog/*.c`

## 2. 크기와 표시

- 아틀라스 스프라이트는 기본 배율 0.5로 표시된다(`game/taisei/scripts/taiseilib/atlas.py`의 `DEFAULT_SPRITE_SCALE`). 원본 621×982는 게임 화면(800×600 기준)에서 310.5×491로 그려진다.
- 캐릭터 선택 화면은 초상화 아래 끝을 화면 아래(y = 600)에 맞춘다. 세로 982px 원본이면 머리 위가 y ≈ 109에 온다. 세로 1180px 정도면 화면 위까지 찬다.
- 권장: 세로 980~1180px, 가로 500~650px, 투명 배경. 림라이트가 알파 경계를 따라 생기므로 경계가 깨끗해야 한다. 아래 16%는 페이드되므로 발끝까지 그릴 필요는 없다.
- 표정 파츠는 기본 초상화와 같은 캔버스에서 눈·입 부위만 잘라 저장하고 padding 값을 다시 계산한다.

## 3. 아틀라스 재생성

웹 빌드 컨테이너는 아틀라스를 다시 만들지 않으므로, 원본을 바꾼 뒤 아래 결과물을 fork에 함께 커밋해야 한다.

- 결과물: `game/taisei/resources/00-taisei.pkgdir/gfx/portraits.tsatlas.zst`, `gfx/dialog/*.spr`(자동 생성, 90개)
- 필요한 Python 모듈: `Pillow rectpack numpy backports.zstd` (Python 3.12 기준. 3.14+는 `backports.zstd` 대신 표준 `compression.zstd`)

```powershell
python -m venv .venv-atlas
.\.venv-atlas\Scripts\python.exe -m pip install Pillow rectpack numpy backports.zstd
Set-Location game\taisei
..\..\.venv-atlas\Scripts\python.exe scripts\gen-atlas.py atlas\config atlas\portraits resources\00-taisei.pkgdir\gfx --border=2 --tsatlas-sort=perimeter --format tsatlas --width=512 --height=512 --samples=256 --single --tsatlas-zstd-level=22
```

옵션은 `game/taisei/atlas/meson.build`의 기본 프로필(`preset_tsatlas` + `preset_thorough` + portraits 전용 `--tsatlas-sort=perimeter`)과 같다. Meson 빌드 디렉터리가 있으면 `ninja -C build gen-atlas-portraits`로도 된다.

2026-10-29 검증(세션 `mini-danmaku-ai-claude-design`, fork `f59212b7` 원본 그대로): 106초 소요, `dialog/*.spr` 90개는 커밋본과 동일, `portraits.tsatlas.zst`는 3,941,621바이트로 커밋본(3,942,699바이트)과 크기가 다르다(패킹 시도·zstd 출력의 비결정성, 내용은 같은 원본). 재생성한 tsatlas를 실제 빌드에 넣어 로드 확인은 아직 하지 않았다. 원본이 바뀌지 않았으면 재생성 결과를 커밋하지 않는다.

## 4. 반영 경로

1. fork 브랜치에 원본 webp·config·재생성한 tsatlas/spr을 커밋
2. fork PR → 검토 → 머지
3. 메인 저장소에서 `game/taisei` gitlink 갱신 PR → main 머지 → GitHub Pages 자동 배포

## 5. 라이선스

현재 초상화는 afensorm 작, CC BY 4.0이며 `game/taisei/COPYING.txt`에 고지되어 있다. 새 그림을 넣을 때는 작가·라이선스·출처를 같은 파일에 추가(또는 교체)한다. 빌드가 그 `COPYING.txt`를 배포물(`site/COPYING.txt`, `site/game/COPYING.txt`)에 복사하므로 별도 작업은 없지만, 게임 셸 하단 라이선스 링크에서 새 고지가 보이는지 확인한다.
