import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from parquet_viewer import ParquetViewService
import json


def check_getview(url):
    """Test ParquetViewService.get_view() returns valid table for each parquet URL."""
    service = ParquetViewService(url)
    response = service.get_view()
    assert response is not None, f"get_view returned None for {url}"
    assert response.num_rows >= 0, f"Invalid table for {url}"
    assert len(response.column_names) > 0, f"No columns in table for {url}"
    print(f"{response.num_rows} rows, {len(response.column_names)} columns")


if __name__ == "__main__":
    urls_file = Path(__file__).with_name("parquets.json")
    with open(urls_file, "r") as handle:
        urls = json.load(handle)

    for key, value in urls.items():
        print("-"*25)
        print(f"- {key}: {value}")
        check_getview(value)

    print("\nAll ParquetViewService tests passed!")