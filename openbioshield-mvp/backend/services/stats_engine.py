"""Statistical computation core using pandas and statsmodels."""

from __future__ import annotations

import io
from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy import stats


def _cv_percent(sd: float, mean: float) -> float:
    if mean == 0:
        return 0.0
    return round((sd / abs(mean)) * 100, 4)


def _build_group_label(df: pd.DataFrame, group_columns: list[str]) -> pd.Series:
    if not group_columns:
        return pd.Series(["all"] * len(df), index=df.index)
    return df[group_columns].astype(str).agg("|".join, axis=1)


def analyze_precision(
    file_bytes: bytes,
    schema: dict[str, Any],
    filename: str = "upload.xlsx",
) -> dict[str, Any]:
    target_col = schema["target_column"]
    group_columns: list[str] = schema.get("group_columns", [])

    if filename.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_bytes))
    else:
        df = pd.read_excel(io.BytesIO(file_bytes))

    if target_col not in df.columns:
        raise ValueError(f"Target column '{target_col}' not found in file")

    df = df.dropna(subset=[target_col]).copy()
    df[target_col] = pd.to_numeric(df[target_col], errors="coerce")
    df = df.dropna(subset=[target_col])

    for col in group_columns:
        if col not in df.columns:
            raise ValueError(f"Group column '{col}' not found in file")

    df["_group"] = _build_group_label(df, group_columns)
    values = df[target_col]
    grand_mean = float(values.mean())

    group_stats = (
        df.groupby("_group")[target_col]
        .agg(["mean", "std", "count"])
        .reset_index()
        .rename(columns={"_group": "group", "mean": "mean", "std": "sd", "count": "n"})
    )
    group_stats["cv_percent"] = group_stats.apply(
        lambda r: _cv_percent(r["sd"], r["mean"]), axis=1
    )

    repeatability_sd = float(df.groupby("_group")[target_col].std().mean())
    repeatability_cv = _cv_percent(repeatability_sd, grand_mean)

    if len(group_columns) > 0:
        formula = f"Q('{target_col}') ~ C(_group)"
        model = smf.ols(formula, data=df).fit()
        anova_table = sm.stats.anova_lm(model, typ=1)
        f_value = float(anova_table.loc["C(_group)", "F"])
        p_value = float(anova_table.loc["C(_group)", "PR(>F)"])

        ss_between = float(anova_table.loc["C(_group)", "sum_sq"])
        ss_within = float(anova_table.loc["Residual", "sum_sq"])
        ms_between = float(anova_table.loc["C(_group)", "mean_sq"])
        ms_within = float(anova_table.loc["Residual", "mean_sq"])

        reproducibility_sd = float(np.sqrt(max(ms_between - ms_within, 0)))
        reproducibility_cv = _cv_percent(reproducibility_sd, grand_mean)
    else:
        f_value = 0.0
        p_value = 1.0
        ss_between = 0.0
        ss_within = float(values.var() * (len(values) - 1))
        reproducibility_sd = 0.0
        reproducibility_cv = 0.0

    total_variance = ss_between + ss_within
    within_ratio = round(ss_within / total_variance * 100, 2) if total_variance > 0 else 0
    between_ratio = round(ss_between / total_variance * 100, 2) if total_variance > 0 else 0

    return {
        "anova": {
            "f_value": round(f_value, 6),
            "p_value": round(p_value, 6),
        },
        "repeatability": {
            "sd": round(repeatability_sd, 6),
            "cv_percent": repeatability_cv,
        },
        "reproducibility": {
            "sd": round(reproducibility_sd, 6),
            "cv_percent": reproducibility_cv,
        },
        "variance_components": {
            "within_group": round(ss_within, 6),
            "between_group": round(ss_between, 6),
            "within_group_percent": within_ratio,
            "between_group_percent": between_ratio,
        },
        "grand_mean": round(grand_mean, 4),
        "sample_count": int(len(df)),
        "groups": group_stats.to_dict(orient="records"),
        "target_column": target_col,
        "group_columns": group_columns,
    }


def extract_excel_metadata(file_bytes: bytes, filename: str = "upload.xlsx", n_rows: int = 5) -> dict:
    if filename.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_bytes), nrows=n_rows)
    else:
        df = pd.read_excel(io.BytesIO(file_bytes), nrows=n_rows)

    columns = []
    for col in df.columns:
        sample_values = df[col].dropna().head(3).tolist()
        columns.append(
            {
                "name": str(col),
                "dtype": str(df[col].dtype),
                "sample_values": [str(v) for v in sample_values],
            }
        )

    return {
        "filename": filename,
        "column_count": len(df.columns),
        "row_preview_count": len(df),
        "columns": columns,
    }
