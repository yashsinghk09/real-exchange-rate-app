"""
Real Exchange Rate Calculator
=============================

Streamlit app that retrieves monthly CPI and exchange-rate data from the IMF
SDMX 3.0 API and computes the bilateral real exchange rate between two
economies.

Definitions
-----------
E_i(t) : IMF exchange rate, units of country i's currency per 1 USD (period average)
S(t)   : units of Country 2 currency per 1 unit of Country 1 currency = E2(t) / E1(t)
P_i(t) : monthly CPI of country i
RER(t) : S(t) * P1(t) / P2(t)
RER*   : mean of RER(t) over valid months in the selected sample
Real Index(t) = 100 * RER(t) / RER*
"""

from __future__ import annotations

import io
import os
import re
import xml.etree.ElementTree as ET

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
from plotly.subplots import make_subplots

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
BASE_URL = "https://api.imf.org/external/sdmx/3.0"
AGENCIES = ("IMF.STA", "*")          # try the IMF Statistics Dept first, then any agency
CPI_DATAFLOW = "CPI"
FX_DATAFLOW = "ER"
CPI_KEY = "{iso3}.CPI._T.IX.M"
CPI_KEY_HICP = "{iso3}.HICP._T.IX.M"  # fallback used only for the Euro area
FX_KEY = "{iso3}.XDC_USD.PA_RT.M"
EURO_AREA = "G163"
SAMPLE_START = pd.Timestamp("1976-01-01")
CACHE_TTL_SECONDS = 60 * 60 * 12
REQUEST_TIMEOUT = 45

ACCEPT_JSON = "application/vnd.sdmx.data+json;version=2.0.0"
ACCEPT_XML = "application/vnd.sdmx.data+xml;version=3.0.0"
ACCEPT_CSV = "application/vnd.sdmx.data+csv;version=2.0.0"

# Each attempt is (Accept header, query parameters). Later attempts are fallbacks
# in case the server rejects a format or parameter.
REQUEST_ATTEMPTS = [
    (ACCEPT_JSON, {"dimensionAtObservation": "TIME_PERIOD", "attributes": "none", "measures": "all"}),
    (ACCEPT_JSON, {}),
    (ACCEPT_XML, {}),
    (ACCEPT_CSV, {}),
]

