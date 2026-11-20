from pathlib import Path

import pandas as pd


def extract_summary(input_path: Path) -> pd.DataFrame:
    s = pd.read_csv(input_path).dropna()
    s = s.loc[s.type == "package"]
    s = s.loc[~s.uri.str.contains(".git")]
    s = s.loc[~s.summary.str.contains("no summary")]
    s.drop(columns=["type"], inplace=True)
    s.to_csv(input_path.parent / "overview.csv", index=False)
    return s


input_path = Path(__file__).parents[2] / "Auto-GPT_summary.csv"
extract_summary(input_path)
