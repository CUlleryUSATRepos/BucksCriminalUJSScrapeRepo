import datetime as dt
from urllib.parse import urljoin
from pathlib import Path
import shutil
import pandas as pd
import requests
from bs4 import BeautifulSoup


BASE_URL = "https://ujsportal.pacourts.us"
SEARCH_URL = f"{BASE_URL}/CaseSearch"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36"
)


def get_session_and_token():
    session = requests.Session()
    headers = {"User-Agent": USER_AGENT}

    r = session.get(SEARCH_URL, headers=headers, timeout=60)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    token_input = soup.find("input", {"name": "__RequestVerificationToken"})
    if not token_input:
        raise RuntimeError("Could not find __RequestVerificationToken on CaseSearch page")

    token = token_input.get("value")
    return session, token


def build_payload(county, filed_start, filed_end, token):
    return {
        "SearchBy": "DateFiled",
        "AdvanceSearch": "true",
        "ParticipantSID": "",
        "ParticipantSSN": "",
        "FiledStartDate": filed_start,
        "FiledEndDate": filed_end,
        "County": county,
        "JudicialDistrict": "",
        "MDJSCourtOffice": "",
        "DocketType": "",
        "CaseCategory": "",
        "CaseStatus": "",
        "DriversLicenseState": "",
        "PADriversLicenseNumber": "",
        "ArrestingAgency": "",
        "ORI": "",
        "JudgeNameID": "",
        "AppellateCourtName": "",
        "AppellateDistrict": "",
        "AppellateDocketType": "",
        "AppellateCaseCategory": "",
        "AppellateCaseType": "",
        "AppellateAgency": "",
        "AppellateTrialCourt": "",
        "AppellateTrialCourtJudge": "",
        "AppellateCaseStatus": "",
        "ParticipantRole": "",
        "ParcelState": "",
        "ParcelCounty": "",
        "ParcelMunicipality": "",
        "CourtOffice": "",
        "CourtRoomID": "",
        "CalendarEventStartDate": "",
        "CalendarEventEndDate": "",
        "CalendarEventType": "",
        "__RequestVerificationToken": token,
    }


def fetch_search_results(session, payload):
    post_headers = {
        "User-Agent": USER_AGENT,
        "Origin": BASE_URL,
        "Referer": SEARCH_URL,
        "Content-Type": "application/x-www-form-urlencoded",
    }

    resp = session.post(SEARCH_URL, headers=post_headers, data=payload, timeout=120)
    resp.raise_for_status()
    return resp.text


def parse_results_table(html):
    soup = BeautifulSoup(html, "html.parser")
    grid = soup.find(id="caseSearchResultGrid")
    if not grid:
        raise RuntimeError("Could not find caseSearchResultGrid in response HTML")

    rows = grid.select("tbody tr")

    col_names = [
        "HiddenIndex",
        "HiddenUnknown",
        "DocketNumber",
        "CourtType",
        "CaseCaption",
        "CaseStatus",
        "FilingDate",
        "PrimaryParticipants",
        "DOBs",
        "County",
        "CourtOffice",
        "OTN",
        "ComplaintNumber",
        "IncidentNumber",
        "EventType",
        "EventStatus",
        "EventDate",
        "EventLocation",
        "IconsText",
    ]

    normalized_rows = []
    max_cols = len(col_names)

    for tr in rows:
        tds = tr.find_all("td")
        texts = [td.get_text(" ", strip=True) for td in tds]

        docket_sheet_url = ""
        court_summary_url = ""

        for a in tr.find_all("a", href=True):
            href = urljoin(BASE_URL, a["href"])
            aria = (a.get("aria-label") or "").strip().lower()
            href_lower = href.lower()

            if "docket sheet" in aria or "docketsheet" in href_lower:
                docket_sheet_url = href
            elif "court summary" in aria or "courtsummary" in href_lower:
                court_summary_url = href

        if len(texts) < max_cols:
            texts += [""] * (max_cols - len(texts))
        elif len(texts) > max_cols:
            texts = texts[:max_cols]

        row_dict = dict(zip(col_names, texts))
        row_dict["DocketSheetURL"] = docket_sheet_url
        row_dict["CourtSummaryURL"] = court_summary_url
        normalized_rows.append(row_dict)

    return pd.DataFrame(normalized_rows)


def filter_criminal(df):
    return df[df["DocketNumber"].str.contains(r"-CR-", na=False)].copy()


def run_scrape(county, filed_start, filed_end, criminal_only=True, save_csv=True):
    session, token = get_session_and_token()
    payload = build_payload(
        county=county,
        filed_start=filed_start,
        filed_end=filed_end,
        token=token,
    )

    html = fetch_search_results(session, payload)
    df = parse_results_table(html)

    if criminal_only:
        result_df = filter_criminal(df)
    else:
        result_df = df.copy()

    if save_csv:
        import os

        county_slug = county.lower().replace(" ", "_")
        suffix = "criminal" if criminal_only else "all"
        output_file = f"ujs_{suffix}_{county_slug}.csv"

        dedupe_columns = [
            "DocketNumber",
            "ComplaintNumber",
            "IncidentNumber",
            "EventDate",
            "EventType"
        ]
        result_df = result_df.copy()

        for col in dedupe_columns:
            if col not in result_df.columns:
                result_df[col] = ""
            result_df[col] = result_df[col].fillna("").astype(str).str.strip()

        if os.path.exists(output_file):
            existing_df = pd.read_csv(output_file, dtype=str, keep_default_na=False).fillna("")
            for col in dedupe_columns:
                if col not in existing_df.columns:
                    existing_df[col] = ""
                existing_df[col] = existing_df[col].fillna("").astype(str).str.strip()
            combined_df = pd.concat([existing_df, result_df], ignore_index=True)
            combined_df = combined_df.drop_duplicates(subset=dedupe_columns, keep="first")
        else:
            combined_df = result_df.copy()
        combined_df.to_csv(output_file, index=False)
        docs_data_dir = Path("docs") / "data"
        docs_data_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output_file, docs_data_dir / output_file)
        new_rows = len(result_df)
        total_rows = len(combined_df)
        print(f"Processed {new_rows} scraped rows")
        print(f"Saved deduped master file: {output_file}")
        print(f"Master File now has {total_rows} rows")

    return result_df


def default_dates():
    today = dt.date.today()
    yesterday = today - dt.timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def main():
    filed_start, filed_end = default_dates()
    df = run_scrape(
        county="Bucks",
        filed_start=filed_start,
        filed_end=filed_end,
        criminal_only=True,
        save_csv=True,
    )
    print(df.head())


if __name__ == "__main__":
    main()