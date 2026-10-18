"""Synthetic Phase 39 documents. Inline strings only: the pre-push guard blocks
committed CSV files. All merchants and amounts are fictional."""

WALLET_HEADER = "account;category;currency;amount;ref_currency_amount;type;payee;note;date;transfer\n"

WALLET_CSV = WALLET_HEADER + (
    "ZZ Cash;Food;IDR;-45000.00;-45000.00;Expenses;ZZ Warung;lunch;2026-03-05 12:10:00;false\n"
    "ZZ Cash;Salary;IDR;3000000.00;3000000.00;Income;;bonus;2026-03-06 09:00:00;false\n"
    "ZZ Bank;Shopping;IDR;-120000.00;-120000.00;Expenses;ZZ Mart;shirt;2026-03-07 15:30:00;false\n"
    "ZZ Cash;Transfer;IDR;-500000.00;-500000.00;Expenses;;to bank;2026-03-08 10:00:00;true\n"
    "ZZ Bank;Transfer;IDR;500000.00;500000.00;Income;;from cash;2026-03-08 10:00:00;true\n"
)

WALLET_USD_CSV = WALLET_CSV + (
    "ZZ Cash;Food;USD;-5.00;-5.00;Expenses;ZZ Diner;dinner;2026-03-09 19:00:00;false\n"
)

# ";" delimiter, BOM, dotted thousands, dd/mm/yyyy with days > 12, Debit/Kredit pair.
GENERIC_ID_CSV = "﻿" + (
    "Tanggal;Keterangan;Debit;Kredit;Saldo\n"
    "25/03/2026;ZZ Kopi;1.250.000,00;;5.000.000,00\n"
    "26/03/2026;ZZ Gaji;;2.000.000,00;7.000.000,00\n"
    "02/03/2026;ZZ Parkir;15.000,50;;6.984.999,50\n"
)

# "," delimiter, quoted description containing a comma, mm/dd/yyyy with a second part > 12.
GENERIC_US_CSV = (
    "Date,Description,Amount\n"
    '03/25/2026,"ZZ Store, Main","-1,250.50"\n'
    '03/26/2026,ZZ Refund,"2,000.00"\n'
)

# "1.250"-style amounts and 03/04/2026-style dates: nothing to settle either guess.
NO_EVIDENCE_CSV = (
    "Date,Description,Amount\n"
    "03/04/2026,ZZ Toko,-1.250\n"
    "04/04/2026,ZZ Bengkel,-20.000\n"
)

CONTRADICTORY_DATES_CSV = (
    "Date,Description,Amount\n"
    "25/03/2026,ZZ Satu,-1000\n"
    "03/25/2026,ZZ Dua,-2000\n"
)

AMBIGUOUS_HEADERS_CSV = (
    "Date,Description,Amount,Jumlah\n"
    "2026-03-05,ZZ Toko,-1000,-1000\n"
)

UNMAPPED_CSV = (
    "Description,Amount\n"
    "ZZ Toko,-1000\n"
)

BOTH_FILLED_CSV = (
    "Date,Description,Debit,Credit\n"
    "2026-03-05,ZZ Ok,1000,\n"
    "2026-03-06,ZZ Both,1000,2000\n"
)

BAD_AMOUNT_CSV = (
    "Date,Description,Amount\n"
    "2026-03-05,ZZ Ok,-1000\n"
    "2026-03-06,ZZ Bad,12abc\n"
)


def over_500_csv() -> str:
    """501 data rows of a plain ISO-dated CSV."""
    return "Date,Description,Amount\n" + "".join(
        f"2026-03-05,ZZ Row {i},-1000.00\n" for i in range(501)
    )
