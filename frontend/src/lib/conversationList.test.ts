import { describe, expect, it } from "vitest";

import type { LatestConversation } from "@/lib/api";
import { arrange, dayOf, hasUnseen, previewOf, unitsOf } from "@/lib/conversationList";

function latest(last: LatestConversation["last_message"]): LatestConversation {
  return {
    character_id: "sora",
    conversation_id: "c1",
    created_at: "2026-09-28T01:00:00Z",
    last_message: last,
    unseen_reach_out: false,
  };
}

describe("previewOf", () => {
  it("她的最后一句显示字幕，时间取这句话的", () => {
    const preview = previewOf(
      latest({ role: "character", text: null, ja: "えっと", zh: "哇", created_at: "2026-09-28T02:00:00Z" }),
    );

    expect(preview).toEqual({ from: "her", text: "哇", at: "2026-09-28T02:00:00Z", photo: false });
  });

  it("她最后那条回复带着发出来了的照片时，最后一句前面加相机，后面照旧是她的话", () => {
    const preview = previewOf(
      latest({ role: "character", text: null, ja: "どうぞ", zh: "给", created_at: "2026-09-28T02:00:00Z", photo: true }),
    );

    expect(preview).toEqual({ from: "her", text: "给", at: "2026-09-28T02:00:00Z", photo: true });
  });

  it("没有字幕时退回她的日语原文", () => {
    const preview = previewOf(
      latest({ role: "character", text: null, ja: "えっと", zh: "", created_at: "2026-09-28T02:00:00Z" }),
    );

    expect(preview).toMatchObject({ text: "えっと" });
  });

  it("自己的话标成制作人说的", () => {
    const preview = previewOf(
      latest({ role: "user", text: "晚安", ja: null, zh: null, created_at: "2026-09-28T02:00:00Z" }),
    );

    expect(preview).toEqual({ from: "you", text: "晚安", at: "2026-09-28T02:00:00Z" });
  });

  it("最后是一条对话事件时，预览是这件事，时间取它的；送礼记录带礼物名", () => {
    const hungUp = previewOf(latest({ type: "event", kind: "hung_up", created_at: "2026-09-28T03:00:00Z" }));
    const gift = previewOf(
      latest({ type: "event", kind: "gift", created_at: "2026-09-28T04:00:00Z", gift_name: "蛋糕" }),
    );

    expect(hungUp).toEqual({ from: "event", event: "hung_up", gift: null, at: "2026-09-28T03:00:00Z" });
    expect(gift).toEqual({ from: "event", event: "gift", gift: "蛋糕", at: "2026-09-28T04:00:00Z" });
  });

  it("刚开的新对话没有最后一句，时间是对话开始的时间", () => {
    expect(previewOf(latest(null))).toEqual({ from: null, text: "", at: "2026-09-28T01:00:00Z" });
  });

  it("从没聊过的角色没有预览", () => {
    expect(previewOf(undefined)).toBeNull();
  });
});

describe("dayOf", () => {
  // 按本地日历算，不按相差多少小时算。
  const now = new Date(2026, 8, 28, 0, 30);

  it.each([
    [new Date(2026, 8, 28, 0, 5), "today"],
    [new Date(2026, 8, 27, 23, 50), "yesterday"],
    [new Date(2026, 8, 26, 12, 0), "thisYear"],
    [new Date(2026, 0, 1, 0, 0), "thisYear"],
    [new Date(2025, 11, 31, 23, 0), "earlier"],
  ] as const)("%s → %s", (at, day) => {
    expect(dayOf(at, now)).toBe(day);
  });

  it("年初的「昨天」跨了年也还是昨天", () => {
    expect(dayOf(new Date(2025, 11, 31, 22, 0), new Date(2026, 0, 1, 8, 0))).toBe("yesterday");
  });
});

/** 测试用的角色：只有 id 和搜索要看的几种名字。 */
function idol(id: string, name = id, unit: string | null = null) {
  return { id, name, name_zh: null, name_kana: null, name_romaji: null, unit, unit_reading: null };
}

