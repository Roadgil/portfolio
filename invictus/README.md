# INVICTUS — 콜로세움의 검투사 (PWA)

Blood & Glory 스타일 3D 1대1 스와이프 검투 액션. 빌드 도구 없이 정적 파일만으로 동작합니다.

## GitHub Pages 배포
1. 새 저장소를 만들고 이 폴더의 **모든 파일을 저장소 루트에 업로드** (`index.html`이 루트에 오도록)
2. Settings → Pages → Source: `Deploy from a branch` → Branch `main` / `(root)` → Save
3. 1~2분 뒤 `https://<아이디>.github.io/<저장소>/` 접속

모든 경로가 상대경로라 하위 폴더에 올려도 동작합니다.

## 폰에 설치 (Galaxy · Android Chrome)
사이트 접속 → 메뉴(⋮) → **홈 화면에 추가 / 앱 설치** → 홈 아이콘으로 실행하면 상태바 없는 전체화면 세로 모드로 실행됩니다.
첫 실행만 온라인이 필요하고, 이후에는 서비스 워커 캐시로 오프라인 플레이가 가능합니다.

## 업데이트할 때
파일을 고친 뒤 `sw.js` 맨 위의 `VERSION` 값을 올려야(예: `invictus-v1.0.1`) 설치된 앱의 캐시가 갱신됩니다.

## 조작
- 스와이프: 8방향 베기 (다른 방향으로 이어 베면 콤보 배율↑, 중간에 꺾어 그으면 페인트)
- 패링: 적 궤적이 번쩍일 때 **궤적 반대 방향**으로 스와이프 → 그로기(데미지 ×2)
- 방패(홀드) · 저스트 가드 / 좌·우 회피(붉은 공격은 회피만 가능, 타이밍 회피 시 불릿타임)
- 분노 게이지 MAX → 필살(인빅투스) · 빈사 그로기 적은 처형 QTE
- PC: 마우스 드래그 베기, A/D 회피, S·Space 방패, Q 포션, E 필살, Esc 일시정지

## 구성
```
index.html · manifest.json · sw.js · css/style.css · icons/
js/ main(루프·시간제어) config(데이터) engine(렌더러·Bloom·PMREM·동적DPR) textures(절차적 PBR)
    arena(콜로세움) gladiator(IK 검투사·망토) viewmodel(1인칭) fx(파티클·검기·궤적) camera
    ai(적 패턴) combat(전투 규칙·QTE·시네마틱) ui · input(스와이프) · audio(Web Audio·햅틱) · save
```
Three.js r170 (`cdn.jsdelivr.net/npm/three@0.170.0`, import map 방식)을 사용합니다.
