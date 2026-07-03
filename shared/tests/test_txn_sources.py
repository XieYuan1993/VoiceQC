import json
from pathlib import Path

from voiceqa_shared.txn_sources import parse_file


def test_quam_client_history_order_report_imports_all_parseable_rows() -> None:
    config = json.loads(
        Path("mocks/data/mapping_template_quam.json").read_text(encoding="utf-8")
    )["config"]
    csv_data = "\n".join(
        [
            "交易日,生成時間,訂單號,證券賬號,客户姓名,證券代碼,證券名稱,市場,買賣方向,開平方向,委託價格,委託數量,掛單數量,成交數量,成交金額,訂單狀態,對手方席位號,經紀人編號,信息,委託人,委託渠道,執行類型,上手經紀商,上手賬號,證券類別",
            '13/5/2026,2026-05-13 09:01:15 HKT,"""123""",213116,WG CAPITAL LTD.,1801,信達生物,HK,賣出,平倉,96.5,"1,000","1,000",0,0,已委託,,QUAMIBIS022,--,Ken Chow,WTT,NewExec,HKEX,,正股',
            '13/5/2026,2026-05-13 10:15:48 HKT,"""123""",213116,WG CAPITAL LTD.,1801,信達生物,HK,賣出,平倉,96.5,"1,000",0,500,"48,250.00",部分成交,,QUAMIBIS022,--,Ken Chow,WTT,TradeExec,HKEX,,正股',
            '13/5/2026,2026-05-13 10:16:48 HKT,"""123""",213116,WG CAPITAL LTD.,1801,信達生物,HK,賣出,平倉,96.5,"1,000",0,500,"48,250.00",成交,,QUAMIBIS022,--,Ken Chow,WTT,TradeExec,HKEX,,正股',
        ]
    ).encode()

    txns = parse_file("orders.csv", csv_data, config)
    imported = [t for t in txns if t.skip_reason is None]

    assert len(imported) == 3
    assert [t.ext_txn_id for t in imported] == ["123", "123-2", "123-3"]
    assert imported[0].trade_date.isoformat() == "2026-05-13"
    assert imported[0].broker_code == "QUAMIBIS022"
    assert imported[0].client_account == "213116"
    assert imported[0].stock_code == "1801"
    assert imported[0].stock_name == "信達生物"
    assert imported[0].side == "sell"
    assert imported[0].quantity == 0
    assert imported[0].amount == 0
    assert imported[0].channel == "phone"
    assert imported[0].raw["order_status"] == "已委託"
    assert imported[0].raw["execution_type"] == "NewExec"
    assert imported[1].raw["order_status"] == "部分成交"
    assert imported[1].raw["execution_type"] == "TradeExec"