describe("arrange", () => {
  // 接口给的顺序，即原作的偶像顺序。
  const characters = ["sora", "nagi", "hina", "riku", "mina"].map((id) => idol(id));

  /** 她最新的对话：`opened` 时开的，最后一句在 `lastAt`（null 表示还没有话）。 */
  function talked(id: string, opened: string, lastAt: string | null = opened): LatestConversation {
    return {
      character_id: id,
      conversation_id: `c-${id}`,
      created_at: opened,
      last_message: lastAt === null ? null : { role: "user", text: "早", ja: null, zh: null, created_at: lastAt },
      unseen_reach_out: false,
    };
  }

  function order(...summaries: LatestConversation[]): string[] {
    const latest = Object.fromEntries(summaries.map((s) => [s.character_id, s]));
    return arrange(characters, latest).rows.map((row) => row.character.id);
  }

  it("聊过的按最后一句从新到旧排，没聊过的在后面、保持原顺序", () => {
    expect(
      order(
        talked("hina", "2026-10-01T00:00:00Z", "2026-10-01T09:00:00Z"),
        talked("mina", "2026-10-01T00:00:00Z", "2026-10-02T09:00:00Z"),
        talked("nagi", "2026-09-01T00:00:00Z", "2026-09-30T23:00:00Z"),
      ),
    ).toEqual(["mina", "hina", "nagi", "sora", "riku"]);
  });

  it("开了新对话还没说话的，按开对话的时间算", () => {
    expect(
      order(
        talked("sora", "2026-10-01T00:00:00Z", "2026-10-01T09:00:00Z"),
        talked("riku", "2026-10-01T10:00:00Z", null),
      ),
    ).toEqual(["riku", "sora", "nagi", "hina", "mina"]);
  });

  it("时间相同时按原顺序", () => {
    expect(
      order(talked("riku", "2026-10-01T00:00:00Z"), talked("nagi", "2026-10-01T00:00:00Z")),
    ).toEqual(["nagi", "riku", "sora", "hina", "mina"]);
  });

  it("时间的写法不同也按实际先后比", () => {
    expect(
      order(talked("nagi", "2026-10-01T09:00:00+09:00"), talked("riku", "2026-10-01T01:00:00Z")),
    ).toEqual(["riku", "nagi", "sora", "hina", "mina"]);
  });

  it("一位都没聊过时就是原顺序", () => {
    expect(order()).toEqual(["sora", "nagi", "hina", "riku", "mina"]);
  });

  it("摘要里有配置中已经不存在的角色时不出错，也不多出一行", () => {
    expect(order(talked("gone", "2026-10-02T00:00:00Z"), talked("hina", "2026-10-01T00:00:00Z"))).toEqual([
      "hina", "sora", "nagi", "riku", "mina",
    ]);
  });
});

describe("arrange 加上隐藏、置顶和搜索", () => {
  const characters = [
    idol("sora", "星野ソラ", "Sample Stars"),
    idol("nagi", "雨宮ナギ", "Sample Stars"),
    idol("hina", "晴川ヒナ", "Sample Stars"),
    idol("riku", "青葉リク", "Sample Harmony"),
    idol("mina", "架空ミナ", "Sample Harmony"),
  ];

  // hina 最近，其次 riku，再其次 sora；nagi 和 mina 没聊过。
  const latest = Object.fromEntries(
    [
      ["hina", "2026-10-03T00:00:00Z"],
      ["riku", "2026-10-02T00:00:00Z"],
      ["sora", "2026-10-01T00:00:00Z"],
    ].map(([id, at]) => [
      id,
      { character_id: id, conversation_id: `c-${id}`, created_at: at, last_message: null, unseen_reach_out: false },
    ]),
  );

  function arranged(options: Parameters<typeof arrange>[2]) {
    return arrange(characters, latest, options);
  }

  const ids = (result: ReturnType<typeof arranged>) => result.rows.map((row) => row.character.id);

  it("置顶的排在前面，她们之间也按最近往来排", () => {
    const result = arranged({ preferences: { hidden: [], pinned: ["nagi", "sora", "riku"] } });

    expect(ids(result)).toEqual(["riku", "sora", "nagi", "hina", "mina"]);
  });

  it("每一行带上是否置顶、是否隐藏", () => {
    const result = arranged({ preferences: { hidden: ["mina"], pinned: ["sora"] }, query: "sample harmony" });

    expect(result.rows.map(({ character, isPinned, isHidden }) => [character.id, isPinned, isHidden])).toEqual([
      ["riku", false, false],
      ["mina", false, true],
    ]);
    expect(arranged({ preferences: { hidden: [], pinned: ["sora"] } }).rows[0]).toMatchObject({
      isPinned: true,
      isHidden: false,
    });
  });

  it("没有搜索时去掉隐藏的人", () => {
    const result = arranged({ preferences: { hidden: ["hina", "nagi"], pinned: [] } });

    expect(ids(result)).toEqual(["riku", "sora", "mina"]);
  });

  it("当前打开的和正在通话的始终留下，即使隐藏了", () => {
    const result = arranged({ preferences: { hidden: ["hina", "nagi", "mina"], pinned: [] }, keep: ["nagi", "hina"] });

    expect(ids(result)).toEqual(["hina", "riku", "sora", "nagi"]);
    expect(result.rows.find((row) => row.character.id === "nagi")?.isHidden).toBe(true);
  });

  it("有搜索时在所有人里搜，隐藏的人照样出现，也按置顶和最近往来排", () => {
    const result = arranged({ preferences: { hidden: ["sora", "hina"], pinned: ["nagi"] }, query: "sample stars" });

    expect(ids(result)).toEqual(["nagi", "hina", "sora"]);
  });

  it("搜索框只有空格时当作没有搜索", () => {
    const result = arranged({ preferences: { hidden: ["sora"], pinned: [] }, query: "  " });

    expect(ids(result)).toEqual(["hina", "riku", "nagi", "mina"]);
  });

  it("什么都没搜到时没有行", () => {
    expect(arranged({ query: "283" }).rows).toEqual([]);
  });

  it("给出隐藏的人数，只数配置里还存在的角色", () => {
    expect(arranged({ preferences: { hidden: ["sora", "gone", "riku"], pinned: [] } }).hiddenCount).toBe(2);
    expect(arranged({}).hiddenCount).toBe(0);
  });

  it("全部隐藏、又没有始终留下的人时，没有行", () => {
    const everyone = characters.map((c) => c.id);

    expect(arranged({ preferences: { hidden: everyone, pinned: [] } })).toEqual({ rows: [], hiddenCount: 5 });
  });
});

