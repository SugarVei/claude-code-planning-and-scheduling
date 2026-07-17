"""共享 fixture：金标算例 V-toy-1 工作簿路径与只读加载。"""
from pathlib import Path

import openpyxl
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
VTOY1_PATH = REPO_ROOT / "data" / "vtoy1.xlsx"


@pytest.fixture(scope="session")
def vtoy1_workbook():
    """以只读值模式加载金标工作簿（data_only=True 读取计算后的值）。"""
    assert VTOY1_PATH.exists(), f"金标算例缺失: {VTOY1_PATH}"
    return openpyxl.load_workbook(VTOY1_PATH, data_only=True)
