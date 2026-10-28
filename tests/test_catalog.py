from simready_assets.catalog import categorize, groups, load_catalog, search


def test_catalog_has_all_assets():
    assert len(load_catalog()) == 2603


def test_search_all_words_must_match():
    hits, total = search("bolt m8")
    assert total >= 2 and all("bolt" in a.name and "m8" in a.name for a in hits)


def test_search_group_filter_and_limit():
    hits, total = search("chair", group="office", limit=2)
    assert len(hits) == 2 and total > 2 and all(a.group == "office" for a in hits)


def test_groups_counts():
    g = groups()
    assert g["office"] == 201 and g["machinery_robotics"] == 131 and sum(g.values()) == 2603


def test_categorize_overrides_are_case_insensitive():
    assert categorize("misc_printerPaper_a01") == "office"
    assert categorize("trashCan_office_beige_a03") == "office"
    assert categorize("conveyor_belt_a02") == "machinery_robotics"
    assert categorize("zzz_unknown_a01") == "other"
