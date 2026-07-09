SCHEMA_MAP = {
    "scheme_master": {
        "table": "altstreet_scheme_master",
        "columns": {
            "scheme_id": "scheme_id", "scheme_name": "scheme_name",
            "amfi_code": "amfi_code", "isin": "isin", "amc": "amc",
            "category": "category", "sub_category": "sub_category",
            "aum": "aum", "launch_date": "launch_date", "status": "status",
        },
    },
    "company_master": {
        "table": "company_master",
        "columns": {
            "company_id": "company_id", "company_name": "company_name",
            "isin": "isin", "sector": "sector", "market_cap_category": "market_cap_category",
        },
    },
    "scheme_holdings": {
        "table": "altstreet_scheme_holdings",
        "columns": {
            "scheme_id": "scheme_id", "company_id": "company_id",
            "company_name": "company_name", "weight": "weight",
            "quantity": "quantity", "market_value": "market_value",
        },
    },
    "market_cap_allocation": {
        "table": "altstreet_market_cap_allocation",
        "columns": {
            "scheme_id": "scheme_id", "large_cap_pct": "large_cap_pct",
            "mid_cap_pct": "mid_cap_pct", "small_cap_pct": "small_cap_pct",
        },
    },
}


def get_table(name: str) -> str:
    return SCHEMA_MAP[name]["table"]


def col(table: str, column: str) -> str:
    return SCHEMA_MAP[table]["columns"][column]
