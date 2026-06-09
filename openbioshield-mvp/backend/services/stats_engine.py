"""Statistical computation core using pandas and statsmodels."""

from __future__ import annotations

import io
import logging
from typing import Any

logger = logging.getLogger(__name__)

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
    logger.info("[analyze_precision] file=%s  target=%s  groups=%s", filename, target_col, group_columns)

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
    logger.info("[analyze_precision] OK  n=%d  grand_mean=%.4f", len(df), grand_mean)


def analyze_method_comparison(
    file_bytes: bytes,
    schema: dict[str, Any],
    filename: str = "upload.xlsx",
) -> dict[str, Any]:
    """EP09-A3: Deming regression + Bland-Altman analysis."""
    ref_col  = schema["reference_column"]
    test_col = schema["test_column"]
    logger.info("[analyze_method_comparison] file=%s  ref=%s  test=%s", filename, ref_col, test_col)

    if filename.endswith(".csv"):
        df = pd.read_csv(io.BytesIO(file_bytes))
    else:
        df = pd.read_excel(io.BytesIO(file_bytes))

    for col in (ref_col, test_col):
        if col not in df.columns:
            raise ValueError(f"Column '{col}' not found in file")

    df = df.dropna(subset=[ref_col, test_col]).copy()
    df[ref_col]  = pd.to_numeric(df[ref_col],  errors="coerce")
    df[test_col] = pd.to_numeric(df[test_col], errors="coerce")
    df = df.dropna(subset=[ref_col, test_col])

    x = df[ref_col].to_numpy(dtype=float)
    y = df[test_col].to_numpy(dtype=float)
    n = len(x)

    if n < 2:
        raise ValueError("At least 2 paired observations required for EP09 analysis")

    # ── Pearson correlation ────────────────────────────────────────────────
    r_val, p_corr = stats.pearsonr(x, y)
    r_squared = float(r_val ** 2)

    # ── Deming regression (lambda = 1, equal error variances) ─────────────
    x_mean = float(x.mean())
    y_mean = float(y.mean())
    sxx = float(np.sum((x - x_mean) ** 2))
    syy = float(np.sum((y - y_mean) ** 2))
    sxy = float(np.sum((x - x_mean) * (y - y_mean)))

    discriminant = (syy - sxx) ** 2 + 4.0 * sxy ** 2
    slope     = float((syy - sxx + np.sqrt(discriminant)) / (2.0 * sxy)) if sxy != 0 else 1.0
    intercept = float(y_mean - slope * x_mean)

    # ── Bland-Altman ───────────────────────────────────────────────────────
    avg  = (x + y) / 2.0
    diff = y - x
    mean_diff = float(diff.mean())
    sd_diff   = float(diff.std(ddof=1))
    loa_upper = mean_diff + 1.96 * sd_diff
    loa_lower = mean_diff - 1.96 * sd_diff

    scatter_data     = [{"ref": round(float(xi), 4), "test": round(float(yi), 4)}
                        for xi, yi in zip(x, y)]
    bland_altman_pts = [{"avg": round(float(a), 4), "diff": round(float(d), 4)}
                        for a, d in zip(avg, diff)]

    return {
        "r_squared":  round(r_squared, 4),
        "pearson_r":  round(float(r_val), 4),
        "deming": {
            "slope":     round(slope, 4),
            "intercept": round(intercept, 4),
        },
        "bland_altman": {
            "mean_diff": round(mean_diff, 4),
            "sd_diff":   round(sd_diff, 4),
            "loa_upper": round(loa_upper, 4),
            "loa_lower": round(loa_lower, 4),
        },
        "scatter_data":       scatter_data,
        "bland_altman_data":  bland_altman_pts,
        "sample_count":       n,
        "reference_column":   ref_col,
        "test_column":        test_col,
    }
    logger.info("[analyze_method_comparison] OK  n=%d  r2=%.4f  slope=%.4f", n, r_squared, slope)


def extract_excel_metadata(file_bytes: bytes, filename: str = "upload.xlsx", n_rows: int = 5) -> dict:
    logger.info("[extract_excel_metadata] file=%s  size=%d bytes", filename, len(file_bytes))
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
