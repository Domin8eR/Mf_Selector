AMC_CODE_TO_NAME: dict[str, str] = {
    "400001": "Baroda BNP Paribas MF", "400004": "Aditya Birla Sun Life MF",
    "400006": "Canara Robeco MF", "400009": "DSP MF", "400010": "Quant MF",
    "400012": "Franklin Templeton MF", "400013": "HDFC MF", "400014": "HSBC MF",
    "400015": "ICICI Prudential MF", "400019": "Kotak MF", "400020": "LIC MF",
    "400021": "Invesco India MF", "400024": "Quantum MF", "400025": "Nippon India MF",
    "400027": "SBI MF", "400028": "Bandhan MF", "400029": "Sundaram MF",
    "400030": "Tata MF", "400032": "UTI MF", "400033": "Mirae Asset MF",
    "400040": "Axis MF", "400041": "Navi MF", "400042": "Motilal Oswal MF",
    "400044": "PGIM India MF", "400045": "Union MF", "400047": "360 ONE MF",
    "400049": "Parag Parikh MF", "400054": "Mahindra Manulife MF",
    "400055": "WhiteOak Capital MF", "400057": "Trust MF", "400058": "NJ MF",
    "400059": "Samco MF", "400060": "Bajaj Finserv MF", "400062": "Zerodha MF",
    "400066": "JioBlackRock MF",
}


def resolve_name(code: str) -> str:
    return AMC_CODE_TO_NAME.get(str(code), code)


def resolve_codes(query: str) -> list[str]:
    q = query.lower()
    return [code for code, name in AMC_CODE_TO_NAME.items() if q in name.lower()]
