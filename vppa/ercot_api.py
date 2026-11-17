"""
Resource-node prices from the ERCOT Public API (free account needed).

Hub and load-zone prices come from a public yearly Excel file (see data.py),
but prices at individual RESOURCE NODES (where a power plant connects) are
only published through ERCOT report NP6-905-CD "Settlement Point Prices at
Resource Nodes, Hubs and Load Zones" - 15-minute real-time prices.

The API serves this report in two ways:
  - a QUERY endpoint: filter by settlement point and date, but it only
    holds data from 11 Dec 2023 onwards;
  - an ARCHIVE endpoint: every original file, one per 15-minute interval
    (96 a day), each listing ALL ~1,000 settlement points. Needed for 2023.

Credentials are read from environment variables, never from the code:
    ERCOT_API_USERNAME, ERCOT_API_PASSWORD, ERCOT_PUBLIC_API_SUBSCRIPTION_KEY
Register at https://apiexplorer.ercot.com to get them.
"""
import io
import os
import time
import zipfile

import pandas as pd
import requests

from vppa import config

API = "https://api.ercot.com/api/public-reports"
REPORT = "np6-905-cd"
QUERY_URL = f"{API}/{REPORT}/spp_node_zone_hub"
ARCHIVE_URL = f"{API}/archive/{REPORT}"
QUERY_START = pd.Timestamp("2023-12-11")   # first (partial) delivery date the query endpoint holds

# ERCOT's sign-in service (Azure B2C, "password" flow). The client ID is
# public: it identifies the API, not the user.
TOKEN_URL = ("https://ercotb2c.b2clogin.com/ercotb2c.onmicrosoft.com/"
             "B2C_1_PUBAPI-ROPC-FLOW/oauth2/v2.0/token")
CLIENT_ID = "fec253ea-0d06-4272-a5e6-b478baeecd70"

