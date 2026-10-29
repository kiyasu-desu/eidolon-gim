import { describe, expect, it } from "vitest";

import { matchesSearch, type Searchable } from "@/lib/characterSearch";

const ILLUMINATION = ["Sample Stars", "さんぷるすたーず"] as const;
const LANTICA = ["Sample Harmony", "さんぷるはーもにー"] as const;
const HOKAGO = ["放課後サンプル", "ほうかごさんぷる"] as const;
const NOCTCHILL = ["Sample Night", "さんぷるないと"] as const;
const STRAYLIGHT = ["Sample Light", "さんぷるらいと"] as const;

function idol(
  name: string,
  [name_zh, name_kana, name_romaji]: [string, string, string],
  [unit, unit_reading]: readonly [string, string] | readonly [null, null] = [null, null],
): Searchable {
  return { name, name_zh, name_kana, name_romaji, unit, unit_reading };
}

const ROSTER: Searchable[] = [
  idol("星野ソラ", ["星野空", "ほしの そら", "Hoshino Sora"], ILLUMINATION),
  idol("晴川ヒナ", ["晴川日奈", "はるかわ ひな", "Harukawa Hina"], ILLUMINATION),
  idol("青葉リク", ["青叶陆", "あおば りく", "Aoba Riku"], LANTICA),
  idol("架空美々", ["架空美美", "かくう みみ", "Kaku Mimi"], LANTICA),
  idol("架空アオ", ["架空青", "かくう あお", "Kaku Ao"], LANTICA),
  idol("架空カナ", ["架空佳奈", "かくう かな", "Kaku Kana"], HOKAGO),
  idol("架空ジュン", ["架空淳", "かくう じゅん", "Kaku Jun"], HOKAGO),
  idol("架空トラ", ["架空永", "かくう とら", "Kaku Tora"], NOCTCHILL),
  idol("架空マド", ["架空圆", "かくう まど", "Kaku Mado"], NOCTCHILL),
  idol("架空アサ", ["架空朝日", "かくう あさ", "Kaku Asa"], STRAYLIGHT),
  { name: "誰か", name_zh: null, name_kana: null, name_romaji: null, unit: null, unit_reading: null },
];

/** 搜索框里是 `query` 时留下的角色，按名单的顺序。 */
function found(query: string): string[] {
  return ROSTER.filter((c) => matchesSearch(c, query)).map((c) => c.name);
}

describe("matchesSearch", () => {
  it.each(["星野空", "星野", "ソラ"])("中文简体译名、只输姓或只输名都找得到：%s", (query) => {
    expect(found(query)).toEqual(["星野ソラ"]);
  });

  it.each([
    ["晴川日奈", "晴川ヒナ"],
    ["日奈", "晴川ヒナ"],
    ["朝日", "架空アサ"],
    ["圆", "架空マド"],
  ])("名字是假名或日文字形的，用社区通行的中文译名找得到：%s", (query, name) => {
    expect(found(query)).toEqual([name]);
  });

  it.each(["陆", "リク", "青葉", "青叶"])("繁体、日文字形和简体混着输都行：%s", (query) => {
    expect(found(query)).toEqual(["青葉リク"]);
  });

  it.each(["星野", "星野ソラ", "マド"])("日文原名照旧找得到：%s", (query) => {
    expect(found(query)).toHaveLength(1);
  });

  it.each(["美々", "美美", "架空美"])("々 和它前面的字一样：%s", (query) => {
    expect(found(query)).toEqual(["架空美々"]);
  });

  it.each(["そら", "ソラ", "ほしの", "ホシノソラ", "ﾎｼﾉ"])("假名读音，平假名片假名都算：%s", (query) => {
    expect(found(query)).toEqual(["星野ソラ"]);
  });

  it.each(["sora", "Hoshino", "Hoshino Sora", "sora hoshino", "Sora Hoshino", "hoshinosora", "HOSHINO"])(
    "罗马字不分姓名先后、大小写和空格：%s",
    (query) => {
      expect(found(query)).toEqual(["星野ソラ"]);
    },
  );

  it.each(["tora", "toora", "tōra", "Tohra"])("长音的几种写法都认：%s", (query) => {
    expect(found(query)).toEqual(["架空トラ"]);
  });

  it.each(["Sample Harmony", "sampleharmony", "Sample Harmony", "サンプルハーモニー", "さんぷるはーもにー"])("组合名搜出整组成员：%s", (query) => {
    expect(found(query)).toEqual(["青葉リク", "架空美々", "架空アオ"]);
  });

  it.each(["放课后", "放課後", "ほうかご"])("组合名用简体、日文或读音写都行：%s", (query) => {
    expect(found(query)).toEqual(["架空カナ", "架空ジュン"]);
  });

  it("前后多打的空格不算", () => {
    expect(found("  ソラ ")).toEqual(["星野ソラ"]);
  });

  it.each(["", "   "])("空着时全部留下：%j", (query) => {
    expect(found(query)).toEqual(ROSTER.map((c) => c.name));
  });

  it("只输一个字母不出错，只是结果多一点", () => {
    expect(found("a")).toContain("星野ソラ");
  });

  it.each(["佐藤", "xyz", "ぴーちゃん"])("不认识的输入什么都不留下：%s", (query) => {
    expect(found(query)).toEqual([]);
  });

  it("没配另外几种名字的角色，照旧用原名找得到", () => {
    expect(found("誰か")).toEqual(["誰か"]);
  });
});
