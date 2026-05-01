import datetime as dt
from email.message import EmailMessage
from pathlib import Path
import shutil
import smtplib
from urllib.parse import urljoin

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

COUNTY = "Bucks"
EMAIL_CREDENTIALS_FILE = "crimewatch_scraper_pwd.txt"
EMAIL_RECIPIENTS_FILE = "ujs_alert_recipients.txt"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# For today, keep this on so you can get the baseline email.
# Later, switch this to "new_only" so it emails only when a newly scraped
# inactive criminal complaint is added to the deduped master CSV.


# This keeps the alert focused on inactive criminal complaint rows, not every
# inactive criminal docket row. Set to False if UJS does not reliably put
# "complaint" in EventType for the rows Jo cares about.
#REQUIRE_COMPLAINT_EVENT_TYPE = True


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


def load_email_credentials(path=EMAIL_CREDENTIALS_FILE):
    cred_path = Path(path)

    if not cred_path.exists():
        raise FileNotFoundError(f"Missing email credentials file: {cred_path}")

    lines = [
        line.strip()
        for line in cred_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    values = {}
    for line in lines:
        if ":" in line:
            key, value = line.split(":", 1)
            values[key.strip().lower()] = value.strip()

    sender_email = values.get("email")
    sender_password = values.get("password")

    if not sender_email or not sender_password:
        raise ValueError(
            f"{cred_path} must contain lines like 'Email: ...' and 'Password: ...'"
        )

    return sender_email, sender_password


def load_email_recipients(path=EMAIL_RECIPIENTS_FILE):
    recipient_path = Path(path)

    if not recipient_path.exists():
        raise FileNotFoundError(
            f"Missing recipient file: {recipient_path}. Expected one recipient email per line."
        )

    recipients = [
        line.strip()
        for line in recipient_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    if not recipients:
        raise ValueError(f"{recipient_path} does not contain any recipient emails.")

    return recipients


def send_email_alert(subject, body, recipients):
    sender_email, sender_password = load_email_credentials()

    msg = EmailMessage()
    msg["From"] = sender_email
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)

    print(f"Sent email alert to: {', '.join(recipients)}")


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
    if "DocketNumber" not in df.columns:
        return df.iloc[0:0].copy()
    return df[df["DocketNumber"].astype(str).str.contains(r"-CR-", na=False)].copy()


def filter_inactive_criminal_complaints(df):
    if df.empty:
        return df.copy()

    if "DocketNumber" not in df.columns:
        return df.iloc[0:0].copy()

    searchable_text = df.fillna("").astype(str).agg(" ".join, axis=1)

    is_criminal = df["DocketNumber"].fillna("").astype(str).str.contains(
        r"-CR-",
        case=False,
        na=False,
    )

    is_inactive = searchable_text.str.contains(
        r"\bInactive\b",
        case=False,
        na=False,
    )

    return df[is_criminal & is_inactive].copy()

ALERT_LOG_FILE = "ujs_emailed_inactive_complaints_log.csv"

ALERT_ID_COLUMNS = [
    "DocketNumber",
    "ComplaintNumber",
    "IncidentNumber",
    "FilingDate",
]


def normalize_date_for_alert(value):
    if pd.isna(value):
        return ""

    text = str(value).strip()
    if not text:
        return ""

    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return text

    return parsed.strftime("%Y-%m-%d")


def make_alert_id(row):
    parts = []

    for col in ALERT_ID_COLUMNS:
        if col in row.index:
            value = str(row.get(col, "")).strip()
        else:
            value = ""

        if col == "FilingDate":
            value = normalize_date_for_alert(value)

        parts.append(value)

    return "|".join(parts)


def add_alert_ids(df):
    df = df.copy()

    if df.empty:
        df["AlertID"] = ""
        return df

    df["AlertID"] = df.apply(make_alert_id, axis=1)
    return df


def load_emailed_alert_log(path=ALERT_LOG_FILE):
    log_path = Path(path)

    if not log_path.exists() or log_path.stat().st_size == 0:
        return pd.DataFrame(columns=["AlertID", "EmailedAt"])

    try:
        log_df = pd.read_csv(log_path, dtype=str, keep_default_na=False).fillna("")
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=["AlertID", "EmailedAt"])

    if "AlertID" not in log_df.columns:
        log_df["AlertID"] = ""

    if "EmailedAt" not in log_df.columns:
        log_df["EmailedAt"] = ""

    return log_df


def append_emailed_alert_log(emailed_df, path=ALERT_LOG_FILE):
    if emailed_df.empty:
        return

    now = dt.datetime.now().isoformat(timespec="seconds")

    rows_to_log = emailed_df[["AlertID"]].copy()
    rows_to_log["EmailedAt"] = now

    existing_log = load_emailed_alert_log(path)

    combined_log = pd.concat([existing_log, rows_to_log], ignore_index=True)
    combined_log = combined_log.drop_duplicates(subset=["AlertID"], keep="first")

    log_path = Path(path)
    combined_log.to_csv(log_path, index=False)


def filter_filing_date_today(df):
    if df.empty:
        return df.copy()

    if "FilingDate" not in df.columns:
        return df.iloc[0:0].copy()

    today_string = dt.date.today().strftime("%Y-%m-%d")

    filing_dates = df["FilingDate"].fillna("").astype(str).apply(normalize_date_for_alert)

    return df[filing_dates == today_string].copy()


def get_today_unemailed_inactive_complaints(master_df):
    inactive_df = filter_inactive_criminal_complaints(master_df)
    today_inactive_df = filter_filing_date_today(inactive_df)
    today_inactive_df = add_alert_ids(today_inactive_df)

    if today_inactive_df.empty:
        return today_inactive_df

    emailed_log = load_emailed_alert_log()
    already_emailed = set(emailed_log["AlertID"].fillna("").astype(str))

    unemailed_df = today_inactive_df[
        ~today_inactive_df["AlertID"].fillna("").astype(str).isin(already_emailed)
    ].copy()

    return unemailed_df