# IMF member countries (plus a few other economies the IMF reports on).
# (ISO3 code, display name, current currency code). Currency codes are used for
# labels only; IMF series are usually expressed in today's currency units.
COUNTRY_LIST: list[tuple[str, str, str]] = [
    ("G163", "Euro area", "EUR"),
    ("AFG", "Afghanistan", "AFN"), ("ALB", "Albania", "ALL"), ("DZA", "Algeria", "DZD"),
    ("AND", "Andorra", "EUR"), ("AGO", "Angola", "AOA"), ("ATG", "Antigua and Barbuda", "XCD"),
    ("ARG", "Argentina", "ARS"), ("ARM", "Armenia", "AMD"), ("ABW", "Aruba", "AWG"),
    ("AUS", "Australia", "AUD"), ("AUT", "Austria", "EUR"), ("AZE", "Azerbaijan", "AZN"),
    ("BHS", "Bahamas", "BSD"), ("BHR", "Bahrain", "BHD"), ("BGD", "Bangladesh", "BDT"),
    ("BRB", "Barbados", "BBD"), ("BLR", "Belarus", "BYN"), ("BEL", "Belgium", "EUR"),
    ("BLZ", "Belize", "BZD"), ("BEN", "Benin", "XOF"), ("BTN", "Bhutan", "BTN"),
    ("BOL", "Bolivia", "BOB"), ("BIH", "Bosnia and Herzegovina", "BAM"), ("BWA", "Botswana", "BWP"),
    ("BRA", "Brazil", "BRL"), ("BRN", "Brunei Darussalam", "BND"), ("BGR", "Bulgaria", "BGN"),
    ("BFA", "Burkina Faso", "XOF"), ("BDI", "Burundi", "BIF"), ("CPV", "Cabo Verde", "CVE"),
    ("KHM", "Cambodia", "KHR"), ("CMR", "Cameroon", "XAF"), ("CAN", "Canada", "CAD"),
    ("CAF", "Central African Republic", "XAF"), ("TCD", "Chad", "XAF"), ("CHL", "Chile", "CLP"),
    ("CHN", "China", "CNY"), ("COL", "Colombia", "COP"), ("COM", "Comoros", "KMF"),
    ("COD", "Congo, Democratic Republic of the", "CDF"), ("COG", "Congo, Republic of", "XAF"),
    ("CRI", "Costa Rica", "CRC"), ("CIV", "Côte d'Ivoire", "XOF"), ("HRV", "Croatia", "EUR"),
    ("CUW", "Curaçao", "XCG"), ("CYP", "Cyprus", "EUR"), ("CZE", "Czech Republic", "CZK"),
    ("DNK", "Denmark", "DKK"), ("DJI", "Djibouti", "DJF"), ("DMA", "Dominica", "XCD"),
    ("DOM", "Dominican Republic", "DOP"), ("ECU", "Ecuador", "USD"), ("EGY", "Egypt", "EGP"),
    ("SLV", "El Salvador", "USD"), ("GNQ", "Equatorial Guinea", "XAF"), ("ERI", "Eritrea", "ERN"),
    ("EST", "Estonia", "EUR"), ("SWZ", "Eswatini", "SZL"), ("ETH", "Ethiopia", "ETB"),
    ("FJI", "Fiji", "FJD"), ("FIN", "Finland", "EUR"), ("FRA", "France", "EUR"),
    ("GAB", "Gabon", "XAF"), ("GMB", "Gambia", "GMD"), ("GEO", "Georgia", "GEL"),
    ("DEU", "Germany", "EUR"), ("GHA", "Ghana", "GHS"), ("GRC", "Greece", "EUR"),
    ("GRD", "Grenada", "XCD"), ("GTM", "Guatemala", "GTQ"), ("GIN", "Guinea", "GNF"),
    ("GNB", "Guinea-Bissau", "XOF"), ("GUY", "Guyana", "GYD"), ("HTI", "Haiti", "HTG"),
    ("HND", "Honduras", "HNL"), ("HKG", "Hong Kong SAR", "HKD"), ("HUN", "Hungary", "HUF"),
    ("ISL", "Iceland", "ISK"), ("IND", "India", "INR"), ("IDN", "Indonesia", "IDR"),
    ("IRN", "Iran", "IRR"), ("IRQ", "Iraq", "IQD"), ("IRL", "Ireland", "EUR"),
    ("ISR", "Israel", "ILS"), ("ITA", "Italy", "EUR"), ("JAM", "Jamaica", "JMD"),
    ("JPN", "Japan", "JPY"), ("JOR", "Jordan", "JOD"), ("KAZ", "Kazakhstan", "KZT"),
    ("KEN", "Kenya", "KES"), ("KIR", "Kiribati", "AUD"), ("KOR", "Korea", "KRW"),
    ("XKX", "Kosovo", "EUR"), ("KWT", "Kuwait", "KWD"), ("KGZ", "Kyrgyz Republic", "KGS"),
    ("LAO", "Lao P.D.R.", "LAK"), ("LVA", "Latvia", "EUR"), ("LBN", "Lebanon", "LBP"),
    ("LSO", "Lesotho", "LSL"), ("LBR", "Liberia", "LRD"), ("LBY", "Libya", "LYD"),
    ("LIE", "Liechtenstein", "CHF"), ("LTU", "Lithuania", "EUR"), ("LUX", "Luxembourg", "EUR"),
    ("MAC", "Macao SAR", "MOP"), ("MDG", "Madagascar", "MGA"), ("MWI", "Malawi", "MWK"),
    ("MYS", "Malaysia", "MYR"), ("MDV", "Maldives", "MVR"), ("MLI", "Mali", "XOF"),
    ("MLT", "Malta", "EUR"), ("MHL", "Marshall Islands", "USD"), ("MRT", "Mauritania", "MRU"),
    ("MUS", "Mauritius", "MUR"), ("MEX", "Mexico", "MXN"), ("FSM", "Micronesia", "USD"),
    ("MDA", "Moldova", "MDL"), ("MNG", "Mongolia", "MNT"), ("MNE", "Montenegro", "EUR"),
    ("MAR", "Morocco", "MAD"), ("MOZ", "Mozambique", "MZN"), ("MMR", "Myanmar", "MMK"),
    ("NAM", "Namibia", "NAD"), ("NRU", "Nauru", "AUD"), ("NPL", "Nepal", "NPR"),
    ("NLD", "Netherlands", "EUR"), ("NZL", "New Zealand", "NZD"), ("NIC", "Nicaragua", "NIO"),
    ("NER", "Niger", "XOF"), ("NGA", "Nigeria", "NGN"), ("MKD", "North Macedonia", "MKD"),
    ("NOR", "Norway", "NOK"), ("OMN", "Oman", "OMR"), ("PAK", "Pakistan", "PKR"),
    ("PLW", "Palau", "USD"), ("PAN", "Panama", "PAB"), ("PNG", "Papua New Guinea", "PGK"),
    ("PRY", "Paraguay", "PYG"), ("PER", "Peru", "PEN"), ("PHL", "Philippines", "PHP"),
    ("POL", "Poland", "PLN"), ("PRT", "Portugal", "EUR"), ("QAT", "Qatar", "QAR"),
    ("ROU", "Romania", "RON"), ("RUS", "Russia", "RUB"), ("RWA", "Rwanda", "RWF"),
    ("WSM", "Samoa", "WST"), ("SMR", "San Marino", "EUR"), ("STP", "São Tomé and Príncipe", "STN"),
    ("SAU", "Saudi Arabia", "SAR"), ("SEN", "Senegal", "XOF"), ("SRB", "Serbia", "RSD"),
    ("SYC", "Seychelles", "SCR"), ("SLE", "Sierra Leone", "SLE"), ("SGP", "Singapore", "SGD"),
    ("SVK", "Slovak Republic", "EUR"), ("SVN", "Slovenia", "EUR"), ("SLB", "Solomon Islands", "SBD"),
    ("SOM", "Somalia", "SOS"), ("ZAF", "South Africa", "ZAR"), ("SSD", "South Sudan", "SSP"),
    ("ESP", "Spain", "EUR"), ("LKA", "Sri Lanka", "LKR"), ("KNA", "St. Kitts and Nevis", "XCD"),
    ("LCA", "St. Lucia", "XCD"), ("VCT", "St. Vincent and the Grenadines", "XCD"),
    ("SDN", "Sudan", "SDG"), ("SUR", "Suriname", "SRD"), ("SWE", "Sweden", "SEK"),
    ("CHE", "Switzerland", "CHF"), ("SYR", "Syria", "SYP"), ("TJK", "Tajikistan", "TJS"),
    ("TZA", "Tanzania", "TZS"), ("THA", "Thailand", "THB"), ("TLS", "Timor-Leste", "USD"),
    ("TGO", "Togo", "XOF"), ("TON", "Tonga", "TOP"), ("TTO", "Trinidad and Tobago", "TTD"),
    ("TUN", "Tunisia", "TND"), ("TUR", "Türkiye", "TRY"), ("TKM", "Turkmenistan", "TMT"),
    ("TUV", "Tuvalu", "AUD"), ("UGA", "Uganda", "UGX"), ("UKR", "Ukraine", "UAH"),
    ("ARE", "United Arab Emirates", "AED"), ("GBR", "United Kingdom", "GBP"),
    ("USA", "United States", "USD"), ("URY", "Uruguay", "UYU"), ("UZB", "Uzbekistan", "UZS"),
    ("VUT", "Vanuatu", "VUV"), ("VEN", "Venezuela", "VES"), ("VNM", "Vietnam", "VND"),
    ("PSE", "West Bank and Gaza", "ILS"), ("YEM", "Yemen", "YER"), ("ZMB", "Zambia", "ZMW"),
    ("ZWE", "Zimbabwe", "ZWG"),
]
COUNTRIES = {code: (name, cur) for code, name, cur in COUNTRY_LIST}
# Euro area first, then alphabetical by name.
COUNTRY_CODES = [EURO_AREA] + sorted(
    (c for c in COUNTRIES if c != EURO_AREA), key=lambda c: COUNTRIES[c][0]
)