# Resource nodes of West Texas wind farms (settlement load zone LZ_WEST),
# from ERCOT's settlement point and resource-node-to-unit mappings
# (report NP4-160-SG). Prices for all of them are kept in the cache so the
# project node (config.NODE) can be changed without downloading again.
# Grouped by region; comments = 2024-25 average price minus HB_WEST.
WEST_WIND_NODES = [
    # Panhandle: big wind export area, strongly negative basis (~ -9 $/MWh)
    "BRISCOE_WIND", "ROUTE66_RN", "SSPURT_WIND1", "SPLAIN1_RN", "SPLAIN2_RN",
    "HRFDWIND_ALL", "HART_WND_RN",
    # Big Spring / Snyder / Abilene-north (~ -4 to -6)
    "FLUVANNA_1_2", "DERMOTT_ALL", "MONT_WND_RN", "VERAWIND_ALL", "VERTIGO_UN1",
    "GPASTURE_ALL", "HORSECRK_RN", "AJAXWIND_RN", "VORT_ALL_RN", "YNG_WND_ALL",
    "BCATWD_WD_1", "SENATEWD_1", "WNDTS2_UNIT1", "WH_WIND_ALL", "CANYONWD_ALL",
    # Sweetwater / Abilene (~ -4 to 0)
    "TKWSW_ROSCOE", "TKWSW_CHAMP", "SWEETWND_1", "SWEETWN2_2_4", "SWEETWN3_3",
    "SWTWN4_WND45", "H_HOLLO_WND1", "HHOLLW2_WND1", "HHOLLW3_WND1", "HHOLLW4_WND1",
    "BUFF_GAP_ALL", "MESQCRK_ALL", "CALLAHA_WND1", "CAPRIDGE_ALL", "GOA_GOATWIND",
    "BRAZ_WND_ALL", "BULLCRK_1_2", "MOZART_WIND1", "TRENT_TRENT", "LACASAWD_RN",
    "BIGSAMWD_RN",
    # San Angelo / Permian edge: local load, positive basis (~ +3 to +13)
    "HI_LONE_ALL", "LGD_LANGFORD", "SGM_SIGNALMT", "KINGE_ALL", "KINGW_ALL",
    "WOODWRD1_RN", "WOODWRD2_RN", "INDNENR_1_RN", "INDNENR_2_RN", "INDNNWP_RN",
]


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------
class ErcotSession:
    """Signs in once and re-signs automatically when the 1-hour token expires."""

    def __init__(self):
        missing = [k for k in ("ERCOT_API_USERNAME", "ERCOT_API_PASSWORD",
                               "ERCOT_PUBLIC_API_SUBSCRIPTION_KEY") if not os.environ.get(k)]
        if missing:
            raise RuntimeError(f"Set these environment variables first: {', '.join(missing)}")
        self.http = requests.Session()
        self.token_time = 0.0
        self._sign_in()

    def _sign_in(self):
        r = self.http.post(TOKEN_URL, timeout=60, data={
            "username": os.environ["ERCOT_API_USERNAME"],
            "password": os.environ["ERCOT_API_PASSWORD"],
            "grant_type": "password",
            "scope": f"openid {CLIENT_ID} offline_access",
            "client_id": CLIENT_ID,
            "response_type": "id_token",
        })
        r.raise_for_status()
        self.http.headers.update({
            "Authorization": f"Bearer {r.json()['id_token']}",
            "Ocp-Apim-Subscription-Key": os.environ["ERCOT_PUBLIC_API_SUBSCRIPTION_KEY"],
        })
        self.token_time = time.time()

    def request(self, method, url, attempts=6, **kwargs):
        """GET/POST with re-sign-in after 50 minutes and back-off on 403/429/5xx
        (ERCOT sometimes answers a rate limit with 403) or a dropped connection."""
        for attempt in range(attempts):
            if time.time() - self.token_time > 50 * 60:
                self._sign_in()
            try:
                r = self.http.request(method, url, timeout=300, **kwargs)
            except (requests.ConnectionError, requests.Timeout):
                if attempt == attempts - 1:
                    raise
                print(f"  connection dropped, retrying (attempt {attempt + 1})...")
                time.sleep(min(60, 5 * 2 ** attempt))
                continue
            if r.status_code == 401:
                self._sign_in()
            elif r.status_code in (403, 429) or r.status_code >= 500:
                time.sleep(min(60, 5 * 2 ** attempt))
            else:
                r.raise_for_status()
                return r
        r.raise_for_status()
        return r


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
def _query_point(api: ErcotSession, point: str, start: str, end: str) -> pd.DataFrame:
    """All 15-minute prices for one settlement point between two delivery dates."""
    rows, page = [], 1
    while True:
        j = api.request("GET", QUERY_URL, params={
            "settlementPoint": point, "deliveryDateFrom": start, "deliveryDateTo": end,
            "size": 200_000, "page": page}).json()
        rows += j["data"]
        if page >= j["_meta"]["totalPages"]:
            break
        page += 1
    cols = [f["name"] for f in j["fields"]]
    df = pd.DataFrame(rows, columns=cols)
    return pd.DataFrame({
        "DeliveryDate": pd.to_datetime(df["deliveryDate"]),
        "DeliveryHour": df["deliveryHour"].astype(int),
        "DeliveryInterval": df["deliveryInterval"].astype(int),
        "SettlementPointName": df["settlementPoint"],
        "SettlementPointPrice": df["settlementPointPrice"].astype(float),
        "DSTFlag": df["DSTFlag"].astype(bool),
    })


def _archive_doc_ids(api: ErcotSession, post_from: str, post_to: str) -> list:
    """IDs of every archived 15-minute file posted in a time window."""
    ids, page = [], 1
    while True:
        j = api.request("GET", ARCHIVE_URL, params={
            "postDatetimeFrom": post_from, "postDatetimeTo": post_to,
            "size": 1000, "page": page}).json()
        ids += [a["docId"] for a in j["archives"]]
        if page >= j["_meta"]["totalPages"]:
            break
        page += 1
    return ids


