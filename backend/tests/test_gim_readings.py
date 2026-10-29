"""GIM names must reach the production Fish pronunciation dictionary."""

from pathlib import Path

from eidolon.readings import load_readings, pronunciation_dictionary, used_in


PATH = Path(__file__).resolve().parents[2] / "characters/gim/readings.toml"


NAMES = [
        ("花海咲季", "はなみ さき"), ("咲季", "さき"),
        ("藤田ことね", "ふじた ことね"),
        ("有村麻央", "ありむら まお"), ("麻央", "まお"),
        ("葛城リーリヤ", "かつらぎ りーりや"), ("リーリヤ", "りーりや"),
        ("倉本千奈", "くらもと ちな"), ("千奈", "ちな"),
        ("紫雲清夏", "しうん すみか"), ("清夏", "すみか"),
        ("篠澤広", "しのさわ ひろ"),
        ("姫崎莉波", "ひめさき りなみ"), ("莉波", "りなみ"),
        ("花海佑芽", "はなみ うめ"), ("佑芽", "うめ"),
        ("秦谷美鈴", "はたや みすず"), ("美鈴", "みすず"),
        ("十王星南", "じゅうおう せな"), ("星南", "せな"),
        ("雨夜燕", "あまや つばめ"),
        ("十王邦夫", "じゅうおう くにお"),
        ("根緒亜紗里", "ねお あさり"),
        ("賀陽燐羽", "かや りんは"), ("燐羽", "りんは"),
]


def test_gim_names_have_readings_in_the_actual_speech_dictionary():
    readings = load_readings(PATH)
    dictionary = pronunciation_dictionary(readings)
    assert dictionary is not None
    for written, kana in NAMES:
        matched = used_in(written, readings)
        assert len(matched) == 1 and matched[0].written == written, written
        assert matched[0].kana == kana, written
        assert any(item["key"] == written and item["value"] for item in dictionary[0]["items"]), written


def test_reported_misuzu_sentence_and_its_subtitle_spelling_use_the_same_reading():
    readings = load_readings(PATH)
    for text in ("美鈴と？ うーん、悪くないけど……急に誘うのもね。", "美铃と？"):
        matched = used_in(text, readings)
        assert len(matched) == 1, text
        assert matched[0].kana == "みすず", text
        assert matched[0].phonemes == next(r.phonemes for r in readings if r.written == "美鈴"), text


def test_spaced_names_are_matched_as_a_whole_and_story_nicknames_keep_their_reading():
    readings = load_readings(PATH)
    for text in ("秦谷 美鈴", "秦谷　美鈴"):
        matched = used_in(text, readings)
        assert len(matched) == 1 and matched[0].written == text, text
        assert matched[0].kana == "はたや みすず", text
    assert used_in("まりちゃん", readings)[0].kana == "まりちゃん"
    assert used_in("りんちゃん", readings)[0].kana == "りんちゃん"


def test_name_corrections_do_not_take_over_common_words():
    readings = load_readings(PATH)
    for sentence in ("広い庭で燕が飛んでいる。", "そういうことね。", "雨夜の月。"):
        assert used_in(sentence, readings) == (), sentence
