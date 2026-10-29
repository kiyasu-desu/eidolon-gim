"""Original synthetic stories for the generic corpus/retrieval tests.

They are inserted through StoryCorpus; GIM file parsing is covered separately.
"""
from pathlib import Path
from collections.abc import Iterable

from eidolon.characters import Character
from eidolon.corpus import Episode, Line, StoryCorpus

def write_sample_stories(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    return root

async def seed_sample_stories(root: Path, corpus: StoryCorpus, characters: Iterable[Character]):
    known = {c.id for c in characters}
    def episode(id, category, source, title, cast, lines):
        return Episode(id, category, source, title, frozenset(cast) & known,
                       tuple(Line(*line) for line in lines), 'gim-csv')
    await corpus.save([
        episode('produce_events/100100101','培育剧情','練習編','公園の歌声', ['sora'], [
            ('プロデューサー','（新しい練習メニューを\n相談しよう）','（来商量新的练习安排吧）'),
            ('社長','練習室の鍵を預けておくね','练习室的钥匙交给你了'),
            ('ソラ','公園で新しい練習をしていました','我在公园进行了新的练习'),
            ('ソラ','えっと……今日は二回練習しました','那个……今天练习了两次'),
        ]),
        episode('produce_events/600100106','培育剧情','練習編','決勝後コミュ',['sora'],[
            ('ソラ','……練習の成果が出たんですね','……练习有成果了呢'),
            ('プロデューサー','次の練習もこの調子で進めよう','下一次练习也这样继续吧'),
        ]),
        episode('produce_events/201100401','S卡剧情','【練習の帰り道】青葉リク','長崎の味',['sora','riku'],[
            ('リク','手作りのご飯を持ってきたよ！','我带来了自己做的饭！'),
            ('リクの母','リク、帰りの時間を教えてね','陆，告诉我回家的时间吧'),
            ('ソラ＆リク','はいっ！','好的！'),
        ]),
        episode('game_event_communications/400100401','活动剧情','Synthetic Event','第1話',[],[
            ('ナギ','準備の手順を確認します','我来确认准备的步骤'),
            ('ヒナ','公園で撮るんだって！','听说要在公园拍！'),
        ]),
    ])
