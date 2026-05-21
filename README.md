<div align="center">

# 🎙️ MIC Analysis Tool v1.1

**MIC 공정 로그를 빠르게 병합·분석하고, 대시보드와 엑셀 리포트까지 한 번에 만드는 Streamlit 기반 분석 도구**

[Quick Start](#-quick-start) · [주요 기능](#-주요-기능) · [사용 흐름](#-사용-흐름) · [프로젝트 구조](#-프로젝트-구조)

</div>

---

## 📖 개요

[`MIC Analysis Tool`](README.md)는 마이크(MIC) 양산 로그 CSV를 업로드해 다음 작업을 수행합니다.

- 제품 모델 자동 감지
- 주파수 응답(FR) / Cpk 분석
- 샘플 기준 불량 유형 분류
- 결함 시료 상세 조회
- Excel 리포트 생성

최근 기준으로는 **동일 제품의 여러 CSV를 한 번에 업로드해 append 처리**할 수 있고, 분석/그래프/엑셀 생성 경로도 캐시 및 지연 실행 구조로 최적화되어 대용량 시료에 더 잘 대응합니다.

## ✨ 주요 기능

- **자동 모델 식별**
  - Serial Number 규칙을 바탕으로 제품 모델, P/N, 생산일을 감지합니다.
- **다중 CSV 업로드 지원**
  - 동일 제품, 동일 컬럼 구조인 여러 CSV를 업로드하면 `test_data` 기준으로 append 처리합니다.
  - 생산일이 다르면 병기 표시합니다.
  - limit row가 다를 경우 첫 번째 파일의 limit를 대표 기준으로 사용하고 경고를 표시합니다.
- **샘플 기준 불량 집계**
  - 다중 채널 불량이 겹칠 경우 우선순위 `Curved Out > No Signal > Margin Out > Nan` 으로 대표 불량 유형을 집계합니다.
- **대시보드 시각화**
  - Production Dashboard
  - 채널별 Precision Metrics Summary
  - FR / Cpk / 결함 상세 / 기타 Yield & 통계 탭 제공
- **요약 통계 확장**
  - 1kHz 채널 통계
  - 200Hz / 4kHz 통계
  - Digital MIC 통합 통계
- **Excel 리포트 생성**
  - 파일명 규칙: `YYMMDD_PN_REPORT.xlsx`
  - 숫자 셀은 가능한 범위에서 Numeric type으로 기록
  - `📈 분석 리포트`, `🔍 결함상세`, `📊 통계요약` 시트 구성

## 🚀 Quick Start

### 1. 요구 사항

- Python 3.8+
- Windows 환경 권장

설치 패키지:

```bash
pip install streamlit pandas matplotlib numpy xlsxwriter chardet
```

### 2. 실행

```bash
streamlit run App_Main.py
```

### 3. 가장 빠른 사용 흐름

1. 사이드바에서 하나 이상의 CSV를 업로드합니다.
2. 모델 자동 감지 결과를 확인하고 필요 시 제품 모델을 선택합니다.
3. `정상 시료 FR 표시` 옵션으로 정상 시료 오버레이 여부를 설정합니다.
4. `❌ 결함 시료 선택` 섹션에서 관심 시료를 선택합니다.
5. 대시보드 / FR / Cpk / 결함 상세 / 기타 Yield & 통계를 확인합니다.
6. 필요 시 `📦 리포트 생성` 후 `📥 Download Report` 로 엑셀을 저장합니다.

## 🧠 다중 업로드 규칙

다중 CSV 업로드는 아래 조건에서만 append 됩니다.

| 항목 | 규칙 |
| --- | --- |
| 제품 모델 | 동일해야 함 |
| 컬럼 구조 | 동일해야 함 |
| limit row | 달라도 허용, 첫 파일 기준 사용 |
| 생산일 | 다르면 병기 표시 |
| P/N | 다르면 `MULTI` 처리 |

즉, **같은 제품 로그를 여러 파일로 나눠 관리하는 경우** 한 번에 합쳐서 분석할 수 있습니다.

## ⚡ 성능 최적화 포인트

최근 기준으로 아래 성능 개선이 반영되어 있습니다.

- 업로드 파일 파싱 캐시
- 제품 감지 결과 캐시
- 분석 결과 [`AnalysisReport`](core/domain.py) 캐시
- FR / Cpk 시각화용 사전 계산 재사용
- 엑셀 리포트 지연 생성 및 세션 캐시
- 채널 단위 사전 계산 기반 분석 파이프라인

따라서 예전처럼 결함 시료를 체크할 때마다 CSV 파싱, 전체 분석, 엑셀 생성이 모두 다시 도는 구조는 상당 부분 줄어들었습니다.

## 📊 분석 기능

### 불량 유형

- `Nan`: 측정 데이터 누락
- `No Signal`: 신호 없음 (Digital -45dB / Analog -30dB 미만)
- `Margin Out`: 주요 검사 주파수(200Hz, 1kHz, 4kHz) 포인트 규격 이탈
- `Curved Out`: 주요 검사 주파수 외 FR 곡선 구간 규격 이탈

### 시각화 탭

- `📈 주파수 응답 (FR)`
  - 정상 시료 및 선택 결함 시료 응답 곡선
- `📉 정규분포 (Cpk)`
  - 1kHz 기준 분포 / Cpk 시각화
- `🔍 결함 시료 상세`
  - 시료별 200Hz / 1kHz / 4kHz / THD / Status 상세
- `📊 기타 Yield & 통계`
  - 불량 유형 요약
  - 200Hz / 4kHz 통계
  - Digital MIC 통합 통계

## 📄 Excel 리포트

Excel 리포트는 [`export/excel_report.py`](export/excel_report.py) 기반으로 생성됩니다.

포함 시트:

- `📈 분석 리포트`
- `🔍 결함상세`
- `📊 통계요약`

주요 특성:

- 샘플 기준 불량 요약 반영
- 숫자 셀 Numeric type 기록 보강
- 통계요약 시트 디자인 개선
- 테스트용 생성/캡처 루프는 [`archive/bugfix/`](archive/bugfix) 아래 보조 스크립트로 관리

## 🧱 프로젝트 구조

### 루트

- [`App_Main.py`](App_Main.py): Streamlit 엔트리 포인트
- [`README.md`](README.md): 프로젝트 문서
- [`logo.png`](logo.png): 상단 로고
- [`excel_icon.png`](excel_icon.png): 엑셀 다운로드 영역 아이콘

### 설정

- [`config/specs.py`](config/specs.py): 제품/채널/limit 명세 객체
- [`config/product_config.py`](config/product_config.py): 제품 카탈로그 정의
- [`config/limits.py`](config/limits.py): defect/limit 정책 정의

### 핵심 로직

- [`core/parser.py`](core/parser.py): CSV 읽기, 감지, 컬럼/limit 시그니처 처리
- [`core/application.py`](core/application.py): 업로드 파일 준비 및 병합 orchestration
- [`core/domain.py`](core/domain.py): 도메인 모델 및 통계 구조
- [`core/analyzer.py`](core/analyzer.py): 분석 엔진 / 분류 / 벡터화 기반 계산

### 출력

- [`export/excel_report.py`](export/excel_report.py): Excel 리포트 생성기

### 참고 / 보조

- [`design/`](design): UI 리워크 참고 자료
- [`test_log/`](test_log): 테스트용 CSV 샘플
- [`archive/bugfix/`](archive/bugfix): 엑셀 렌더링/캡처/디버깅 보조 스크립트 및 산출물

## 🧪 테스트 및 검증

문법 검증:

```bash
python -m py_compile App_Main.py core\parser.py core\application.py core\analyzer.py core\domain.py export\excel_report.py
```

엑셀 미리보기/캡처 보조 스크립트:

- [`archive/bugfix/generate_preview_report.py`](archive/bugfix/generate_preview_report.py)
- [`archive/bugfix/export_excel_sheets_to_pdf.py`](archive/bugfix/export_excel_sheets_to_pdf.py)
- [`archive/bugfix/capture_excel_sheets.py`](archive/bugfix/capture_excel_sheets.py)

## 📌 참고 사항

- 다중 업로드는 append 편의를 위한 기능이며, 제품이 다르면 병합하지 않습니다.
- limit row가 다를 경우 첫 파일 기준을 사용하므로, 운영 시 어떤 파일을 먼저 올리는지 유의해야 합니다.
- FR 전체 렌더링은 시료 수가 매우 많을 경우 여전히 시각화 비용이 클 수 있습니다.

## 👨‍💻 Credits

- **Provided by**: JW Lee, JJ Kim

---
