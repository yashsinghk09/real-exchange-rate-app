# Real Exchange Rate Calculator

A Streamlit app that downloads monthly CPI and exchange-rate data from the IMF SDMX 3.0 API and computes the bilateral real exchange rate between any two IMF economies or the Euro area, from January 1976 where data exist.

## What it calculates

| Symbol | Definition |
|---|---|
| E_i(t) | IMF exchange rate: units of country *i*'s currency per 1 USD (period average) |
| S(t) | Units of Country 2 currency per 1 unit of Country 1 currency = E2(t) / E1(t) |
| P1(t), P2(t) | Monthly CPI of Country 1 and Country 2 |
| RER(t) | S(t) × P1(t) / P2(t) |
| RER* | Average of RER(t) over valid months in the selected sample |
| Real Index(t) | 100 × RER(t) / RER* |

A month is **valid** only when E1, E2, P1 and P2 are all present and positive. RER* is recalculated every time the sample start or end month changes. The nominal rate S(t) is plotted in actual currency units and is never normalized.

A real index above 100 means Country 1's currency is stronger in real terms against Country 2's than its average over the sample.

## Features

- Choose Country 1 and Country 2 from IMF member economies and the Euro area (`G163`).
- Pick the sample with a start/end month slider.
- Show the Real index, Nominal S(t), or Both (Both uses separate left and right y-axes). An optional log scale is available for the nominal series, which helps with high-inflation currencies.
- Download a CSV of every month in the selected sample with all inputs and calculations: `month, country1, country2, E1_<cur>_per_USD, E2_<cur>_per_USD, S_<cur2>_per_<cur1>, P1_CPI, P2_CPI, RER, valid_month, RER_star, Real_Index`.
- A data coverage table shows the first and last observation of each series.

## Data source

Base URL: `https://api.imf.org/external/sdmx/3.0`

| Series | Dataflow | Key |
|---|---|---|
| CPI (all items, index) | `CPI` | `{ISO3}.CPI._T.IX.M` |
| Exchange rate (national currency per USD, period average) | `ER` | `{ISO3}.XDC_USD.PA_RT.M` |

Requests take the form `{BASE_URL}/data/dataflow/IMF.STA/{dataflow}/+/{key}`. The app asks for SDMX-JSON first and falls back to SDMX-ML (XML) and SDMX-CSV if needed. For the United States, E(t) is set to 1. For the Euro area, if no CPI series exists under `G163.CPI._T.IX.M`, the app tries `G163.HICP._T.IX.M` and tells you when it does.

Downloads are cached for 12 hours. Use **Refresh IMF data** in the sidebar to fetch them again. Network errors are not cached, so a failed request is retried on the next interaction.

## Repository layout

```
app.py            Streamlit application
requirements.txt  Python dependencies
README.md         This file
```

## Run locally (Python 3.12)

```bash
python3.12 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Deploy on Streamlit Community Cloud

1. Push `app.py`, `requirements.txt` and `README.md` to a GitHub repository.
2. Go to [share.streamlit.io](https://share.streamlit.io), choose **Create app**, and select the repository, branch and `app.py` as the main file.
3. Under **Advanced settings**, choose Python **3.12**.
4. Deploy.

### Optional API key

The public IMF endpoints do not normally need a key. If the IMF later requires one, or you have a subscription key from the IMF API portal, add it under **App settings → Secrets**:

```toml
IMF_API_KEY = "your-key"
```

Locally you can put the same line in `.streamlit/secrets.toml` or set an `IMF_API_KEY` environment variable. The app sends it as the `Ocp-Apim-Subscription-Key` header.

## Data caveats

- **Gaps and coverage.** Many economies have CPI or exchange-rate data starting well after 1976, or with missing months. The slider is limited to the span of valid months; missing months inside the window are excluded from RER* and appear as gaps in the charts.
- **Euro area.** The `G163` exchange rate starts in 1999, so Euro area pairs begin then at the earliest.
- **Euro area members and redenominations.** Individual euro members' exchange rates before euro adoption, and currencies that were redenominated (for example Türkiye, Venezuela, Zimbabwe), may be expressed in old or converted units. Currency codes in the app are today's codes and are used for labels only. Inspect the nominal series around changeover dates.
- **CPI base years** differ across countries, so the level of RER(t) is not meaningful by itself; use the Real index and its changes.
- **Dataflow changes.** If the IMF renames a dataflow, key structure or country code, update the constants near the top of `app.py` (`CPI_KEY`, `FX_KEY`, `AGENCIES`, `COUNTRY_LIST`).

## Disclaimer

Data © International Monetary Fund. This tool is for analysis and education and is not financial advice.