class IMFDataError(Exception):
    """Raised when the IMF API cannot be reached or returns unusable data."""


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
_PERIOD_RE = re.compile(r"^(\d{4})-?M?(\d{1,2})$", re.IGNORECASE)


def parse_period(value) -> pd.Timestamp:
    """Convert IMF period strings ('2020-M01', '2020M01', '2020-01') to month start."""
    text = str(value).strip()
    match = _PERIOD_RE.match(text)
    if match:
        year, month = int(match.group(1)), int(match.group(2))
        if 1 <= month <= 12:
            return pd.Timestamp(year=year, month=month, day=1)
        return pd.NaT
    try:
        return pd.Timestamp(text).to_period("M").to_timestamp()
    except (ValueError, TypeError):
        return pd.NaT


def _to_float(value) -> float | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _finalize(observations: dict) -> pd.Series:
    if not observations:
        return pd.Series(dtype=float)
    series = pd.Series(observations, dtype=float).sort_index()
    series = series[~series.index.duplicated(keep="first")]
    return series.replace([np.inf, -np.inf], np.nan).dropna()


def _parse_sdmx_json(payload: dict) -> pd.Series:
    """Parse SDMX-JSON (2.0 or 1.0) into a date-indexed Series."""
    data = payload.get("data", payload)
    structures = data.get("structures")
    if not structures and "structure" in data:
        structures = [data["structure"]]
    datasets = data.get("dataSets") or []
    if not structures or not datasets:
        return pd.Series(dtype=float)

    observations: dict = {}
    for dataset in datasets:
        struct_idx = dataset.get("structure", 0)
        if not isinstance(struct_idx, int) or struct_idx >= len(structures):
            struct_idx = 0
        obs_dims = structures[struct_idx].get("dimensions", {}).get("observation", [])
        time_pos, time_values = None, None
        for pos, dim in enumerate(obs_dims):
            if dim.get("id") == "TIME_PERIOD":
                time_pos, time_values = pos, dim.get("values", [])
                break
        if time_values is None and obs_dims:
            time_pos, time_values = 0, obs_dims[0].get("values", [])
        if time_values is None:
            continue

        if dataset.get("series"):
            groups = [s.get("observations", {}) for s in dataset["series"].values()]
        else:
            groups = [dataset.get("observations", {})]

        for group in groups:
            for obs_key, obs_val in group.items():
                try:
                    idx = int(str(obs_key).split(":")[time_pos])
                    tv = time_values[idx]
                except (ValueError, IndexError):
                    continue
                if isinstance(tv, dict):
                    period = tv.get("id") or tv.get("value") or tv.get("name")
                else:
                    period = tv
                when = parse_period(period)
                number = _to_float(obs_val)
                if pd.notna(when) and number is not None:
                    observations.setdefault(when, number)
    return _finalize(observations)


