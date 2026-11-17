"""Offline tests for parsing ERCOT Public API data (no credentials needed)."""
import io
import zipfile

import pandas as pd

from vppa import ercot_api


def _rows(date, hours, dst=None):
    """ERCOT-style rows: delivery date, hour ending 1-24, interval 1-4."""
    hrs = [h for h in hours for _ in range(4)]
    return pd.DataFrame({
        "DeliveryDate": pd.Timestamp(date),
        "DeliveryHour": hrs,
        "DeliveryInterval": [1, 2, 3, 4] * len(hours),
        "DSTFlag": dst if dst is not None else [False] * len(hrs),
    })


def test_hour_ending_becomes_interval_start():
    t = ercot_api.interval_start(_rows("2024-07-01", [1, 24]))
    assert str(t.iloc[0]) == "2024-07-01 00:00:00-05:00"      # HE1, interval 1
    assert str(t.iloc[3]) == "2024-07-01 00:45:00-05:00"      # HE1, interval 4
    assert str(t.iloc[-1]) == "2024-07-01 23:45:00-05:00"     # HE24, interval 4


def test_repeated_fall_back_hour_is_kept_apart():
    # 3 Nov 2024: hour ending 2 happens twice; the second copy has DSTFlag=True.
    df = _rows("2024-11-03", [2, 2], dst=[False] * 4 + [True] * 4)
    t = ercot_api.interval_start(df)
    assert t.nunique() == 8
    assert t.iloc[4] - t.iloc[0] == pd.Timedelta(hours=1)


def _zip_of_zips(csv_text):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("SPPHLZNP6905_20230101_0015.csv", csv_text)
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("doc.SPPHLZNP6905_20230101_0015_csv.zip", inner.getvalue())
    return outer.getvalue()


def test_archive_zip_keeps_only_requested_points():
    csv = ("DeliveryDate,DeliveryHour,DeliveryInterval,SettlementPointName,"
           "SettlementPointType,SettlementPointPrice,DSTFlag\n"
           "01/01/2023,1,1,BRISCOE_WIND,RN,-3.5,N\n"
           "01/01/2023,1,1,HB_WEST,HU,10.0,N\n"
           "01/01/2023,1,1,SOME_OTHER,RN,99.0,N\n")
    df = ercot_api._read_archive_zip(_zip_of_zips(csv), {"BRISCOE_WIND", "HB_WEST"})
    assert sorted(df["SettlementPointName"]) == ["BRISCOE_WIND", "HB_WEST"]
    assert df.loc[df["SettlementPointName"] == "BRISCOE_WIND", "SettlementPointPrice"].item() == -3.5
    assert not df["DSTFlag"].any()


def test_project_node_is_in_the_cached_list():
    from vppa import config
    assert config.NODE in ercot_api.WEST_WIND_NODES
