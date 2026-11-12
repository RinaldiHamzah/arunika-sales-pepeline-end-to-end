from pathlib import Path

import pandas as pd
import pytest

from pipeline.extract.base import ExtractedSource
from pipeline.promotions import apply_order_promotions, extract_promotion_sources
from pipeline.validation.contracts import SOURCE_SPECS


def _source(name, path, records):
    frame = pd.DataFrame(records, dtype="string")
    return ExtractedSource(
        name.upper(),
        f"raw.{name}",
        Path(path),
        "CSV",
        frame,
        {column: column for column in frame.columns},
        source_records=len(frame),
    )


def _promo_files(tmp_path, redemption="SHOPEE,ORDER-1,NEW15,10.00"):
    (tmp_path / "promo_master.csv").write_text(
        "promo_code,promo_name,discount_type,discount_value,start_date,end_date,status\n"
        "NEW15,Promo Pengguna Baru,percentage,15,2026-01-01,2026-12-31,active\n",
        encoding="utf-8",
    )
    (tmp_path / "order_promotions.csv").write_text(
        "source_name,order_id,promo_code,discount_amount\n" + redemption + "\n",
        encoding="utf-8",
    )
    return extract_promotion_sources(tmp_path)


def test_identical_promo_rows_are_safe_but_conflicts_are_not(tmp_path):
    from pipeline.promotions import _read_master
    promotions = _promo_files(tmp_path, "SHOPEE,ORDER-1,NEW15,10.00\nSHOPEE,ORDER-1,NEW15,10")
    master = promotions[0]
    master.frame.loc[len(master.frame)] = master.frame.iloc[0]
    assert len(_read_master(master)) == 1
    # Tanpa transaksi, uji aturan deduplikasi penukaran secara terisolasi.
    apply_order_promotions([], promotions)
    promotions[1].frame.loc[1, "discount_amount"] = "11"
    with pytest.raises(ValueError, match="isi berbeda"):
        apply_order_promotions([], promotions)


def test_discount_order_allocated_by_gross_and_channel_scoped(tmp_path):
    promotions = _promo_files(tmp_path, " SHOPEE , ORDER-1 , new15 , 10.00")
    spec = SOURCE_SPECS["shopee"]
    columns = list(spec.values()) + ["discount_amount", "promo_code"]
    shopee = _source(
        "shopee",
        tmp_path / "shopee.csv",
        [
            dict(
                zip(
                    columns,
                    ["ORDER-1", "1", "2026-06-01", "Serum", "1", "30", "A", "Jakarta", "COD", "completed", "0", ""],
                )
            ),
            dict(
                zip(
                    columns,
                    ["ORDER-1", "2", "2026-06-01", "Toner", "1", "70", "A", "Jakarta", "COD", "completed", "0", ""],
                )
            ),
        ],
    )
    tokopedia = _source(
        "tokopedia",
        tmp_path / "tokopedia.csv",
        [
            dict(
                zip(
                    list(SOURCE_SPECS["tokopedia"].values()) + ["discount_amount", "promo_code"],
                    ["ORDER-1", "1", "01/06/2026", "Powder", "1", "100", "B", "Jakarta", "COD", "completed", "0", ""],
                )
            )
        ],
    )
    website = _source(
        "website",
        tmp_path / "website.csv",
        [
            {
                "invoice_no": "ORDER-1",
                "line_item_no": "1",
                "created_at": "2026-06-01T10:00:00",
                "product_identifier": "SKU-1",
                "quantity": "1",
                "unit_price": "100",
                "discount_amount": "0",
                "promo_code": "",
            }
        ],
    )
    offline = _source(
        "offline",
        tmp_path / "offline.csv",
        [
            {
                "pos_receipt_no": "ORDER-1",
                "receipt_line_no": "1",
                "sold_at": "01-Jun-2026",
                "item_description": "Toner",
                "units": "1",
                "item_price": "100",
                "discount_amount": "0",
                "promo_code": "",
            }
        ],
    )

    enriched, master = apply_order_promotions([shopee, tokopedia, website, offline], promotions)

    assert master["NEW15"]["discount_type"] == "percentage"
    assert enriched[0].frame["discount_amount"].tolist() == ["3.00", "7.00"]
    assert enriched[0].frame["promo_code"].tolist() == ["NEW15", "NEW15"]
    assert enriched[1].frame["discount_amount"].tolist() == ["0"]
    assert enriched[2].frame["discount_amount"].tolist() == ["0"]
    assert enriched[3].frame["discount_amount"].tolist() == ["0"]
    shopee.frame.loc[2] = shopee.frame.iloc[0]
    shopee.frame.loc[3] = shopee.frame.iloc[1]
    repeated, _ = apply_order_promotions([shopee], promotions)
    assert repeated[0].frame["discount_amount"].tolist() == ["3.00", "7.00", "3.00", "7.00"]