def _parse_sdmx_xml(content: bytes) -> pd.Series:
    """Parse SDMX-ML (structure-specific or generic) into a date-indexed Series."""
    root = ET.fromstring(content)
    observations: dict = {}
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "Obs":
            continue
        period = element.attrib.get("TIME_PERIOD")
        value = element.attrib.get("OBS_VALUE")
        if period is None or value is None:  # generic message layout
            for child in element:
                tag = child.tag.rsplit("}", 1)[-1]
                child_id = child.attrib.get("id")
                if tag == "ObsDimension" or (tag == "Value" and child_id == "TIME_PERIOD"):
                    period = child.attrib.get("value", period)
                elif tag == "ObsValue" or (tag == "Value" and child_id == "OBS_VALUE"):
                    value = child.attrib.get("value", value)
        when = parse_period(period) if period is not None else pd.NaT
        number = _to_float(value)
        if pd.notna(when) and number is not None:
            observations.setdefault(when, number)
    return _finalize(observations)


def _parse_sdmx_csv(text: str) -> pd.Series:
    frame = pd.read_csv(io.StringIO(text))
    cols = {c.upper(): c for c in frame.columns}
    if "TIME_PERIOD" not in cols or "OBS_VALUE" not in cols:
        raise ValueError("CSV response lacks TIME_PERIOD/OBS_VALUE columns")
    observations: dict = {}
    for period, value in zip(frame[cols["TIME_PERIOD"]], frame[cols["OBS_VALUE"]]):
        when = parse_period(period)
        number = _to_float(value)
        if pd.notna(when) and number is not None:
            observations.setdefault(when, number)
    return _finalize(observations)


