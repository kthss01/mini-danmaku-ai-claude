// Taisei 웹 셸과 게임 산출물(세션 1 빌드 결과) 사이의 연결 지점.
// 산출물 계약이 바뀌면 이 파일만 수정한다. shell.js는 이 값만 참조한다.
//
// 현재 가정(세션 1 계약 확정 전, 실제 빌드 산출물 관찰 기준):
// - 게임 로더: taisei.js (Emscripten MODULARIZE=1, EXPORT_NAME=createTaisei)
// - taisei.wasm은 taisei.js가 자기 스크립트 URL 기준 상대 경로로 찾는다(locateFile 기본 동작).
// - 리소스는 wasm 내부 상수 "data/<content_id>"로 fetch된다. 이 URL은 HTML 문서 URL 기준 상대 경로이므로
//   data/ 디렉터리는 반드시 index.html과 같은 디렉터리에 있어야 한다(gameBase를 바꿔도 data/ 위치는 바뀌지 않는다).
window.TAISEI_SHELL_CONFIG = {
    // 게임 로더·wasm이 놓인 디렉터리. 페이지 기준 상대 경로이며 빈 문자열은 같은 디렉터리를 뜻한다. 예: 'game/'
    gameBase: '',
    // Emscripten이 생성한 로더 파일 이름
    gameScript: 'taisei.js',
    // -sEXPORT_NAME 으로 지정된 전역 팩터리 함수 이름
    factoryName: 'createTaisei',
    // 팩터리가 돌려준 인스턴스에서 셸이 호출하는 메서드(preamble.js가 정의). 없으면 계약 불일치 오류로 처리한다.
    requiredInstanceMethods: ['initFilesystem', 'callMain'],
    // 라이선스 고지 파일(세션 1이 산출물에 포함). 없으면 링크만 깨진다.
    licenseFile: 'COPYING.txt',
};
