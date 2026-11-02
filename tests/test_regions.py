import pytest

from osint.regions import DISPLAY_ORDER, HOME_REGION, REGIONS, region_name, tag, tag_report


def test_every_region_is_listed_once_in_display_order_with_a_name() -> None:
    assert sorted(DISPLAY_ORDER) == sorted(r.id for r in REGIONS)
    assert len(set(DISPLAY_ORDER)) == len(DISPLAY_ORDER)
    assert region_name("bien_dong") == "Biển Đông" and region_name("nga") == "Nga"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Beijing drills water cannons near disputed South China Sea shoals",
            {"bien_dong", "trung_quoc"},
        ),
        ("Philippines and Vietnam discuss Spratly Islands patrols", {"bien_dong", "dong_nam_a"}),
        (
            "Hegseth discusses Iran with Netanyahu in unannounced visit to Israel",
            {"my", "iran", "trung_dong", "israel_gaza"},
        ),
        (
            "North Korea fires missile barrage days after rejecting South's border talks",
            {"trieu_tien", "dong_bac_a"},
        ),
        (
            "South Korean lasers down three drones in Army demo, Hanwha says",
            {"han_quoc", "dong_bac_a"},
        ),
        ("Ukraine's Zelenskyy says US decisions are hard to explain", {"ukraine", "my"}),
        (
            "Russia pulls its ambassador from London over support for Kyiv",
            {"nga", "ukraine", "chau_au"},
        ),
        ("Houthis seize strategic port city in Yemen", {"trung_dong"}),
        (
            "Taiwan thinks the unthinkable: resisting China without America",
            {"dai_loan", "dong_bac_a", "trung_quoc", "my"},
        ),
        ("AUKUS submarines: Australia and Guam hosting Pacific deployments", {"chau_uc_tbd"}),
        ("Pentagon to start expanding Greenland bases", {"my", "bac_cuc"}),
        ("Sudan claims UAV attacks launched from Ethiopia", {"chau_phi"}),
        ("India and Pakistan trade fire along Kashmir line", {"nam_a"}),
        ("US strikes Venezuela-linked drug boats off Colombia", {"my_latinh"}),
    ],
)
def test_english_reports_get_the_expected_regions(text: str, expected: set[str]) -> None:
    assert expected <= set(tag(text))


@pytest.mark.parametrize(
    ("text", "region"),
    [
        ("Điện Kremlin lên tiếng về việc ông Trump muốn Ukraine bầu tổng thống mới", "nga"),
        ("Iran nã tên lửa vào tàu sân bay, tàu khu trục Mỹ", "iran"),
        ("Nga thử tên lửa gần quần đảo đang tranh chấp với Nhật Bản", "nhat_ban"),
        ("Quân đội Hàn Quốc bắn cảnh cáo về phía nhóm lính Triều Tiên", "trieu_tien"),
        ("Песков заявил о диалоге между омбудсменами России и Украины", "ukraine"),
        ("Министерство обороны КНДР провело испытание ракеты", "trieu_tien"),
        ("国防部：中国军队坚决反对美国国防部对中方进行无端指责", "my"),
        ("许其亮魏凤和分别与日本防卫大臣会见会谈", "nhat_ban"),
        ("俄国防部向美方展示“先锋”高超音速导弹", "nga"),
        ("북한이 동해상으로 탄도미사일을 발사했다", "trieu_tien"),
        ("ロシアがウクライナの軍事施設を攻撃した", "ukraine"),
        ("ABD'nin Körfez ülkelerini İran'a saldırıların başlayabileceği iddia edildi", "iran"),
        ("إيران تطلق صواريخ على سفن أمريكية في الخليج", "iran"),
    ],
)
def test_other_languages_get_the_expected_region(text: str, region: str) -> None:
    assert region in tag(text)


@pytest.mark.parametrize(
    ("text", "absent"),
    [
        ("Indiana lawmakers debate a new highway bill", "nam_a"),  # whole-word "India" only
        ("The package gives us all a reason to celebrate", "my"),  # pronoun, not the country
        ("An action plan for the quarter", "trung_quoc"),  # "plan" is not PLAN
        ("Malicious software hits a hospital network", "chau_phi"),  # not Mali
        ("A roman candle lit the festival", "trung_dong"),  # not Oman
        ("Metallica Skid Steer: Where Heavy Metal Meets Heavy Equipment", "my"),
    ],
)
def test_ordinary_words_do_not_trigger_a_region(text: str, absent: str) -> None:
    assert absent not in tag(text)


def test_us_in_capitals_and_dotted_forms_count_as_the_united_states() -> None:
    assert "my" in tag("US Navy destroyer enters dry dock")
    assert "my" in tag("The U.S. Army fields a new system")


def test_tags_come_back_in_display_order_and_none_is_fine() -> None:
    out = tag("Iran and Ukraine and Russia and the South China Sea")
    assert out == [r for r in DISPLAY_ORDER if r in out]
    assert out.index("bien_dong") < out.index("nga") < out.index("ukraine") < out.index("iran")
    assert tag("A cooking competition in a small town") == []
    assert tag(None, "") == []


def test_chinese_shorthand_names_resolve_without_matching_ordinary_words() -> None:
    assert {"nga", "my"} <= set(tag("俄方称美军在黑海活动"))
    assert "my" not in tag("她有一个美丽的花园")  # 美丽 means beautiful, not America
    assert "nga" not in tag("这是一个好办法")


def test_a_headline_mention_counts_but_a_passing_body_mention_does_not() -> None:
    body = "The ministry reviewed procurement. A delegation from Africa attended the briefing."
    assert tag("Navy orders new frigates", body) == []
    assert "chau_phi" in tag("Navy orders new frigates for Africa", body)
    twice = "Talks with Africa stalled. Officials in Africa asked for more time."
    assert "chau_phi" in tag("Navy orders new frigates", twice)


def test_polish_and_indian_agency_names() -> None:
    assert {"nga", "chau_au"} <= set(tag("Wleciały do Polski z Białorusi samoloty z Rosji"))
    assert "nam_a" in tag("ISRO targets five more navigation satellite launches")


def test_chinese_military_vocabulary_and_small_european_states() -> None:
    assert "trung_quoc" in tag("起飞——陆军第76集团军某陆航旅用战斗力牵引全面建设记事")
    assert "trung_quoc" in tag("中央军委印发《关于加强军队党的政治建设的意见》")
    assert "chau_au" in tag("Latvia reports brief airspace intrusion near Russia, Belarus borders")
    assert "chau_au" in tag("Switzerland Is Cutting Back on Its F-35A Order")


def test_home_region_applies_only_when_nothing_else_matched() -> None:
    assert tag_report(
        "Army converts Futures and Concepts Command", None, "www.militarytimes.com"
    ) == ["my"]
    assert tag_report("Iran talks resume", None, "militarytimes.com") == ["trung_dong", "iran"]
    assert tag_report("Army converts Futures and Concepts Command", None, "example.org") == []
    assert tag_report("A cooking show", None, None) == []
    assert set(HOME_REGION.values()) <= set(DISPLAY_ORDER)