def _parse_response(response: requests.Response) -> pd.Series:
    content_type = response.headers.get("Content-Type", "").lower()
    head = response.text[:2000].lstrip()
    if "json" in content_type or head.startswith("{"):
        return _parse_sdmx_json(response.json())
    if "xml" in content_type or head.startswith("<"):
        return _parse_sdmx_xml(response.content)
    if "csv" in content_type or "TIME_PERIOD" in head:
        return _parse_sdmx_csv(response.text)
    raise ValueError(f"unrecognised content type '{content_type}'")


# --------------------------------------------------------------------------- #
# IMF API access
# --------------------------------------------------------------------------- #
def _api_key() -> str | None:
    """Optional subscription key from Streamlit secrets or the environment."""
    try:
        key = st.secrets.get("IMF_API_KEY")
    except Exception:  # no secrets file configured
        key = None
    return key or os.environ.get("IMF_API_KEY")


def _headers(accept: str) -> dict:
    headers = {"Accept": accept, "User-Agent": "real-exchange-rate-app/1.0 (Streamlit)"}
    key = _api_key()
    if key:
        headers["Ocp-Apim-Subscription-Key"] = key
    return headers


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def fetch_imf_series(dataflow: str, key: str) -> pd.Series:
    """
    Fetch one monthly series from the IMF SDMX 3.0 API.

    Returns an empty Series when the IMF reports no data for the key (this
    result is cached). Raises IMFDataError on network/server problems so the
    failure is not cached and the next run retries.
    """
    problems: list[str] = []
    no_data = False
    for agency in AGENCIES:
        url = f"{BASE_URL}/data/dataflow/{agency}/{dataflow}/+/{key}"
        for accept, params in REQUEST_ATTEMPTS:
            try:
                response = requests.get(
                    url, params=params, headers=_headers(accept), timeout=REQUEST_TIMEOUT
                )
            except requests.RequestException as exc:
                problems.append(f"{agency}: {type(exc).__name__}")
                continue
            if response.status_code == 404:
                no_data = True
                problems.append(f"{agency}: no data (404)")
                break
            if not response.ok:
                problems.append(f"{agency}: HTTP {response.status_code}")
                continue
            try:
                series = _parse_response(response)
            except Exception as exc:  # malformed or unexpected payload
                problems.append(f"{agency}: could not parse response ({exc})")
                continue
            if series.empty:
                no_data = True
                problems.append(f"{agency}: response had no observations")
                break
            return series.loc[series.index >= SAMPLE_START].rename(key)
    if no_data:
        return pd.Series(dtype=float, name=key)
    raise IMFDataError(f"{dataflow} / {key}: " + "; ".join(problems[-6:]))