def _read_archive_zip(content: bytes, points: set) -> pd.DataFrame:
    """A bulk download is a zip of zips, each holding one CSV of all points."""
    frames = []
    with zipfile.ZipFile(io.BytesIO(content)) as outer:
        for name in outer.namelist():
            with zipfile.ZipFile(io.BytesIO(outer.read(name))) as inner:
                for csv in inner.namelist():
                    df = pd.read_csv(inner.open(csv))
                    frames.append(df[df["SettlementPointName"].isin(points)])
    df = pd.concat(frames, ignore_index=True)
    return pd.DataFrame({
        "DeliveryDate": pd.to_datetime(df["DeliveryDate"], format="%m/%d/%Y"),
        "DeliveryHour": df["DeliveryHour"].astype(int),
        "DeliveryInterval": df["DeliveryInterval"].astype(int),
        "SettlementPointName": df["SettlementPointName"],
        "SettlementPointPrice": df["SettlementPointPrice"].astype(float),
        "DSTFlag": df["DSTFlag"].eq("Y"),
    })


def _archive_prices(api: ErcotSession, year: int, points: list) -> pd.DataFrame:
    """Prices for a year before the query endpoint starts, from archived files."""
    # The query endpoint starts partway through QUERY_START's day, so the
    # archive covers that whole day too; duplicates are dropped later.
    end = min(pd.Timestamp(f"{year + 1}-01-01"), QUERY_START + pd.Timedelta(days=1))
    # Each file is posted a few minutes after its interval ends, so read a
    # little past the end of the window and keep only the delivery dates wanted.
    ids = _archive_doc_ids(api, f"{year}-01-01T00:00:00",
                           (end + pd.Timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S"))
    ids = sorted(ids)
    print(f"  {len(ids):,} archived 15-minute files to read")
    # Each batch is saved as it arrives, so an interrupted download resumes
    # where it stopped instead of starting the year over.
    parts_dir = config.DATA_DIR / f"_archive_parts_{year}"
    parts_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for i in range(0, len(ids), 1000):               # bulk download: up to 1,000 files per request
        batch = ids[i:i + 1000]
        part = parts_dir / f"{batch[0]}_{batch[-1]}.parquet"
        if part.exists():
            frames.append(pd.read_parquet(part))
            continue
        r = api.request("POST", f"{ARCHIVE_URL}/download", json={"docIds": batch})
        df = _read_archive_zip(r.content, set(points))
        df.to_parquet(part)
        frames.append(df)
        print(f"  {min(i + 1000, len(ids)):,} / {len(ids):,} files")
    df = pd.concat(frames, ignore_index=True)
    keep = (df["DeliveryDate"] >= f"{year}-01-01") & (df["DeliveryDate"] < end)
    return df[keep]


def interval_start(df: pd.DataFrame) -> pd.Series:
    """
    ERCOT labels each 15-minute price by delivery date, hour ENDING (1-24)
    and interval (1-4). Convert to the interval's start time in Central time.

    DSTFlag marks the repeated 1 AM hour on the November "fall back" day:
    flagged rows are the second (standard time) 1 AM hour.
    """
    local = (df["DeliveryDate"]
             + pd.to_timedelta(df["DeliveryHour"] - 1, unit="h")
             + pd.to_timedelta((df["DeliveryInterval"] - 1) * 15, unit="min"))
    return local.dt.tz_localize(config.TIMEZONE, ambiguous=~df["DSTFlag"].to_numpy(),
                                nonexistent="NaT")


def download_year(year: int, points: list) -> pd.DataFrame:
    """15-minute prices for one year, long format, query + archive combined."""
    api = ErcotSession()
    parts = []
    if pd.Timestamp(f"{year}-01-01") < QUERY_START:
        parts.append(_archive_prices(api, year, points))
    if pd.Timestamp(f"{year}-12-31") >= QUERY_START:
        start = max(pd.Timestamp(f"{year}-01-01"), QUERY_START).strftime("%Y-%m-%d")
        for p in points:
            parts.append(_query_point(api, p, start, f"{year}-12-31"))
    df = pd.concat(parts, ignore_index=True)
    df["Interval Start"] = interval_start(df)
    return (df.dropna(subset=["Interval Start"])
              .drop_duplicates(["SettlementPointName", "Interval Start"])
              .rename(columns={"SettlementPointName": "point", "SettlementPointPrice": "SPP"})
              [["Interval Start", "point", "SPP"]])
