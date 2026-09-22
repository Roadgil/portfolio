# Roadgil Portfolio

Candela Korea 수입/통관/재무/수출/파트오더/대시보드 업무를 자동화한 사내 프로젝트들의 포트폴리오.
루트의 `portfolio_*.html`은 각 프로젝트를 소개하는 페이지(디자인/카피는 손으로 다듬은 것이라 임의로 재작성하지 않음), `index.html`이 전체 목록이다.
`code/` 아래에는 각 프로젝트의 실제 운영 소스 코드가 들어있다. 사내 자동화 스크립트를 그대로 가져온 것이므로
회사 내부 경로/담당자명/이메일 등이 코드에 남아있을 수 있다.

## 프로젝트 ↔ 코드 매핑

| 카드 | 코드 |
|---|---|
| `portfolio_import_automation.html` | [`code/import-customs/`](code/import-customs/) |
| `portfolio_finance_automation.html` | [`code/finance-automation/`](code/finance-automation/) |
| `portfolio_wd_cost_tracking.html` | [`code/wd-cost-tracking/`](code/wd-cost-tracking/) |
| `portfolio_oracle_automation.html` | [`code/outbound-rpa/`](code/outbound-rpa/) |
| `portfolio_sco_cancellation.html` | [`code/sco-cancellation/`](code/sco-cancellation/) |
| `portfolio_rma_automation.html` | [`code/rma-automation/`](code/rma-automation/) |
| `portfolio_export_rebalance.html` | [`code/export-rebalance/`](code/export-rebalance/) |
| `portfolio_part_order_app.html` | [`code/part-order-app/`](code/part-order-app/) |
| `portfolio_invoice_generator.html` | [`code/invoice-generator/`](code/invoice-generator/) |
| `portfolio_inventory_dashboard.html` | [`code/krp-inventory-dashboard/`](code/krp-inventory-dashboard/) |
| `portfolio_fse_inventory.html` | [`code/warehouse-monthly-closing/`](code/warehouse-monthly-closing/) |
| `portfolio_monthly_visit_pm.html` | [`code/equipment-pm-webapp/`](code/equipment-pm-webapp/) |
| `portfolio_customer_order_management.html` | part-order-app + [`code/dcd-can-recovery/`](code/dcd-can-recovery/) |
| `portfolio_supply_chain.html` | export-rebalance + rma-automation (허브 페이지, 자체 코드 없음) |
| `portfolio_sales_dashboard.html` | 별도 저장소 [Roadgil/sales-dashboard](https://github.com/Roadgil/sales-dashboard) |

## 안내

- 각 `code/<project>/` 폴더의 `NOTES.md`에 원본 로컬 경로, 실행 방식(스케줄러/트리거), **실제 재실행에 필요한 패키지/외부 의존성/환경변수, 재사용 시 고쳐야 할 것**이 정리되어 있다.
- state/cache json, 실행 로그, `.bak` 백업 파일, PDF/Excel 데이터 파일은 전시 목적상 제외했다.
- `code/export-rebalance/dhl_export_arrange.py`, `fedex_ship_watcher.py`의 물류포털 로그인 비밀번호는 하드코딩을 제거하고 환경변수(`DHL_PASSWORD`, `FEDEX_PASSWORD`)로 읽도록 코드를 고쳤다(2026-09-22).