def monthly_index() -> pd.DatetimeIndex:
    end = pd.Timestamp.today().to_period("M").to_timestamp()
    return pd.date_range(SAMPLE_START, end, freq="MS")


def load_country(iso3: str) -> dict:
    """Return CPI and exchange-rate series (LCU per USD) for one economy."""
    notes: list[str] = []
    cpi = fetch_imf_series(CPI_DATAFLOW, CPI_KEY.format(iso3=iso3))
    if cpi.empty and iso3 == EURO_AREA:
        cpi = fetch_imf_series(CPI_DATAFLOW, CPI_KEY_HICP.format(iso3=iso3))
        if not cpi.empty:
            notes.append("Euro area CPI not found under the CPI index type; HICP was used instead.")
    if iso3 == "USA":
        # USD per USD is 1 by definition.
        fx = pd.Series(1.0, index=monthly_index(), name="USD per USD")
    else:
        fx = fetch_imf_series(FX_DATAFLOW, FX_KEY.format(iso3=iso3))
    return {"cpi": cpi, "fx": fx, "notes": notes}


# --------------------------------------------------------------------------- #
# Calculations
# --------------------------------------------------------------------------- #
def build_frame(c1: dict, c2: dict) -> pd.DataFrame:
    idx = monthly_index()
    df = pd.DataFrame(
        {
            "E1": c1["fx"].reindex(idx),
            "E2": c2["fx"].reindex(idx),
            "P1": c1["cpi"].reindex(idx),
            "P2": c2["cpi"].reindex(idx),
        },
        index=idx,
    )
    fx_ok = (df["E1"] > 0) & (df["E2"] > 0)
    df["S"] = np.where(fx_ok, df["E2"] / df["E1"], np.nan)  # Country 2 currency per 1 Country 1
    inputs = df[["E1", "E2", "P1", "P2"]]
    df["valid"] = np.isfinite(inputs).all(axis=1) & (inputs > 0).all(axis=1)
    df["RER"] = np.where(df["valid"], df["S"] * df["P1"] / df["P2"], np.nan)
    return df


def coverage(series: pd.Series) -> dict:
    s = series.dropna()
    if s.empty:
        return {"First": "—", "Last": "—", "Months": 0}
    return {"First": s.index.min().strftime("%Y-%m"), "Last": s.index.max().strftime("%Y-%m"), "Months": int(s.size)}


# --------------------------------------------------------------------------- #
# Charts
# --------------------------------------------------------------------------- #
REAL_COLOR = "#1f5fa8"
NOMINAL_COLOR = "#c2410c"