def get_master_csv_path(county, criminal_only=True):
    county_slug = county.lower().replace(" ", "_")
    suffix = "criminal" if criminal_only else "all"
    return Path(f"ujs_{suffix}_{county_slug}.csv")


def prepare_dedupe_columns(df, dedupe_columns):
    df = df.copy()
    for col in dedupe_columns:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str).str.strip()
    return df


def make_row_key(df, key_columns):
    if df.empty:
        return pd.Series(dtype=str)
    return df[key_columns].fillna("").astype(str).agg("||".join, axis=1)


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

    master_df = result_df.copy()
    newly_added_df = result_df.copy()
    output_file = get_master_csv_path(county, criminal_only=criminal_only)

    if save_csv:
        dedupe_columns = [
            "DocketNumber",
            "ComplaintNumber",
            "IncidentNumber",
            "EventDate",
            "EventType",
        ]

        result_df = prepare_dedupe_columns(result_df, dedupe_columns)

        if output_file.exists():
            existing_df = pd.read_csv(output_file, dtype=str, keep_default_na=False).fillna("")
            existing_df = prepare_dedupe_columns(existing_df, dedupe_columns)

            existing_keys = set(make_row_key(existing_df, dedupe_columns))
            result_keys = make_row_key(result_df, dedupe_columns)
            newly_added_df = result_df[~result_keys.isin(existing_keys)].copy()

            combined_df = pd.concat([existing_df, result_df], ignore_index=True)
            combined_df = combined_df.drop_duplicates(subset=dedupe_columns, keep="first")
        else:
            combined_df = result_df.copy()
            newly_added_df = result_df.copy()

        combined_df.to_csv(output_file, index=False)

        docs_data_dir = Path("docs") / "data"
        docs_data_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output_file, docs_data_dir / output_file.name)

        master_df = combined_df
        print(f"Processed {len(result_df)} scraped rows")
        print(f"Added {len(newly_added_df)} new deduped rows to master file")
        print(f"Saved deduped master file: {output_file}")
        print(f"Master file now has {len(master_df)} rows")

    return result_df, newly_added_df, master_df, output_file


def default_dates():
    today = dt.date.today()
    yesterday = today - dt.timedelta(days=1)
    return yesterday.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def build_baseline_email_body(inactive_complaints, master_csv_path, filed_start, filed_end):
    count = len(inactive_complaints)

    lines = [
        "This is a test email from the Bucks UJS alert scraper.",
        "",
        f"Scrape date range checked: {filed_start} through {filed_end}",
        f"Master CSV checked: {master_csv_path}",
        f"Current inactive criminal complaint baseline count: {count}",
        "",
        "This baseline count comes from the deduped master CSV after today's scrape was merged in.",
    ]

    if count:
        lines.extend([
            "",
            "Most recent matching rows:",
        ])

        preview_columns = [
            "DocketNumber",
            "CaseCaption",
            "CaseStatus",
            "FilingDate",
            "EventType",
            "EventDate",
            "CourtOffice",
            "DocketSheetURL",
        ]
        available_columns = [col for col in preview_columns if col in inactive_complaints.columns]
        preview_df = inactive_complaints.tail(10)[available_columns]

        for _, row in preview_df.iterrows():
            lines.append("-")
            for col in available_columns:
                value = str(row.get(col, "")).strip()
                if value:
                    lines.append(f"  {col}: {value}")

    return "\n".join(lines)


def build_new_alert_email_body(new_inactive_complaints, master_csv_path, filed_start, filed_end):
    count = len(new_inactive_complaints)

    lines = [
        "New inactive criminal complaint alert from the Bucks UJS scraper.",
        "",
        f"Scrape date range checked: {filed_start} through {filed_end}",
        f"Master CSV updated: {master_csv_path}",
        f"Inactive criminal complaints filed today and not previously emailed: {count}",
        "",
        "Matching rows:",
    ]

    preview_columns = [
        "DocketNumber",
        "CaseCaption",
        "CaseStatus",
        "FilingDate",
        "EventType",
        "EventDate",
        "CourtOffice",
        "DocketSheetURL",
    ]
    available_columns = [col for col in preview_columns if col in new_inactive_complaints.columns]

    for _, row in new_inactive_complaints[available_columns].iterrows():
        lines.append("-")
        for col in available_columns:
            value = str(row.get(col, "")).strip()
            if value:
                lines.append(f"  {col}: {value}")

    return "\n".join(lines)


def main():
    filed_start, filed_end = default_dates()

    result_df, newly_added_df, master_df, master_csv_path = run_scrape(
        county=COUNTY,
        filed_start=filed_start,
        filed_end=filed_end,
        criminal_only=True,
        save_csv=True,
    )

    print(result_df.head())

    alerts_df = get_today_unemailed_inactive_complaints(master_df)

    if alerts_df.empty:
        print("No new unemailed inactive criminal complaints for today.")
        return

    recipients = load_email_recipients()

    subject = f"Bucks UJS alert: {len(alerts_df)} inactive criminal complaint(s) filed today"

    body = build_new_alert_email_body(
        new_inactive_complaints=alerts_df,
        master_csv_path=master_csv_path,
        filed_start=filed_start,
        filed_end=filed_end,
    )

    send_email_alert(subject, body, recipients)

    append_emailed_alert_log(alerts_df)

    print(f"Emailed {len(alerts_df)} new inactive criminal complaint alert(s).")


if __name__ == "__main__":
    main()