def test_redemption_must_reference_master_promo(tmp_path):
    promotions = _promo_files(tmp_path, "SHOPEE,ORDER-1,UNKNOWN,10.00")

    with pytest.raises(ValueError, match="tidak ada di promo_master"):
        apply_order_promotions([], promotions)


def test_channel_line_promo_code_must_map_to_master(tmp_path):
    (tmp_path / "promo_master.csv").write_text(
        "promo_code,promo_name,discount_type,discount_value,start_date,end_date,status\n"
        "NEW15,Promo Pengguna Baru,percentage,15,2026-01-01,2026-12-31,active\n",
        encoding="utf-8",
    )
    (tmp_path / "order_promotions.csv").write_text(
        "source_name,order_id,promo_code,discount_amount\n", encoding="utf-8"
    )
    promotions = extract_promotion_sources(tmp_path)
    spec = SOURCE_SPECS["shopee"]
    frame = dict(
        zip(
            list(spec.values()) + ["discount_amount", "promo_code"],
            ["ORDER-2", "1", "2026-06-01", "Serum", "1", "100", "A", "Jakarta", "COD", "completed", "5.00", "NEW15"],
        )
    )
    source = _source("shopee", tmp_path / "shopee.csv", [frame])

    enriched, _ = apply_order_promotions([source], promotions)

    assert enriched[0].frame.loc[0, "discount_amount"] == "5.00"
    assert enriched[0].frame.loc[0, "promo_code"] == "NEW15"


def test_order_level_and_nonzero_line_discount_cannot_be_counted_twice(tmp_path):
    promotions = _promo_files(tmp_path)
    spec = SOURCE_SPECS["shopee"]
    source = _source(
        "shopee",
        tmp_path / "shopee.csv",
        [
            dict(
                zip(
                    list(spec.values()) + ["discount_amount", "promo_code"],
                    [
                        "ORDER-1",
                        "1",
                        "2026-06-01",
                        "Serum",
                        "1",
                        "100",
                        "A",
                        "Jakarta",
                        "COD",
                        "completed",
                        "2.00",
                        "NEW15",
                    ],
                )
            )
        ],
    )

    with pytest.raises(ValueError, match="tingkat order dan promo baris"):
        apply_order_promotions([source], promotions)


def test_promo_master_requires_explicit_discount_value(tmp_path):
    (tmp_path / "promo_master.csv").write_text(
        "promo_code,promo_name,discount_type,discount_value,start_date,end_date,status\n"
        "WEEKEND15,Promo Akhir Pekan,percentage,,2026-01-01,2026-12-31,active\n",
        encoding="utf-8",
    )
    (tmp_path / "order_promotions.csv").write_text(
        "source_name,order_id,promo_code,discount_amount\n", encoding="utf-8"
    )
    sources = extract_promotion_sources(tmp_path)

    with pytest.raises(ValueError, match="discount_value"):
        apply_order_promotions([], sources)