def make_chart(sample: pd.DataFrame, view: str, s_label: str, log_nominal: bool) -> go.Figure:
    real_trace = go.Scatter(
        x=sample.index, y=sample["Real_Index"], name="Real index (sample average = 100)",
        mode="lines", line=dict(color=REAL_COLOR, width=2), connectgaps=False,
        hovertemplate="Real index: %{y:.2f}<extra></extra>",
    )
    base_trace = go.Scatter(
        x=[sample.index.min(), sample.index.max()], y=[100, 100], name="RER* (= 100)",
        mode="lines", line=dict(color="gray", width=1, dash="dot"), hoverinfo="skip",
    )
    nominal_trace = go.Scatter(
        x=sample.index, y=sample["S"], name=f"Nominal S(t), {s_label}",
        mode="lines", line=dict(color=NOMINAL_COLOR, width=2), connectgaps=False,
        hovertemplate="S: %{y:,.6g}<extra></extra>",
    )
    nominal_axis_type = "log" if log_nominal else "linear"

    if view == "Real":
        fig = go.Figure([real_trace, base_trace])
        fig.update_yaxes(title_text="Real index (RER* = 100)")
    elif view == "Nominal":
        fig = go.Figure([nominal_trace])
        fig.update_yaxes(title_text=s_label, type=nominal_axis_type)
    else:
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(real_trace, secondary_y=False)
        fig.add_trace(base_trace, secondary_y=False)
        fig.add_trace(nominal_trace, secondary_y=True)
        fig.update_yaxes(title_text="Real index (RER* = 100)", title_font=dict(color=REAL_COLOR),
                         tickfont=dict(color=REAL_COLOR), secondary_y=False)
        fig.update_yaxes(title_text=f"Nominal S(t), {s_label}", title_font=dict(color=NOMINAL_COLOR),
                         tickfont=dict(color=NOMINAL_COLOR), type=nominal_axis_type,
                         showgrid=False, secondary_y=True)

    fig.update_layout(
        height=520, hovermode="x unified", margin=dict(l=10, r=10, t=40, b=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
    )
    fig.update_xaxes(hoverformat="%Y-%m")
    return fig


# --------------------------------------------------------------------------- #
# User interface
# --------------------------------------------------------------------------- #
def label(code: str) -> str:
    return f"{COUNTRIES[code][0]} ({code})"


def main() -> None:
    st.set_page_config(page_title="Real Exchange Rate Calculator", page_icon="💱", layout="wide")
    st.title("Real exchange rate calculator")
    st.caption(
        "Monthly IMF CPI and exchange-rate data from January 1976 where available. "
        "RER(t) = S(t) × P1(t) / P2(t), where S(t) is Country 2 currency per 1 unit of Country 1 currency."
    )

    with st.sidebar:
        st.header("Countries")
        c1 = st.selectbox("Country 1", COUNTRY_CODES, index=COUNTRY_CODES.index("USA"), format_func=label)
        c2 = st.selectbox("Country 2", COUNTRY_CODES, index=COUNTRY_CODES.index(EURO_AREA), format_func=label)
        st.divider()
        if st.button("Refresh IMF data"):
            st.cache_data.clear()
            st.rerun()
        st.caption("Data is cached for 12 hours. Refresh to download it again.")

    if c1 == c2:
        st.warning("Choose two different economies to calculate a real exchange rate.")
        st.stop()

    name1, cur1 = COUNTRIES[c1]
    name2, cur2 = COUNTRIES[c2]

    try:
        with st.spinner(f"Downloading IMF data for {name1} and {name2}…"):
            d1 = load_country(c1)
            d2 = load_country(c2)
    except IMFDataError as exc:
        st.error(
            "The IMF API did not return usable data. Check your connection or try "
            f"**Refresh IMF data** in a few minutes.\n\nDetails: {exc}"
        )
        st.stop()

    for note in d1["notes"] + d2["notes"]:
        st.info(note)

    df = build_frame(d1, d2)

    cov = pd.DataFrame(
        {
            f"Exchange rate, {name1} ({cur1} per USD)": coverage(d1["fx"]),
            f"Exchange rate, {name2} ({cur2} per USD)": coverage(d2["fx"]),
            f"CPI, {name1}": coverage(d1["cpi"]),
            f"CPI, {name2}": coverage(d2["cpi"]),
            "Valid months (all four inputs present)": coverage(df.loc[df["valid"], "RER"]),
        }
    ).T

    valid_months = df.index[df["valid"]]
    if valid_months.empty:
        st.error(
            f"No month has all four inputs for {name1} and {name2}. "
            "See the data coverage below and try a different pair."
        )
        st.dataframe(cov)
        st.stop()

    # ---- Sample period ---------------------------------------------------- #
    options = list(pd.date_range(valid_months.min(), valid_months.max(), freq="MS"))
    start, end = st.select_slider(
        "Sample period (RER* is the average over valid months in this window)",
        options=options,
        value=(options[0], options[-1]),
        format_func=lambda t: t.strftime("%Y-%m"),
        key=f"sample_{c1}_{c2}",
    )

    sample = df.loc[start:end].copy()
    valid = sample["valid"]
    rer_star = float(sample.loc[valid, "RER"].mean()) if valid.any() else np.nan
    sample["RER_star"] = rer_star
    sample["Real_Index"] = 100.0 * sample["RER"] / rer_star

    if not valid.any():
        st.warning("The selected window contains no valid months. Widen the sample period.")
        st.stop()

    # ---- Summary ---------------------------------------------------------- #
    last_valid = sample.index[valid][-1]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("RER*", f"{rer_star:,.6g}")
    m2.metric("Valid months in sample", f"{int(valid.sum())} of {len(sample)}")
    m3.metric(f"Real index, {last_valid:%Y-%m}", f"{sample.at[last_valid, 'Real_Index']:.2f}")
    m4.metric(f"S(t), {last_valid:%Y-%m}", f"{sample.at[last_valid, 'S']:,.6g}")

    # ---- Chart ------------------------------------------------------------ #
    s_label = f"{cur2} per 1 {cur1}"
    col_a, col_b = st.columns([3, 1])
    view = col_a.radio("Show", ["Real", "Nominal", "Both"], index=2, horizontal=True)
    log_nominal = col_b.checkbox("Log scale for nominal", value=False, disabled=(view == "Real"))

    st.plotly_chart(make_chart(sample, view, s_label, log_nominal))
    st.caption(
        f"A real index above 100 means {name1}'s currency is stronger in real terms against {name2}'s "
        "than its average over the sample. Gaps in the lines are months with missing data."
    )

    # ---- Download --------------------------------------------------------- #
    export = pd.DataFrame(
        {
            "month": sample.index.strftime("%Y-%m"),
            "country1": label(c1),
            "country2": label(c2),
            f"E1_{cur1}_per_USD": sample["E1"].values,
            f"E2_{cur2}_per_USD": sample["E2"].values,
            f"S_{cur2}_per_{cur1}": sample["S"].values,
            "P1_CPI": sample["P1"].values,
            "P2_CPI": sample["P2"].values,
            "RER": sample["RER"].values,
            "valid_month": sample["valid"].values,
            "RER_star": rer_star,
            "Real_Index": sample["Real_Index"].values,
        }
    )
    st.download_button(
        "Download CSV",
        data=export.to_csv(index=False).encode("utf-8"),
        file_name=f"rer_{c1}_{c2}_{start:%Y%m}_{end:%Y%m}.csv",
        mime="text/csv",
    )

    # ---- Details ---------------------------------------------------------- #
    with st.expander("Data table"):
        st.dataframe(export, hide_index=True)

    with st.expander("Data coverage"):
        st.dataframe(cov)
        st.caption(
            "A month is valid only when both exchange rates and both CPIs are present and positive. "
            "Invalid months are excluded from RER* and shown as gaps."
        )

    with st.expander("Method and data sources"):
        st.markdown(
            f"""
- **Exchange rates:** IMF `ER` dataflow, key `{{ISO3}}.XDC_USD.PA_RT.M` (period-average national currency per USD).
  S(t) = E2(t) / E1(t) gives **{cur2} per 1 {cur1}**. For the United States, E(t) = 1.
- **Prices:** IMF `CPI` dataflow, key `{{ISO3}}.CPI._T.IX.M` (all-items CPI index). The Euro area uses code `G163`.
- **Real exchange rate:** RER(t) = S(t) × P1(t) / P2(t). RER* is the mean of RER(t) over valid months
  between {start:%Y-%m} and {end:%Y-%m}; Real Index(t) = 100 × RER(t) / RER*.
- CPI base years differ across countries, so the level of RER(t) has no direct meaning; only its movements and the
  normalized index are interpretable. S(t) is shown in actual currency units.
- Euro area members report national currencies before they adopted the euro, and many currencies were redenominated.
  Check the series around such dates before drawing conclusions.
"""
        )


if __name__ == "__main__":
    main()