describe("没看过的搭话", () => {
  const characters = ["sora", "nagi", "hina", "riku"].map((id) => idol(id));

  /** 每位最新的对话；`unseen` 里的那几位有没看过的搭话（她刚搭的话就是最后一句）。 */
  function withUnseen(...unseen: string[]): Record<string, LatestConversation> {
    return Object.fromEntries(
      ["sora", "nagi", "hina", "gone"].map((id) => [
        id,
        {
          character_id: id,
          conversation_id: `c-${id}`,
          created_at: "2026-10-01T00:00:00Z",
          last_message: {
            role: "character" as const, text: null, ja: "ねえ", zh: "呐", created_at: "2026-10-02T00:00:00Z",
            ...(unseen.includes(id) && { reach_out: true as const }),
          },
          unseen_reach_out: unseen.includes(id),
        },
      ]),
    );
  }

  const marked = (latest: Record<string, LatestConversation>, options: Parameters<typeof arrange>[2] = {}) =>
    arrange(characters, latest, options).rows.filter((row) => row.isUnseen).map((row) => row.character.id);

  it("有没看过的搭话的那几行标出来，别的行不标", () => {
    expect(marked(withUnseen("nagi", "hina"))).toEqual(["nagi", "hina"]);
    expect(marked(withUnseen())).toEqual([]);
  });

  it("当前对话正显示着的那位不标", () => {
    expect(marked(withUnseen("nagi", "hina"), { onScreen: "nagi" })).toEqual(["hina"]);
  });

  it("导航上的点：只要列表里有一行有没看过的搭话；当前对话正显示着的、在这台设备上隐藏了的、配置里已经没有的不算", () => {
    const hidden = { preferences: { hidden: ["nagi"], pinned: [] } };

    expect(hasUnseen(characters, withUnseen("hina")), "有一行").toBe(true);
    expect(hasUnseen(characters, withUnseen()), "一行都没有").toBe(false);
    expect(hasUnseen(characters, withUnseen("hina"), { onScreen: "hina" }), "只有正显示着的那位").toBe(false);
    expect(hasUnseen(characters, withUnseen("nagi", "gone"), hidden), "只有隐藏的和配置里没有的").toBe(false);
  });
});

describe("unitsOf", () => {
  const member = (id: string, unit: string | null, unit_order: number | null) => ({ id, unit, unit_order });

  it("按组合的官方顺序分组，组内保持接口顺序，没有组合或对不上官方顺序的放在最后", () => {
    const groups = unitsOf([
      member("riku", "Sample Harmony", 1),
      member("guest", null, null),
      member("stray", "未知", null),
      member("sora", "Sample Stars", 0),
      member("mina", "Sample Harmony", 1),
      member("nagi", "Sample Stars", 0),
    ]);

    expect(groups.map((g) => [g.unit, g.members.map((c) => c.id)])).toEqual([
      ["Sample Stars", ["sora", "nagi"]],
      ["Sample Harmony", ["riku", "mina"]],
      [null, ["guest", "stray"]],
    ]);
  });
});
